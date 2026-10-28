/*
 * The doorbell's microphone to the indoor unit, one way: for the recording of
 * a ring and for listening while the camera view is open there.
 *
 * The microphone always fills a few seconds of history (doorbell_sound.c), so
 * a press can send the moments before it too: the indoor unit's video clips
 * start 3 s before the press as well. Audio goes as UDP packets to
 * DOORBELL_LISTEN_PORT, each one LISTEN_HEADER bytes then 20 ms of 16 kHz mono
 * 16-bit PCM:
 *     "DBA1"   magic
 *     uint32   session (new on every start), little-endian
 *     uint32   number of the first sample since the microphone started, little-endian
 * The sample number lets the indoor unit place every packet exactly in time,
 * even ones that come late, twice or never (see Indoor/door_audio.py).
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define DOORBELL_LISTEN_PORT 5006
#define LISTEN_HEADER        12
#define LISTEN_PRE_MS        3000  /* sent from before the start when asked to (a press) */
#define LISTEN_PRESS_S       20    /* a press streams this long; the indoor unit extends it while it needs more */
#define LISTEN_MAX_S         120   /* longest a single request may ask for */

/* Call once after sound_init(). */
void listen_init(void);
/* Streams to `host` (IPv4) for `seconds` from now; `pre` also sends the last LISTEN_PRE_MS first.
 * While running, a new start for the same host only extends the time (and never resends history). */
void listen_start(const char *host, uint16_t port, uint32_t seconds, bool pre);
void listen_stop(void);
bool listen_active(void);
