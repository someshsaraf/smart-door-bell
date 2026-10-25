/*
 * Intercom with the indoor unit: raw 16 kHz mono 16-bit PCM over UDP, one
 * 20 ms packet at a time, both ways on DOORBELL_TALK_PORT. Calls are opened
 * and closed by the indoor unit over MQTT (see Indoor/topics.md); the audio
 * itself runs on its own thread so it never waits on MQTT or the UI.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define DOORBELL_TALK_PORT 5004
#define TALK_IDLE_END_MS   10000      /* nothing heard from the indoor unit this long: hang up */
#define TALK_MAX_MS        (5 * 60000) /* longest call */

/* Call once after sound_init(). */
void talk_init(void);
/* Calls `host` (the indoor unit's IPv4 address); replaces a call in progress. */
void talk_start(const char *host, uint16_t port);
void talk_stop(void);
bool talk_active(void);
