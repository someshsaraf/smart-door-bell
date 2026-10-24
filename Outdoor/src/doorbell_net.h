/*
 * Outdoor doorbell networking: Wi-Fi station, saved credentials and a small
 * MQTT client that talks to the indoor Raspberry Pi dashboard.
 *
 * All work runs on a dedicated thread. The UI calls the request functions
 * (they only queue work and never block) and polls net_get_status().
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Must match Indoor/config.json. */
#define DOORBELL_TOPIC_START  "home/doorbell/start"
#define DOORBELL_TOPIC_STOP   "home/doorbell/stop"
#define DOORBELL_TOPIC_ACK    "home/doorbell/ack" /* indoor -> outdoor: start received */
/* Remote configuration from the indoor unit (see Indoor/topics.md). */
#define DOORBELL_TOPIC_STATE  "home/doorbell/outdoor/state"     /* outdoor -> retained settings + network */
#define DOORBELL_TOPIC_ONLINE "home/doorbell/outdoor/online"    /* retained "online"/"offline" (last will) */
#define DOORBELL_TOPIC_CONFIG "home/doorbell/outdoor/config"    /* indoor -> changes to apply */
#define DOORBELL_TOPIC_SCAN   "home/doorbell/outdoor/wifi_scan" /* outdoor -> networks seen */
#define DOORBELL_ACK_WAIT_MS  2000 /* resend the start if no ack within this */
#define DOORBELL_START_RESENDS 3   /* resends after the first send */
#define DOORBELL_MQTT_PORT    1883
#define DOORBELL_MQTT_CLIENT  "tuya-outdoor-doorbell"
#define DOORBELL_MQTT_USER    "" /* empty: anonymous, as in the Pi sample config */
#define DOORBELL_MQTT_PASS    ""

/* Local time = UTC + this. IST (+05:30), the indoor Pi's time zone. */
#define DOORBELL_UTC_OFFSET_S (5 * 3600 + 30 * 60)

#define NET_SSID_MAX  32
#define NET_PSWD_MAX  64
#define NET_HOST_MAX  63
#define NET_MAX_APS   20

typedef enum { NET_WIFI_NONE, NET_WIFI_CONNECTING, NET_WIFI_CONNECTED, NET_WIFI_FAILED } net_wifi_state_t;
typedef enum { NET_MQTT_DOWN, NET_MQTT_CONNECTING, NET_MQTT_UP } net_mqtt_state_t;
/* Delivery of the last ring to the indoor unit. */
typedef enum { NET_RING_NONE, NET_RING_SENDING, NET_RING_DELIVERED, NET_RING_FAILED } net_ring_state_t;

typedef struct {
    char ssid[NET_SSID_MAX + 1];
    int8_t rssi;
    bool secure;
} net_ap_t;

typedef struct {
    net_wifi_state_t wifi;
    char ssid[NET_SSID_MAX + 1]; /* network being used or tried */
    char ip[16];
    net_mqtt_state_t mqtt;
    char broker[NET_HOST_MAX + 1];
    bool scanning;
    uint32_t scan_seq; /* bumps when a scan finishes */
    uint32_t ap_count;
    net_ap_t aps[NET_MAX_APS]; /* strongest first, duplicates removed */
    uint32_t stop_seq; /* bumps on every stop message received */
    net_ring_state_t ring;
    bool time_synced; /* system UTC time set from NTP; read it with tal_time_get_posix() */
    /* UI settings sent by the indoor unit: bumps remote_seq, -1 = not in that message */
    uint32_t remote_seq;
    int32_t remote_theme, remote_bell, remote_ring, remote_style;
} net_status_t;

/* Call once after tal_kv_init(); connects with the saved Wi-Fi if any. */
void net_start(void);
void net_get_status(net_status_t *out);

void net_scan(void);
/* Credentials are saved only after the connection succeeds. */
void net_connect(const char *ssid, const char *pswd);
/* Saved immediately; the MQTT session reconnects to the new host. */
void net_set_broker(const char *host);

/*
 * Ring events for the indoor unit. A start is sent with a per-press event_id
 * and resent (same event_id) every DOORBELL_ACK_WAIT_MS until the indoor
 * unit acknowledges it, at most DOORBELL_START_RESENDS times. A start made
 * while MQTT is down is sent once it comes up, unless it is more than a few
 * seconds old by then. A stop cancels any resends still pending.
 */
void net_publish_start(uint32_t seconds);
void net_publish_stop(void);

/* Current UI settings, published (retained) for the indoor unit's settings page.
 * Call at start-up and after every change. */
void net_report_settings(uint32_t theme, uint32_t bell_color, uint32_t ring_seconds, uint32_t bell_style);
