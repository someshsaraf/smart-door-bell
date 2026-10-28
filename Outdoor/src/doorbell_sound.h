/*
 * Outdoor doorbell sound: a chime on the board's speaker so the visitor hears
 * that the bell rang. Plays on its own thread; the calls below never block
 * the UI for longer than it takes to stop a chime in progress.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Chime numbers are stored and sent to the indoor unit: only ever append. */
enum { CHIME_DING_DONG, CHIME_WESTMINSTER, CHIME_TRIPLE, CHIME_MARIMBA, CHIME_CHURCH, CHIME_COUNT };
extern const char *const chime_names[CHIME_COUNT];
/* Festival chimes: played during festival themes only, never offered on the Sound page. */
enum { CHIME_TEMPLE_GHANTI = CHIME_COUNT, CHIME_JINGLE_BELLS, CHIME_AULD_LANG_SYNE, CHIME_ALL };

/* Opens the speaker and prepares `chime`. Call after board_register_hardware(). */
void sound_init(uint32_t chime, uint8_t volume);

/* Switches to another chime (stops one that is playing). */
void sound_set_chime(uint32_t chime);

/* Plays the chime once, or with `repeat` over and over until sound_stop(). */
void sound_play(bool repeat);
void sound_stop(void);

/* Speaker volume 0..100 (0 = silent). */
void sound_set_volume(uint8_t volume);

/*
 * Intercom: 16 kHz mono 16-bit PCM in both directions. During a call the
 * speaker plays what sound_call_feed() delivers (a chime is stopped and none
 * starts), and the microphone, after the board's echo cancellation, collects
 * audio for sound_call_mic(). Feed and mic may be used from one other thread.
 */
void sound_call_begin(void);
void sound_call_end(void);
bool sound_in_call(void);
void sound_call_feed(const uint8_t *pcm, uint32_t len); /* far end, any length */
uint32_t sound_call_mic(uint8_t *out, uint32_t len);    /* near end: `len` bytes or 0 if not yet there */

/*
 * Microphone history: the last SOUND_MIC_HISTORY bytes (16 kHz mono 16-bit PCM),
 * filled all the time, calls or not. Positions count bytes since the microphone
 * started; read from any thread.
 */
#define SOUND_MIC_HISTORY (256 * 1024) /* ~8 s, a power of two */
uint32_t sound_mic_head(void);                               /* bytes recorded so far */
bool sound_mic_read(uint32_t pos, uint8_t *out, uint32_t len); /* false: not there yet or overwritten */
