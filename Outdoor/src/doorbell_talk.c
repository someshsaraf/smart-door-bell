/*
 * Intercom with the indoor unit. See doorbell_talk.h.
 *
 * One thread owns the UDP socket: it waits up to 10 ms for far-end audio,
 * hands it to the speaker, and sends whatever the microphone has collected
 * in 20 ms packets. The far end's address is taken from the start command
 * and then from the packets that actually arrive, so a reply always goes
 * back the way the audio came.
 */
#include "tuya_cloud_types.h"
#include "tal_api.h"
#include "tal_network.h"
#include "doorbell_sound.h"
#include "doorbell_talk.h"
#include <string.h>

#define PACKET_BYTES 640 /* 20 ms at 16 kHz, 16-bit mono */

static THREAD_HANDLE thread;
static SEM_HANDLE wake;
static volatile bool want;           /* a call should be running */
static volatile uint32_t generation; /* bumps on every start, so a new call restarts the loop */
static TUYA_IP_ADDR_T peer;
static uint16_t peer_port;

static void talk_call(void)
{
    uint32_t gen = generation;
    int fd = tal_net_socket_create(PROTOCOL_UDP);
    if (fd < 0) {
        PR_ERR("[TALK] no socket");
        want = false;
        return;
    }
    tal_net_set_reuse(fd);
    if (tal_net_bind(fd, TY_IPADDR_ANY, DOORBELL_TALK_PORT) < 0) {
        PR_ERR("[TALK] port %d busy", DOORBELL_TALK_PORT);
        tal_net_close(fd);
        want = false;
        return;
    }
    sound_call_begin();
    PR_NOTICE("[TALK] call started");

    static uint8_t buf[1500];
    uint32_t start = tal_system_get_millisecond(), heard = start;
    while (want && gen == generation) {
        uint32_t now = tal_system_get_millisecond();
        if (now - heard > TALK_IDLE_END_MS || now - start > TALK_MAX_MS) {
            PR_NOTICE("[TALK] %s: hanging up", now - start > TALK_MAX_MS ? "longest call reached" : "indoor unit silent");
            break;
        }
        TUYA_FD_SET_T rd;
        tal_net_fd_zero(&rd);
        tal_net_fd_set(fd, &rd);
        if (tal_net_select(fd + 1, &rd, NULL, NULL, 10) > 0) {
            TUYA_IP_ADDR_T from;
            uint16_t port;
            int n = tal_net_recvfrom(fd, buf, sizeof(buf), &from, &port);
            if (n > 0 && from == peer) {
                peer_port = port; /* answer the port the audio comes from */
                heard = now;
                sound_call_feed(buf, (uint32_t)n & ~1u);
            }
        }
        while (sound_call_mic(buf, PACKET_BYTES))
            tal_net_send_to(fd, buf, PACKET_BYTES, peer, peer_port);
    }
    sound_call_end();
    tal_net_close(fd);
    if (gen == generation)
        want = false;
    PR_NOTICE("[TALK] call ended");
}

static void talk_thread(void *arg)
{
    (void)arg;
    for (;;) {
        tal_semaphore_wait_forever(wake);
        while (want)
            talk_call(); /* again at once when a new start replaced the call */
    }
}

void talk_init(void)
{
    tal_semaphore_create_init(&wake, 0, 1);
    THREAD_CFG_T cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.stackDepth = 4 * 1024;
    cfg.priority = THREAD_PRIO_2;
    cfg.thrdname = "doorbell_talk";
    tal_thread_create_and_start(&thread, NULL, NULL, talk_thread, NULL, &cfg);
}

void talk_start(const char *host, uint16_t port)
{
    peer = tal_net_str2addr(host);
    peer_port = port ? port : DOORBELL_TALK_PORT;
    generation++;
    want = true;
    tal_semaphore_post(wake);
}

void talk_stop(void)
{
    want = false;
}

bool talk_active(void)
{
    return want;
}
