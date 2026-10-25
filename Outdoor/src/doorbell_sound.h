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

/* Opens the speaker and prepares `chime`. Call after board_register_hardware(). */
void sound_init(uint32_t chime, uint8_t volume);

/* Switches to another chime (stops one that is playing). */
void sound_set_chime(uint32_t chime);

/* Plays the chime once, or with `repeat` over and over until sound_stop(). */
void sound_play(bool repeat);
void sound_stop(void);

/* Speaker volume 0..100 (0 = silent). */
void sound_set_volume(uint8_t volume);
