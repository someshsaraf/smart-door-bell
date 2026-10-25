/*
 * Outdoor doorbell networking. See doorbell_net.h for the API.
 *
 * MQTT: a minimal MQTT 3.1.1 client (QoS 0 only) on tal_net sockets. The
 * SDK's libmqtt wrapper blocks for up to 5 s per read when the line is idle,
 * which would delay a ring; here every wait is a short select() so a bell
 * press goes out within one loop pass (~50 ms).
 *
 * Encryption: with Outdoor/src/doorbell_secret.h present (a pre-shared key,
 * kept out of git), MQTT runs over TLS 1.2 with that key on port 8883
 * (ECDHE-PSK-AES128-CBC-SHA256: forward secrecy, and only a doorbell holding
 * the key gets in). PSK needs no certificates, so it works before the clock
 * is set from NTP and whatever address the Pi has. Without the header the
 * link is plain MQTT on 1883, and the build says so.
 */
#if defined(__has_include)
#if __has_include("doorbell_secret.h")
#include "doorbell_secret.h"
#endif
#endif
#include "tuya_cloud_types.h"
#include "tal_api.h"
#include "tal_kv.h"
#include "tal_wifi.h"
#include "tal_network.h"
#include "tal_time_service.h"
#include "cJSON.h"
#include "doorbell_net.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef DOORBELL_PSK_HEX
#define BROKER_TLS  1
#define BROKER_PORT DOORBELL_MQTT_TLS_PORT
#include "tuya_tls.h" /* tuya_tls_init (mbedtls allocator), tuya_tls_random */
#include "mbedtls/ssl.h"
#else
#define BROKER_TLS  0
#define BROKER_PORT DOORBELL_MQTT_PORT
#warning "Outdoor/src/doorbell_secret.h missing: MQTT to the indoor unit is NOT encrypted"
#endif

#define KV_WIFI   "db_wifi"
#define KV_BROKER "db_broker"

#define LOOP_MS             50
#define WIFI_CONNECT_MS     20000 /* give up on a connection attempt after this */
#define WIFI_RETRY_MS       10000 /* reconnect to the saved network after a drop */
#define MQTT_RETRY_MS       5000
#define MQTT_KEEPALIVE_S    30
#define MQTT_ACK_MS         3000
#define TCP_CONNECT_MS      3000 /* a firewalled broker drops packets: never wait on TCP's own retries */
#define START_MAX_AGE_MS    5000 /* a ring older than this is not worth sending late */
#define NTP_WAIT_MS         2000
#define NTP_RETRY_MS        15000
#define NTP_REFRESH_MS      (6UL * 3600UL * 1000UL)
#define NTP_UNIX_DELTA      2208988800UL /* seconds from 1900 (NTP epoch) to 1970 */

/* ---------- shared state (guarded by lock) ---------- */

static MUTEX_HANDLE lock;
static net_status_t st;
static struct {
    bool scan, connect, broker, stop;
    bool start;
    uint32_t start_secs, start_at;
    char ssid[NET_SSID_MAX + 1], pswd[NET_PSWD_MAX + 1];
    bool report; /* UI settings below changed: republish the state */
    net_settings_t settings;
} req;
static volatile int wifi_event = -1; /* last WF_EVENT_E from the driver, -1 = none */

/* ---------- net-thread-only state ---------- */

static THREAD_HANDLE thread;
static char saved_ssid[NET_SSID_MAX + 1], saved_pswd[NET_PSWD_MAX + 1];
static char try_ssid[NET_SSID_MAX + 1], try_pswd[NET_PSWD_MAX + 1];
static bool trying_new; /* current attempt uses credentials not saved yet */
static uint32_t wifi_since, wifi_retry_at, mqtt_retry_at, ntp_due_at;
static uint32_t ntp_server;
static const char *const ntp_servers[] = {"pool.ntp.org", "time.google.com", "time.cloudflare.com"};

/* The ring being delivered: resent until acknowledged or out of attempts. */
static struct {
    bool active;
    uint32_t id, secs, pressed_at, sent_at, sends;
} ring;

/* Work asked for by the indoor unit, done on the next loop pass (not inside
 * the MQTT receive path, since joining a network drops the connection). */
static bool remote_scan, state_dirty;

/*
 * A network change asked for by the indoor unit: a new Wi-Fi and/or a new
 * broker address, applied as one unit. Nothing is saved until the doorbell
 * has joined the Wi-Fi AND reached the broker; if that does not happen within
 * NET_CHANGE_MS it goes back to the previous network and broker, so a typo
 * can never leave it unreachable.
 */
#define NET_CHANGE_MS 60000
static struct {
    bool requested, active, new_wifi;
    bool wifi_up; /* the new Wi-Fi has connected (not just the old one still being up) */
    char ssid[NET_SSID_MAX + 1], pswd[NET_PSWD_MAX + 1], broker[NET_HOST_MAX + 1];
    uint32_t deadline;
} change;
static char change_result[12]; /* "applied" / "reverted": reported in the state */
static void change_commit(void);
static void change_revert(const char *why);

static int sock = -1;
static uint8_t rx[1024];
static uint8_t tx[1600]; /* largest message: the Wi-Fi scan list */
static uint32_t rx_len, last_tx, ping_sent;
static uint16_t packet_id = 1;

static uint32_t now_ms(void)
{
    return (uint32_t)tal_system_get_millisecond();
}
static bool due(uint32_t at)
{
    return (int32_t)(now_ms() - at) >= 0;
}

/* ---------- link to the broker: plain TCP, or TLS over it ---------- */

#define LINK_AGAIN -2 /* nothing to read yet (TLS: a record not complete) */

#if BROKER_TLS
#define TLS_IO_MS        3000  /* one read during the handshake or of a split record */
#define TLS_HANDSHAKE_MS 10000
static mbedtls_ssl_context ssl;
static mbedtls_ssl_config ssl_conf;
static bool tls_up;
static uint8_t psk[32];
static size_t psk_len;
static const int psk_suites[] = {MBEDTLS_TLS_ECDHE_PSK_WITH_AES_128_CBC_SHA256, 0};

static int tls_rng(void *ctx, unsigned char *out, size_t len)
{
    (void)ctx;
    return tuya_tls_random(out, len);
}

static int bio_send(void *ctx, const unsigned char *buf, size_t len)
{
    (void)ctx;
    int n = tal_net_send(sock, buf, (uint32_t)len);
    return n > 0 ? n : MBEDTLS_ERR_SSL_INTERNAL_ERROR;
}

static int bio_recv(void *ctx, unsigned char *buf, size_t len)
{
    (void)ctx;
    TUYA_FD_SET_T rd;
    tal_net_fd_zero(&rd);
    tal_net_fd_set(sock, &rd);
    if (tal_net_select(sock + 1, &rd, NULL, NULL, TLS_IO_MS) <= 0)
        return MBEDTLS_ERR_SSL_TIMEOUT;
    int n = tal_net_recv(sock, buf, (uint32_t)len);
    return n > 0 ? n : n == 0 ? MBEDTLS_ERR_SSL_CONN_EOF : MBEDTLS_ERR_SSL_INTERNAL_ERROR;
}

static int hex_nibble(char c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

static void tls_free(void)
{
    mbedtls_ssl_free(&ssl);
    mbedtls_ssl_config_free(&ssl_conf);
    tls_up = false;
}

/* Handshake on the connected socket; false (and a log line) if the key or the broker's TLS listener is wrong. */
static bool tls_start(void)
{
    static bool lib_ready;
    if (!lib_ready) {
        tuya_tls_init(); /* mbedtls heap (PSRAM) and threading hooks */
        const char *h = DOORBELL_PSK_HEX;
        for (psk_len = 0; psk_len < sizeof(psk) && hex_nibble(h[0]) >= 0 && hex_nibble(h[1]) >= 0; h += 2)
            psk[psk_len++] = (uint8_t)(hex_nibble(h[0]) << 4 | hex_nibble(h[1]));
        lib_ready = true;
    }
    mbedtls_ssl_init(&ssl);
    mbedtls_ssl_config_init(&ssl_conf);
    int r = mbedtls_ssl_config_defaults(&ssl_conf, MBEDTLS_SSL_IS_CLIENT, MBEDTLS_SSL_TRANSPORT_STREAM,
                                        MBEDTLS_SSL_PRESET_DEFAULT);
    if (r == 0) {
        mbedtls_ssl_conf_rng(&ssl_conf, tls_rng, NULL);
        mbedtls_ssl_conf_ciphersuites(&ssl_conf, psk_suites);
        r = mbedtls_ssl_conf_psk(&ssl_conf, psk, psk_len, (const unsigned char *)DOORBELL_PSK_IDENTITY,
                                 strlen(DOORBELL_PSK_IDENTITY));
    }
    if (r == 0)
        r = mbedtls_ssl_setup(&ssl, &ssl_conf);
    if (r == 0) {
        mbedtls_ssl_set_bio(&ssl, NULL, bio_send, bio_recv, NULL);
        uint32_t until = now_ms() + TLS_HANDSHAKE_MS;
        while ((r = mbedtls_ssl_handshake(&ssl)) == MBEDTLS_ERR_SSL_WANT_READ || r == MBEDTLS_ERR_SSL_WANT_WRITE ||
               r == MBEDTLS_ERR_SSL_TIMEOUT)
            if (due(until))
                break;
    }
    if (r != 0) {
        PR_ERR("[NET] TLS with the broker failed (-0x%04x): same key on both sides? 8883 listener set up?", -r);
        tls_free();
        return false;
    }
    tls_up = true;
    PR_NOTICE("[NET] encrypted: %s", mbedtls_ssl_get_ciphersuite(&ssl));
    return true;
}
#endif

static int link_write(const uint8_t *buf, uint32_t len)
{
#if BROKER_TLS
    if (tls_up) {
        int n;
        while ((n = mbedtls_ssl_write(&ssl, buf, len)) == MBEDTLS_ERR_SSL_WANT_WRITE)
            ;
        return n;
    }
#endif
    return tal_net_send(sock, buf, len);
}

/* Bytes read, 0 when the broker closed, LINK_AGAIN when nothing complete yet, < 0 on errors. */
static int link_read(uint8_t *buf, uint32_t len)
{
#if BROKER_TLS
    if (tls_up) {
        int n = mbedtls_ssl_read(&ssl, buf, len);
        if (n == MBEDTLS_ERR_SSL_WANT_READ || n == MBEDTLS_ERR_SSL_WANT_WRITE || n == MBEDTLS_ERR_SSL_TIMEOUT)
            return LINK_AGAIN;
        return n == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY ? 0 : n;
    }
#endif
    return tal_net_recv(sock, buf, len);
}

/* Data to read within `ms`: decrypted bytes TLS already holds count too,
 * since the socket itself would not report them. */
static bool link_readable(uint32_t ms)
{
#if BROKER_TLS
    if (tls_up && (mbedtls_ssl_get_bytes_avail(&ssl) > 0 || mbedtls_ssl_check_pending(&ssl)))
        return true;
#endif
    TUYA_FD_SET_T rd;
    tal_net_fd_zero(&rd);
    tal_net_fd_set(sock, &rd);
    return tal_net_select(sock + 1, &rd, NULL, NULL, ms) > 0;
}

static void set_mqtt_state(net_mqtt_state_t s)
{
    tal_mutex_lock(lock);
    st.mqtt = s;
    tal_mutex_unlock(lock);
}

static void set_ring_state(net_ring_state_t s)
{
    tal_mutex_lock(lock);
    st.ring = s;
    tal_mutex_unlock(lock);
}

/* A dotted IPv4 address is used as is; only names go through DNS. */
static OPERATE_RET resolve_host(const char *host, TUYA_IP_ADDR_T *addr)
{
    const char *c = host;
    while (*c && ((*c >= '0' && *c <= '9') || *c == '.'))
        c++;
    if (*c == '\0') {
        *addr = tal_net_str2addr(host);
        return OPRT_OK;
    }
    return tal_net_gethostbyname(host, addr);
}

/* ---------- storage ---------- */

static bool kv_read_str(const char *key, char *out, size_t size)
{
    uint8_t *v = NULL;
    size_t len = 0;
    if (tal_kv_get(key, &v, &len) != OPRT_OK || !v)
        return false;
    if (len >= size)
        len = size - 1;
    memcpy(out, v, len);
    out[len] = '\0';
    tal_kv_free(v);
    return true;
}

/* Wi-Fi record: ssid '\0' password */
static void load_saved(void)
{
    uint8_t *v = NULL;
    size_t len = 0;
    if (tal_kv_get(KV_WIFI, &v, &len) == OPRT_OK && v) {
        size_t n = strnlen((char *)v, len);
        if (n > 0 && n <= NET_SSID_MAX && n < len) {
            memcpy(saved_ssid, v, n);
            saved_ssid[n] = '\0';
            snprintf(saved_pswd, sizeof(saved_pswd), "%.*s", (int)(len - n - 1), (char *)v + n + 1);
        }
        tal_kv_free(v);
    }
    tal_mutex_lock(lock);
    kv_read_str(KV_BROKER, st.broker, sizeof(st.broker));
    tal_mutex_unlock(lock);
}

static void save_wifi(void)
{
    uint8_t buf[NET_SSID_MAX + NET_PSWD_MAX + 2];
    size_t a = strlen(try_ssid), b = strlen(try_pswd);
    memcpy(buf, try_ssid, a + 1);
    memcpy(buf + a + 1, try_pswd, b);
    if (tal_kv_set(KV_WIFI, buf, a + 1 + b) == OPRT_OK)
        PR_NOTICE("[NET] saved Wi-Fi '%s'", try_ssid);
    strcpy(saved_ssid, try_ssid);
    strcpy(saved_pswd, try_pswd);
}

/* ---------- Wi-Fi ---------- */

static void wifi_cb(WF_EVENT_E event, void *arg)
{
    (void)arg;
    wifi_event = event; /* handled on the net thread */
}

static void wifi_begin(const char *ssid, const char *pswd, bool is_new)
{
    snprintf(try_ssid, sizeof(try_ssid), "%s", ssid);
    snprintf(try_pswd, sizeof(try_pswd), "%s", pswd);
    trying_new = is_new;
    wifi_since = now_ms();
    tal_mutex_lock(lock);
    st.wifi = NET_WIFI_CONNECTING;
    snprintf(st.ssid, sizeof(st.ssid), "%s", ssid);
    st.ip[0] = '\0';
    tal_mutex_unlock(lock);
    PR_NOTICE("[NET] connecting to '%s'", ssid);
    tal_wifi_station_disconnect();
    tal_wifi_station_connect((int8_t *)try_ssid, (int8_t *)try_pswd);
}

static void wifi_fail(void)
{
    tal_mutex_lock(lock);
    st.wifi = NET_WIFI_FAILED;
    tal_mutex_unlock(lock);
    /* The retry uses the saved network, so a wrong new password never loses
     * the one that worked before. Nothing is retried if none was saved. */
    wifi_since = 0;
    wifi_retry_at = now_ms() + WIFI_RETRY_MS;
    trying_new = false;
}

static int ap_cmp_rssi(const void *a, const void *b)
{
    return ((const net_ap_t *)b)->rssi - ((const net_ap_t *)a)->rssi;
}

static void wifi_scan(void)
{
    AP_IF_S *aps = NULL;
    uint32_t n = 0;
    static net_ap_t found[NET_MAX_APS];
    uint32_t count = 0;

    if (tal_wifi_all_ap_scan(&aps, &n) == OPRT_OK && aps) {
        for (uint32_t i = 0; i < n; i++) {
            const char *ssid = (const char *)aps[i].ssid;
            uint32_t len = aps[i].s_len > NET_SSID_MAX ? NET_SSID_MAX : aps[i].s_len;
            if (len == 0 || ssid[0] == '\0')
                continue; /* hidden network */
            uint32_t j;
            for (j = 0; j < count; j++)
                if (strlen(found[j].ssid) == len && memcmp(found[j].ssid, ssid, len) == 0)
                    break;
            if (j < count) { /* same network on another AP/band: keep the strongest */
                if (aps[i].rssi > found[j].rssi)
                    found[j].rssi = aps[i].rssi;
                continue;
            }
            if (count == NET_MAX_APS)
                continue;
            memcpy(found[count].ssid, ssid, len);
            found[count].ssid[len] = '\0';
            found[count].rssi = aps[i].rssi;
            found[count].secure = aps[i].security != WAAM_OPEN;
            count++;
        }
        tal_wifi_release_ap(aps);
    }
    qsort(found, count, sizeof(found[0]), ap_cmp_rssi);

    tal_mutex_lock(lock);
    memcpy(st.aps, found, count * sizeof(found[0]));
    st.ap_count = count;
    st.scanning = false;
    st.scan_seq++;
    tal_mutex_unlock(lock);
    PR_NOTICE("[NET] scan found %u networks", (unsigned)count);
}

static void wifi_service(void)
{
    int ev = wifi_event;
    if (ev >= 0) {
        wifi_event = -1;
        if (ev == WFE_CONNECTED) {
            NW_IP_S ip;
            memset(&ip, 0, sizeof(ip));
            tal_wifi_get_ip(WF_STATION, &ip);
            if (trying_new)
                save_wifi();
            trying_new = false;
            wifi_since = 0;
            tal_mutex_lock(lock);
            st.wifi = NET_WIFI_CONNECTED;
            snprintf(st.ip, sizeof(st.ip), "%s", ip.nwipstr);
            tal_mutex_unlock(lock);
            PR_NOTICE("[NET] Wi-Fi up, ip %s", ip.nwipstr);
            if (change.active)
                change.wifi_up = true;
            mqtt_retry_at = now_ms();
            ntp_due_at = now_ms();
        } else if (ev == WFE_CONNECT_FAILED) {
            PR_NOTICE("[NET] Wi-Fi connect failed");
            if (change.active && change.new_wifi)
                change_revert("could not join the new Wi-Fi");
            else
                wifi_fail();
        } else if (ev == WFE_DISCONNECTED) {
            PR_NOTICE("[NET] Wi-Fi disconnected");
            tal_mutex_lock(lock);
            st.wifi = saved_ssid[0] ? NET_WIFI_CONNECTING : NET_WIFI_NONE;
            st.ip[0] = '\0';
            tal_mutex_unlock(lock);
            wifi_retry_at = now_ms() + WIFI_RETRY_MS;
        }
    }

    tal_mutex_lock(lock);
    net_wifi_state_t w = st.wifi;
    tal_mutex_unlock(lock);
    if (w == NET_WIFI_CONNECTING && wifi_since && now_ms() - wifi_since > WIFI_CONNECT_MS) {
        PR_NOTICE("[NET] Wi-Fi connect timed out");
        if (change.active && change.new_wifi)
            change_revert("the new Wi-Fi did not connect in time");
        else
            wifi_fail();
    } else if (w != NET_WIFI_CONNECTED && saved_ssid[0] && wifi_retry_at && due(wifi_retry_at) &&
               !(w == NET_WIFI_CONNECTING && wifi_since)) {
        wifi_retry_at = 0;
        wifi_begin(saved_ssid, saved_pswd, false);
    }
}

/* ---------- clock (SNTP) ---------- */

static bool ntp_query(const char *host)
{
    TUYA_IP_ADDR_T addr, from;
    uint16_t port;
    uint8_t pkt[48] = {0x1B}; /* LI 0, version 3, mode 3 (client) */
    bool ok = false;

    if (resolve_host(host, &addr) != OPRT_OK)
        return false;
    int fd = tal_net_socket_create(PROTOCOL_UDP);
    if (fd < 0)
        return false;
    if (tal_net_send_to(fd, pkt, sizeof(pkt), addr, 123) == (int)sizeof(pkt)) {
        TUYA_FD_SET_T rd;
        tal_net_fd_zero(&rd);
        tal_net_fd_set(fd, &rd);
        if (tal_net_select(fd + 1, &rd, NULL, NULL, NTP_WAIT_MS) > 0 &&
            tal_net_recvfrom(fd, pkt, sizeof(pkt), &from, &port) == (int)sizeof(pkt) && (pkt[0] & 0x07) == 4) {
            /* transmit timestamp, seconds part */
            uint32_t secs = ((uint32_t)pkt[40] << 24) | ((uint32_t)pkt[41] << 16) | ((uint32_t)pkt[42] << 8) | pkt[43];
            if (secs > NTP_UNIX_DELTA) {
                tal_time_set_posix((TIME_T)(secs - NTP_UNIX_DELTA), 2);
                ok = true;
            }
        }
    }
    tal_net_close(fd);
    return ok;
}

static void ntp_service(void)
{
    if (!due(ntp_due_at))
        return;
    if (ntp_query(ntp_servers[ntp_server])) {
        PR_NOTICE("[NET] time set from %s", ntp_servers[ntp_server]);
        ntp_due_at = now_ms() + NTP_REFRESH_MS;
        tal_mutex_lock(lock);
        st.time_synced = true;
        tal_mutex_unlock(lock);
        state_dirty = true;
    } else {
        PR_ERR("[NET] no time from %s", ntp_servers[ntp_server]);
        ntp_server = (ntp_server + 1) % (sizeof(ntp_servers) / sizeof(ntp_servers[0]));
        ntp_due_at = now_ms() + NTP_RETRY_MS;
    }
}

/* ---------- MQTT 3.1.1, QoS 0 ---------- */

static int put_str(uint8_t *p, const char *s)
{
    size_t n = strlen(s);
    p[0] = (uint8_t)(n >> 8);
    p[1] = (uint8_t)n;
    memcpy(p + 2, s, n);
    return (int)n + 2;
}

/* Fixed header: type byte + variable-length "remaining length". */
static int put_header(uint8_t *p, uint8_t type, uint32_t remaining)
{
    int i = 0;
    p[i++] = type;
    do {
        uint8_t b = remaining & 0x7F;
        remaining >>= 7;
        p[i++] = b | (remaining ? 0x80 : 0);
    } while (remaining);
    return i;
}

static bool sock_send(const uint8_t *buf, int len)
{
    while (len > 0) {
        int n = link_write(buf, (uint32_t)len);
        if (n <= 0)
            return false;
        buf += n;
        len -= n;
    }
    last_tx = now_ms();
    return true;
}

static void mqtt_close(void)
{
    if (sock >= 0) {
#if BROKER_TLS
        if (tls_up) {
            mbedtls_ssl_close_notify(&ssl);
            tls_free();
        }
#endif
        tal_net_close(sock);
        sock = -1;
        PR_NOTICE("[NET] MQTT closed");
    }
    rx_len = 0;
    ping_sent = 0;
    mqtt_retry_at = now_ms() + MQTT_RETRY_MS;
    set_mqtt_state(NET_MQTT_DOWN);
}

static bool wait_readable(uint32_t ms)
{
    return link_readable(ms);
}

static bool mqtt_publish_ex(const char *topic, const char *payload, bool retain)
{
    size_t t = strlen(topic), p = strlen(payload);
    if (sock < 0 || t + p + 8 > sizeof(tx))
        return false;
    int i = put_header(tx, retain ? 0x31 : 0x30, (uint32_t)(2 + t + p));
    i += put_str(tx + i, topic);
    memcpy(tx + i, payload, p);
    if (!sock_send(tx, i + (int)p)) {
        mqtt_close();
        return false;
    }
    PR_NOTICE("[NET] -> %s %.120s", topic, payload);
    return true;
}

static bool mqtt_publish(const char *topic, const char *payload)
{
    return mqtt_publish_ex(topic, payload, false);
}

/* Publishes a cJSON object and frees it. */
static void publish_json(const char *topic, cJSON *obj, bool retain)
{
    char *s = cJSON_PrintUnformatted(obj);
    if (s) {
        mqtt_publish_ex(topic, s, retain);
        cJSON_free(s);
    }
    cJSON_Delete(obj);
}

/* Retained snapshot of everything the indoor settings page shows. */
static void publish_state(void)
{
    cJSON *o = cJSON_CreateObject();
    tal_mutex_lock(lock);
    const net_settings_t *s = &req.settings;
    cJSON_AddNumberToObject(o, "theme", s->theme);
    cJSON_AddNumberToObject(o, "bell_color", s->bell_color);
    cJSON_AddNumberToObject(o, "ring_seconds", s->ring_seconds);
    cJSON_AddNumberToObject(o, "bell_style", s->bell_style);
    cJSON_AddBoolToObject(o, "glow", s->glow);
    cJSON_AddNumberToObject(o, "chime", s->chime);
    cJSON_AddBoolToObject(o, "chime_repeat", s->chime_repeat);
    cJSON_AddNumberToObject(o, "volume", s->volume);
    if (change_result[0])
        cJSON_AddStringToObject(o, "network_change", change_result);
    cJSON_AddStringToObject(o, "wifi_ssid", st.ssid);
    cJSON_AddStringToObject(o, "ip", st.ip);
    cJSON_AddStringToObject(o, "broker", st.broker);
    cJSON_AddBoolToObject(o, "time_synced", st.time_synced);
    tal_mutex_unlock(lock);
    cJSON_AddStringToObject(o, "firmware", PROJECT_VERSION);
    publish_json(DOORBELL_TOPIC_STATE, o, true);
    state_dirty = false;
}

static void publish_scan(void)
{
    cJSON *o = cJSON_CreateObject(), *list = cJSON_AddArrayToObject(o, "networks");
    tal_mutex_lock(lock);
    for (uint32_t i = 0; i < st.ap_count; i++) {
        cJSON *n = cJSON_CreateObject();
        cJSON_AddStringToObject(n, "ssid", st.aps[i].ssid);
        cJSON_AddNumberToObject(n, "rssi", st.aps[i].rssi);
        cJSON_AddBoolToObject(n, "secure", st.aps[i].secure);
        cJSON_AddItemToArray(list, n);
    }
    tal_mutex_unlock(lock);
    publish_json(DOORBELL_TOPIC_SCAN, o, false);
}

static void mqtt_open(const char *host)
{
    TUYA_IP_ADDR_T addr;
    uint8_t buf[320];
    int i;

    set_mqtt_state(NET_MQTT_CONNECTING);
    if (resolve_host(host, &addr) != OPRT_OK) {
        PR_ERR("[NET] cannot resolve broker '%s'", host);
        mqtt_close();
        return;
    }
    sock = tal_net_socket_create(PROTOCOL_TCP);
    if (sock < 0) {
        mqtt_close();
        return;
    }
    /* Non-blocking connect bounded by TCP_CONNECT_MS. A refused connection
     * also reports writable; the CONNECT/CONNACK exchange below then fails. */
    TUYA_FD_SET_T wr;
    tal_net_set_block(sock, FALSE);
    tal_net_connect(sock, addr, BROKER_PORT);
    tal_net_fd_zero(&wr);
    tal_net_fd_set(sock, &wr);
    if (tal_net_select(sock + 1, NULL, &wr, NULL, TCP_CONNECT_MS) <= 0) {
        PR_ERR("[NET] broker %s:%d not answering (firewall or wrong address?)", host, BROKER_PORT);
        mqtt_close();
        return;
    }
    tal_net_set_block(sock, TRUE);
#if BROKER_TLS
    if (!tls_start()) {
        mqtt_close();
        return;
    }
#endif

    /* CONNECT: protocol "MQTT" level 4, clean session, optional user/pass, and
     * a retained last will so the broker reports "offline" if we vanish. */
    bool user = DOORBELL_MQTT_USER[0] != '\0', pass = DOORBELL_MQTT_PASS[0] != '\0';
    uint8_t body[288];
    int b = put_str(body, "MQTT");
    body[b++] = 4;
    body[b++] = 0x02 | 0x04 | 0x20 | (user ? 0x80 : 0) | (pass ? 0x40 : 0);
    body[b++] = 0;
    body[b++] = MQTT_KEEPALIVE_S;
    b += put_str(body + b, DOORBELL_MQTT_CLIENT);
    b += put_str(body + b, DOORBELL_TOPIC_ONLINE);
    b += put_str(body + b, "offline");
    if (user)
        b += put_str(body + b, DOORBELL_MQTT_USER);
    if (pass)
        b += put_str(body + b, DOORBELL_MQTT_PASS);
    i = put_header(buf, 0x10, (uint32_t)b);
    memcpy(buf + i, body, b);
    if (!sock_send(buf, i + b) || !wait_readable(MQTT_ACK_MS) || link_read(buf, 4) != 4 ||
        buf[0] != 0x20 || buf[3] != 0) {
        PR_ERR("[NET] broker refused the connection");
        mqtt_close();
        return;
    }

    /* SUBSCRIBE to stop, ack, config, festival and talk at QoS 0 (the SUBACK is ignored in the loop). */
    b = 0;
    body[b++] = (uint8_t)(packet_id >> 8);
    body[b++] = (uint8_t)packet_id;
    packet_id = packet_id == 0xFFFF ? 1 : packet_id + 1;
    b += put_str(body + b, DOORBELL_TOPIC_STOP);
    body[b++] = 0;
    b += put_str(body + b, DOORBELL_TOPIC_ACK);
    body[b++] = 0;
    b += put_str(body + b, DOORBELL_TOPIC_CONFIG);
    body[b++] = 0;
    b += put_str(body + b, DOORBELL_TOPIC_FESTIVAL);
    body[b++] = 0;
    b += put_str(body + b, DOORBELL_TOPIC_TALK);
    body[b++] = 0;
    i = put_header(buf, 0x82, (uint32_t)b);
    memcpy(buf + i, body, b);
    if (!sock_send(buf, i + b)) {
        mqtt_close();
        return;
    }
    rx_len = 0;
    ping_sent = 0;
    set_mqtt_state(NET_MQTT_UP);
    PR_NOTICE("[NET] MQTT connected to %s", host);
    if (change.active && (!change.new_wifi || change.wifi_up))
        change_commit(); /* new Wi-Fi and broker both work */
    mqtt_publish_ex(DOORBELL_TOPIC_ONLINE, "online", true);
    publish_state();
}

/* ---------- network change from the indoor unit ---------- */

static void change_begin(void)
{
    change.requested = false;
    change.active = true;
    change.wifi_up = false;
    change.deadline = now_ms() + NET_CHANGE_MS;
    if (!change.broker[0]) { /* Wi-Fi only: same broker */
        tal_mutex_lock(lock);
        strcpy(change.broker, st.broker);
        tal_mutex_unlock(lock);
    }
    PR_NOTICE("[NET] network change: Wi-Fi %s%s%s, broker %s", change.new_wifi ? "'" : "",
              change.new_wifi ? change.ssid : "unchanged", change.new_wifi ? "'" : "", change.broker);
    if (sock >= 0)
        mqtt_close();
    mqtt_retry_at = now_ms();
    if (change.new_wifi)
        wifi_begin(change.ssid, change.pswd, false); /* saved only when the broker is reached too */
}

/* The new network works end to end: keep it. */
static void change_commit(void)
{
    if (change.new_wifi)
        save_wifi(); /* try_ssid / try_pswd: the network just joined */
    tal_kv_set(KV_BROKER, (const uint8_t *)change.broker, strlen(change.broker));
    tal_mutex_lock(lock);
    snprintf(st.broker, sizeof(st.broker), "%s", change.broker);
    tal_mutex_unlock(lock);
    change.active = false;
    strcpy(change_result, "applied");
    PR_NOTICE("[NET] network change applied and saved");
}

/* It did not work: back to the saved Wi-Fi and broker. */
static void change_revert(const char *why)
{
    PR_ERR("[NET] network change failed (%s): back to the previous network", why);
    change.active = false;
    strcpy(change_result, "reverted");
    state_dirty = true;
    if (sock >= 0)
        mqtt_close();
    mqtt_retry_at = now_ms();
    if (change.new_wifi && saved_ssid[0])
        wifi_begin(saved_ssid, saved_pswd, false);
}

/* A settings change from the indoor unit. Unknown or invalid fields are ignored. */
static void handle_config(const char *json)
{
    cJSON *j = cJSON_Parse(json);
    if (!j)
        return;
    const cJSON *theme = cJSON_GetObjectItem(j, "theme"), *bell = cJSON_GetObjectItem(j, "bell_color");
    const cJSON *ring_s = cJSON_GetObjectItem(j, "ring_seconds"), *wifi = cJSON_GetObjectItem(j, "wifi");
    const cJSON *broker = cJSON_GetObjectItem(j, "broker"), *cmd = cJSON_GetObjectItem(j, "command");
    const cJSON *style = cJSON_GetObjectItem(j, "bell_style"), *glow = cJSON_GetObjectItem(j, "glow");
    const cJSON *chime = cJSON_GetObjectItem(j, "chime"), *rep = cJSON_GetObjectItem(j, "chime_repeat");
    const cJSON *vol = cJSON_GetObjectItem(j, "volume");

    if (cJSON_IsNumber(theme) || cJSON_IsNumber(bell) || cJSON_IsNumber(ring_s) || cJSON_IsNumber(style) ||
        cJSON_IsBool(glow) || cJSON_IsNumber(chime) || cJSON_IsBool(rep) || cJSON_IsNumber(vol)) {
        tal_mutex_lock(lock);
        st.remote_theme = cJSON_IsNumber(theme) ? theme->valueint : -1;
        st.remote_bell = cJSON_IsNumber(bell) ? bell->valueint : -1;
        st.remote_ring = cJSON_IsNumber(ring_s) ? ring_s->valueint : -1;
        st.remote_style = cJSON_IsNumber(style) ? style->valueint : -1;
        st.remote_glow = cJSON_IsBool(glow) ? cJSON_IsTrue(glow) : -1;
        st.remote_chime = cJSON_IsNumber(chime) ? chime->valueint : -1;
        st.remote_repeat = cJSON_IsBool(rep) ? cJSON_IsTrue(rep) : -1;
        st.remote_volume = cJSON_IsNumber(vol) ? vol->valueint : -1;
        st.remote_seq++;
        tal_mutex_unlock(lock);
    }
    /* Network change: {"network":{"ssid","password","broker"}}, any of them optional.
     * The older separate "wifi" object and "broker" string take the same safe path. */
    const cJSON *net = cJSON_GetObjectItem(j, "network");
    const cJSON *w = cJSON_IsObject(net) ? net : cJSON_IsObject(wifi) ? wifi : NULL;
    const cJSON *ssid = w ? cJSON_GetObjectItem(w, "ssid") : NULL, *pw = w ? cJSON_GetObjectItem(w, "password") : NULL;
    const cJSON *host = cJSON_IsObject(net) ? cJSON_GetObjectItem(net, "broker") : broker;
    bool has_ssid = cJSON_IsString(ssid) && ssid->valuestring[0];
    bool has_host = cJSON_IsString(host) && host->valuestring[0];
    if (has_ssid || has_host) {
        const char *p = cJSON_IsString(pw) ? pw->valuestring : "";
        if (change.active || change.requested) {
            PR_ERR("[NET] network change ignored: another one is in progress");
        } else if ((has_ssid && (strlen(ssid->valuestring) > NET_SSID_MAX || strlen(p) > NET_PSWD_MAX ||
                                 (p[0] && strlen(p) < 8))) ||
                   (has_host && strlen(host->valuestring) > NET_HOST_MAX)) {
            PR_ERR("[NET] network change rejected: invalid SSID, password or address");
        } else {
            change.new_wifi = has_ssid;
            snprintf(change.ssid, sizeof(change.ssid), "%s", has_ssid ? ssid->valuestring : "");
            snprintf(change.pswd, sizeof(change.pswd), "%s", has_ssid ? p : "");
            snprintf(change.broker, sizeof(change.broker), "%s", has_host ? host->valuestring : "");
            change.requested = true; /* started on the next loop pass: joining a network drops this connection */
        }
    }
    if (cJSON_IsString(cmd) && strcmp(cmd->valuestring, "wifi_scan") == 0)
        remote_scan = true;
    cJSON_Delete(j);
}

/* {"festival":"diwali"|"none","until":<UTC s>,"greeting":"...","tones":true} (retained). */
static void handle_festival(const char *json)
{
    cJSON *j = cJSON_Parse(json);
    if (!j)
        return;
    const cJSON *f = cJSON_GetObjectItem(j, "festival"), *until = cJSON_GetObjectItem(j, "until");
    const cJSON *g = cJSON_GetObjectItem(j, "greeting"), *tones = cJSON_GetObjectItem(j, "tones");
    const char *key = cJSON_IsString(f) && strcmp(f->valuestring, "none") ? f->valuestring : "";
    tal_mutex_lock(lock);
    snprintf(st.festival, sizeof(st.festival), "%s", key);
    snprintf(st.festival_greeting, sizeof(st.festival_greeting), "%s", cJSON_IsString(g) ? g->valuestring : "");
    st.festival_until = cJSON_IsNumber(until) && until->valuedouble > 0 ? (uint32_t)until->valuedouble : 0;
    st.festival_tones = !cJSON_IsBool(tones) || cJSON_IsTrue(tones);
    st.festival_seq++;
    tal_mutex_unlock(lock);
    cJSON_Delete(j);
}

/* {"command":"start","host":"192.168.1.102","port":5004} or {"command":"end"} */
static void handle_talk(const char *json)
{
    cJSON *j = cJSON_Parse(json);
    if (!j)
        return;
    const cJSON *cmd = cJSON_GetObjectItem(j, "command"), *host = cJSON_GetObjectItem(j, "host");
    const cJSON *port = cJSON_GetObjectItem(j, "port");
    bool start = cJSON_IsString(cmd) && strcmp(cmd->valuestring, "start") == 0;
    if (start || (cJSON_IsString(cmd) && strcmp(cmd->valuestring, "end") == 0)) {
        tal_mutex_lock(lock);
        st.talk_on = start;
        snprintf(st.talk_host, sizeof(st.talk_host), "%s", cJSON_IsString(host) ? host->valuestring : "");
        st.talk_port = cJSON_IsNumber(port) ? (uint16_t)port->valueint : 0;
        st.talk_seq++;
        tal_mutex_unlock(lock);
    }
    cJSON_Delete(j);
}

static bool topic_is(const uint8_t *topic, uint32_t len, const char *name)
{
    return len == strlen(name) && memcmp(topic, name, len) == 0;
}

static void handle_publish(const uint8_t *p, uint32_t len, uint8_t flags)
{
    if (len < 2)
        return;
    uint32_t tlen = ((uint32_t)p[0] << 8) | p[1];
    if (tlen + 2 > len || (flags & 0x06)) /* only QoS 0 is subscribed for */
        return;
    const uint8_t *topic = p + 2;

    if (topic_is(topic, tlen, DOORBELL_TOPIC_TALK)) {
        char payload[160];
        uint32_t plen = len - 2 - tlen;
        if (plen >= sizeof(payload))
            return;
        memcpy(payload, topic + tlen, plen);
        payload[plen] = 0;
        PR_NOTICE("[NET] <- talk %s", payload);
        handle_talk(payload);
    } else if (topic_is(topic, tlen, DOORBELL_TOPIC_FESTIVAL)) {
        char payload[200];
        uint32_t plen = len - 2 - tlen;
        if (plen >= sizeof(payload))
            return;
        memcpy(payload, topic + tlen, plen);
        payload[plen] = '\0';
        PR_NOTICE("[NET] <- festival %s", payload);
        handle_festival(payload);
    } else if (topic_is(topic, tlen, DOORBELL_TOPIC_CONFIG)) {
        static char payload[sizeof(rx)];
        uint32_t plen = len - 2 - tlen;
        if (plen >= sizeof(payload))
            return;
        memcpy(payload, topic + tlen, plen);
        payload[plen] = '\0';
        PR_NOTICE("[NET] <- config %.120s", payload);
        handle_config(payload);
    } else if (topic_is(topic, tlen, DOORBELL_TOPIC_STOP)) {
        PR_NOTICE("[NET] <- stop");
        tal_mutex_lock(lock);
        st.stop_seq++;
        tal_mutex_unlock(lock);
    } else if (topic_is(topic, tlen, DOORBELL_TOPIC_ACK) && ring.active) {
        /* An ack counts only if it carries the event_id of the ring in flight. */
        char payload[160], want[32];
        uint32_t plen = len - 2 - tlen;
        if (plen >= sizeof(payload))
            plen = sizeof(payload) - 1;
        memcpy(payload, topic + tlen, plen);
        payload[plen] = '\0';
        snprintf(want, sizeof(want), "\"outdoor-%u\"", (unsigned)ring.id);
        if (strstr(payload, want)) {
            PR_NOTICE("[NET] <- ack after %u send(s)", (unsigned)ring.sends);
            ring.active = false;
            set_ring_state(NET_RING_DELIVERED);
        }
    }
}

/* Sends or resends the ring in flight when it is due. */
static void ring_service(void)
{
    if (!ring.active || (ring.sends > 0 && now_ms() - ring.sent_at < DOORBELL_ACK_WAIT_MS))
        return;
    if (ring.sends > DOORBELL_START_RESENDS) {
        PR_ERR("[NET] indoor unit did not acknowledge the ring");
        ring.active = false;
        set_ring_state(NET_RING_FAILED);
        return;
    }
    char msg[96];
    snprintf(msg, sizeof(msg), "{\"command\":\"start\",\"timer\":%u,\"event_id\":\"outdoor-%u\"}",
             (unsigned)ring.secs, (unsigned)ring.id);
    if (mqtt_publish(DOORBELL_TOPIC_START, msg)) {
        ring.sends++;
        ring.sent_at = now_ms();
    }
}

/* Waits up to `ms` for data and handles every complete packet received. */
static void mqtt_poll(uint32_t ms)
{
    if (wait_readable(ms)) {
        if (rx_len == sizeof(rx)) {
            mqtt_close(); /* a packet bigger than we ever expect */
            return;
        }
        int n = link_read(rx + rx_len, sizeof(rx) - rx_len);
        if (n != LINK_AGAIN && n <= 0) {
            mqtt_close();
            return;
        }
        if (n > 0)
            rx_len += (uint32_t)n;
    }

    for (;;) {
        uint32_t remaining = 0, mult = 1, i = 1;
        bool complete = false;
        while (i < rx_len && i <= 4) {
            remaining += (rx[i] & 0x7F) * mult;
            mult <<= 7;
            if (!(rx[i++] & 0x80)) {
                complete = true;
                break;
            }
        }
        if (!complete || rx_len < i + remaining)
            break;
        uint8_t type = rx[0] & 0xF0;
        if (type == 0x30)
            handle_publish(rx + i, remaining, rx[0] & 0x0F);
        else if (type == 0xD0)
            ping_sent = 0; /* PINGRESP */
        memmove(rx, rx + i + remaining, rx_len - i - remaining);
        rx_len -= i + remaining;
    }

    /* keep-alive */
    if (ping_sent && now_ms() - ping_sent > MQTT_ACK_MS * 3) {
        PR_ERR("[NET] broker stopped answering");
        mqtt_close();
    } else if (!ping_sent && now_ms() - last_tx > MQTT_KEEPALIVE_S * 500) {
        static const uint8_t ping[] = {0xC0, 0x00};
        if (sock_send(ping, 2))
            ping_sent = now_ms();
        else
            mqtt_close();
    }
}

/* ---------- thread ---------- */

static void net_thread(void *arg)
{
    (void)arg;
    load_saved();
    tal_wifi_init(wifi_cb);
    tal_wifi_set_work_mode(WWM_STATION);
    if (saved_ssid[0])
        wifi_begin(saved_ssid, saved_pswd, false);

    for (;;) {
        tal_mutex_lock(lock);
        bool do_scan = req.scan, do_connect = req.connect, broker_changed = req.broker, do_stop = req.stop;
        req.scan = req.connect = req.broker = req.stop = false;
        char ssid[NET_SSID_MAX + 1], pswd[NET_PSWD_MAX + 1], host[NET_HOST_MAX + 1];
        strcpy(ssid, req.ssid);
        strcpy(pswd, req.pswd);
        strcpy(host, st.broker);
        if (req.start) {
            req.start = false;
            ring.active = true;
            ring.id = req.start_at; /* press time in ms: unique per press, same for every resend */
            ring.secs = req.start_secs;
            ring.pressed_at = req.start_at;
            ring.sends = 0;
            st.ring = NET_RING_SENDING;
        }
        if (req.report) {
            req.report = false;
            state_dirty = true;
        }
        net_wifi_state_t w = st.wifi;
        tal_mutex_unlock(lock);

        if (change.requested) {
            change_begin();
            tal_mutex_lock(lock);
            w = st.wifi; /* "connecting" now if a new Wi-Fi is being joined */
            tal_mutex_unlock(lock);
        }
        if (change.active && due(change.deadline))
            change_revert("the indoor unit was not reached in time");
        if (change.active)
            strcpy(host, change.broker); /* try the new broker; st.broker stays the saved one */
        if (remote_scan) {
            remote_scan = false;
            tal_mutex_lock(lock);
            st.scanning = true;
            tal_mutex_unlock(lock);
            wifi_scan();
            publish_scan();
        }

        /* Not out within START_MAX_AGE_MS, or no ack by the end of all resends
         * (e.g. MQTT dropped in between): too late to be useful. */
        uint32_t age = now_ms() - ring.pressed_at;
        if (ring.active && ((ring.sends == 0 && age > START_MAX_AGE_MS) ||
                            age > START_MAX_AGE_MS + (DOORBELL_START_RESENDS + 1) * DOORBELL_ACK_WAIT_MS)) {
            PR_ERR("[NET] ring not delivered: indoor unit not connected");
            ring.active = false;
            set_ring_state(NET_RING_FAILED);
        }
        if (do_stop && ring.active) {
            ring.active = false; /* no resends after a stop */
            set_ring_state(NET_RING_NONE);
        }

        if (do_connect)
            wifi_begin(ssid, pswd, true);
        if (do_scan)
            wifi_scan();
        wifi_service();
        if (broker_changed) {
            if (sock >= 0)
                mqtt_close();
            mqtt_retry_at = now_ms();
        }

        if (w == NET_WIFI_CONNECTED)
            ntp_service();
        if (w == NET_WIFI_CONNECTED && host[0]) {
            if (sock < 0 && due(mqtt_retry_at))
                mqtt_open(host);
            if (sock >= 0) {
                ring_service();
                if (state_dirty && sock >= 0)
                    publish_state();
                if (do_stop && sock >= 0)
                    mqtt_publish(DOORBELL_TOPIC_STOP, "{\"command\":\"stop\",\"source\":\"outdoor\"}");
                if (sock >= 0) {
                    mqtt_poll(LOOP_MS);
                    continue;
                }
            }
        } else if (sock >= 0) {
            mqtt_close();
        }
        if (do_stop)
            PR_NOTICE("[NET] stop not sent: indoor unit not connected");
        tal_system_sleep(LOOP_MS);
    }
}

void net_start(void)
{
    THREAD_CFG_T cfg;
    tal_mutex_create_init(&lock);
    memset(&cfg, 0, sizeof(cfg));
    cfg.stackDepth = 8 * 1024;
    cfg.priority = THREAD_PRIO_2;
    cfg.thrdname = "doorbell_net";
    tal_thread_create_and_start(&thread, NULL, NULL, net_thread, NULL, &cfg);
}

void net_get_status(net_status_t *out)
{
    tal_mutex_lock(lock);
    *out = st;
    tal_mutex_unlock(lock);
}

void net_scan(void)
{
    tal_mutex_lock(lock);
    if (!st.scanning) {
        st.scanning = true;
        req.scan = true;
    }
    tal_mutex_unlock(lock);
}

void net_connect(const char *ssid, const char *pswd)
{
    tal_mutex_lock(lock);
    snprintf(req.ssid, sizeof(req.ssid), "%s", ssid);
    snprintf(req.pswd, sizeof(req.pswd), "%s", pswd);
    req.connect = true;
    tal_mutex_unlock(lock);
}

void net_set_broker(const char *host)
{
    tal_kv_set(KV_BROKER, (const uint8_t *)host, strlen(host));
    tal_mutex_lock(lock);
    snprintf(st.broker, sizeof(st.broker), "%s", host);
    req.broker = true;
    tal_mutex_unlock(lock);
}

void net_publish_start(uint32_t seconds)
{
    tal_mutex_lock(lock);
    req.start = true;
    req.start_secs = seconds;
    req.start_at = now_ms();
    tal_mutex_unlock(lock);
}

void net_report_settings(const net_settings_t *s)
{
    tal_mutex_lock(lock);
    req.settings = *s;
    req.report = true;
    tal_mutex_unlock(lock);
}

void net_publish_stop(void)
{
    tal_mutex_lock(lock);
    req.start = false; /* a ring not yet picked up must not be sent after its stop */
    req.stop = true;
    tal_mutex_unlock(lock);
}
