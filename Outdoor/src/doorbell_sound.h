/*
 * Outdoor doorbell sound: a "ding-dong" chime on the board's speaker so the
 * visitor hears that the bell rang. Plays on its own thread; the calls below
 * never block the UI.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Opens the speaker and prepares the chime. Call after board_register_hardware(). */
void sound_init(void);

/* Plays the chime once. Ignored while it is already playing. */
void sound_chime(void);

/* Speaker volume 0..100 (0 = silent). */
void sound_set_volume(uint8_t volume);
