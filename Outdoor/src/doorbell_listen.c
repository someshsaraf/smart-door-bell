/*
 * The doorbell's microphone to the indoor unit. See doorbell_listen.h.
 *
 * One thread reads the microphone history (doorbell_sound.c) with its own
 * cursor and sends whatever is there in 20 ms packets. History from before
 * the start (a press) goes out at up to 5x real time so it catches up within
 * a second without flooding the Wi-Fi; after that, packets go as the
 * microphone fills them.
 */
#include "tuya_cloud_types.h"
#include "tal_api.h"
#include "tal_network.h"
#include "doorbell_sound.h"
#include "doorbell_listen.h"
#include <string.h>

#define PACKET_PCM   640 /* 20 ms at 16 kHz, 16-bit mono */
#define MS_BYTES     32  /* 16 kHz mono 16-bit: bytes in a millisecond */
#define BURST        5   /* packets per 10 ms tick at most: 5x real time */

static THREAD_HANDLE thread;
static SEM_HANDLE wake;
static volatile bool want;
static volatile uint32_t want_pre_ms;
static volatile uint32_t until_ms;   /* tal_system_get_millisecond() when it ends */
static volatile uint32_t generation; /* bumps on a start that needs a new session */
static TUYA_IP_ADDR_T peer;
static uint16_t peer_port;
static uint32_t session;

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static void stream(void)
{
    uint32_t gen = generation;
    int fd = tal_net_socket_create(PROTOCOL_UDP);
    if (fd < 0) {
        PR_ERR("[LISTEN] no socket");
        want = false;
        return;
    }
    session = tal_system_get_random(0x7FFFFFFF) + 1;
    uint32_t head = sound_mic_head();
    uint32_t pre = want_pre_ms * MS_BYTES;
    uint32_t pos = head > pre ? head - pre : 0;
    pos &= ~1u;
    PR_NOTICE("[LISTEN] streaming to the indoor unit, session %u, from %u ms back", (unsigned)session, (unsigned)want_pre_ms);

    static uint8_t pkt[LISTEN_HEADER + PACKET_PCM];
    memcpy(pkt, "DBA1", 4);
    put32(pkt + 4, session);
    while (want && gen == generation && (int32_t)(until_ms - tal_system_get_millisecond()) > 0) {
        head = sound_mic_head();
        if (head - pos > SOUND_MIC_HISTORY - 8192) /* fell too far behind (network stall): skip ahead */
            pos = (head - 1000 * MS_BYTES) & ~1u;
        for (int n = 0; n < BURST && head - pos >= PACKET_PCM; n++) {
            if (!sound_mic_read(pos, pkt + LISTEN_HEADER, PACKET_PCM)) {
                pos = head & ~1u; /* overwritten meanwhile */
                break;
            }
            put32(pkt + 8, pos / 2);
            tal_net_send_to(fd, pkt, sizeof(pkt), peer, peer_port);
            pos += PACKET_PCM;
        }
        tal_system_sleep(10);
    }
    tal_net_close(fd);
    if (gen == generation)
        want = false;
    PR_NOTICE("[LISTEN] stopped");
}

static void listen_thread(void *arg)
{
    (void)arg;
    for (;;) {
        tal_semaphore_wait_forever(wake);
        while (want)
            stream(); /* again at once when a start for another address replaced it */
    }
}

void listen_init(void)
{
    tal_semaphore_create_init(&wake, 0, 1);
    THREAD_CFG_T cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.stackDepth = 4 * 1024;
    cfg.priority = THREAD_PRIO_2;
    cfg.thrdname = "doorbell_listen";
    tal_thread_create_and_start(&thread, NULL, NULL, listen_thread, NULL, &cfg);
}

void listen_start(const char *host, uint16_t port, uint32_t seconds, uint32_t pre_ms)
{
    TUYA_IP_ADDR_T addr = tal_net_str2addr(host);
    uint16_t p = port ? port : DOORBELL_LISTEN_PORT;
    if (seconds == 0 || seconds > LISTEN_MAX_S)
        seconds = LISTEN_MAX_S;
    until_ms = tal_system_get_millisecond() + seconds * 1000;
    if (want && addr == peer && p == peer_port)
        return; /* already streaming there: just longer */
    peer = addr;
    peer_port = p;
    want_pre_ms = pre_ms > LISTEN_PRE_MAX_MS ? LISTEN_PRE_MAX_MS : pre_ms;
    generation++;
    want = true;
    tal_semaphore_post(wake);
}

void listen_stop(void)
{
    want = false;
}

bool listen_active(void)
{
    return want;
}
