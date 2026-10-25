/*
 * Outdoor doorbell sound. See doorbell_sound.h.
 *
 * The chime is synthesised once at start-up into PSRAM as 16-bit mono PCM at
 * the speaker's sample rate (16 kHz on this board): two struck-bell notes,
 * E5 then C5, with the same partials as the indoor unit's "Ding Dong" tone.
 * A thread feeds it to the speaker one driver frame at a time; the driver
 * paces playback, and the board driver switches the amplifier on and off.
 */
#include "tuya_cloud_types.h"
#include "tal_api.h"
#include "tkl_memory.h"
#include "tdl_audio_manage.h"
#include "doorbell_sound.h"
#include <math.h>
#include <string.h>

#define SAMPLE_RATE    16000
#define CHIME_SECONDS  2.2f
#define DEFAULT_VOLUME 80

static TDL_AUDIO_HANDLE_T audio;
static TDL_AUDIO_INFO_T info;
static int16_t *chime;
static uint32_t chime_bytes;
static SEM_HANDLE start_sem;
static THREAD_HANDLE thread;
static volatile bool playing;

/* (ratio to the fundamental, level, decay time constant in s): a tubular chime */
static const float partials[][3] = {{1.0f, 1.0f, 1.4f}, {2.76f, 0.45f, 0.7f}, {5.40f, 0.22f, 0.38f}, {8.93f, 0.10f, 0.2f}};

static void synth_chime(void)
{
    const struct {
        float start, freq;
    } notes[] = {{0.0f, 659.26f}, {0.55f, 523.25f}}; /* E5, C5 */
    uint32_t n = (uint32_t)(CHIME_SECONDS * SAMPLE_RATE);
    float *mix = tkl_system_psram_malloc(n * sizeof(float));
    chime = tkl_system_psram_malloc(n * sizeof(int16_t));
    if (!mix || !chime) {
        PR_ERR("[SOUND] no memory for the chime");
        return;
    }
    memset(mix, 0, n * sizeof(float));
    for (uint32_t k = 0; k < sizeof(notes) / sizeof(notes[0]); k++) {
        uint32_t s0 = (uint32_t)(notes[k].start * SAMPLE_RATE);
        for (uint32_t p = 0; p < sizeof(partials) / sizeof(partials[0]); p++) {
            float w = 2.0f * 3.14159265f * notes[k].freq * partials[p][0] / SAMPLE_RATE;
            float fall = expf(-1.0f / (partials[p][2] * SAMPLE_RATE)), env = partials[p][1];
            for (uint32_t i = 0; s0 + i < n; i++, env *= fall) {
                float attack = i < 64 ? i / 64.0f : 1.0f; /* 4 ms: no click */
                mix[s0 + i] += env * attack * sinf(w * i);
            }
        }
    }
    float peak = 1e-6f;
    for (uint32_t i = 0; i < n; i++)
        peak = fmaxf(peak, fabsf(mix[i]));
    for (uint32_t i = 0; i < n; i++)
        chime[i] = (int16_t)(mix[i] / peak * 0.85f * 32767.0f);
    tkl_system_psram_free(mix);
    chime_bytes = n * sizeof(int16_t);
}

static void sound_thread(void *arg)
{
    (void)arg;
    for (;;) {
        tal_semaphore_wait_forever(start_sem);
        playing = true;
        for (uint32_t off = 0; off < chime_bytes; off += info.frame_size) {
            uint32_t len = chime_bytes - off < info.frame_size ? chime_bytes - off : info.frame_size;
            tdl_audio_play(audio, (uint8_t *)chime + off, len);
        }
        playing = false;
    }
}

void sound_init(void)
{
    if (tdl_audio_find(AUDIO_CODEC_NAME, &audio) != OPRT_OK || tdl_audio_open(audio, NULL) != OPRT_OK ||
        tdl_audio_get_info(audio, &info) != OPRT_OK || info.frame_size == 0) {
        PR_ERR("[SOUND] speaker not available");
        audio = NULL;
        return;
    }
    tdl_audio_volume_set(audio, DEFAULT_VOLUME);
    synth_chime();
    if (!chime)
        return;
    tal_semaphore_create_init(&start_sem, 0, 1);
    THREAD_CFG_T cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.stackDepth = 4 * 1024;
    cfg.priority = THREAD_PRIO_2;
    cfg.thrdname = "doorbell_snd";
    tal_thread_create_and_start(&thread, NULL, NULL, sound_thread, NULL, &cfg);
    PR_NOTICE("[SOUND] speaker ready, frame %u bytes", (unsigned)info.frame_size);
}

void sound_chime(void)
{
    if (audio && chime && !playing)
        tal_semaphore_post(start_sem);
}

void sound_set_volume(uint8_t volume)
{
    if (audio)
        tdl_audio_volume_set(audio, volume > 100 ? 100 : volume);
}
