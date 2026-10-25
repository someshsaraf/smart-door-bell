/*
 * Outdoor doorbell sound. See doorbell_sound.h.
 *
 * The chosen chime is synthesised into PSRAM as 16-bit mono PCM at the
 * speaker's sample rate (16 kHz on this board): struck-bell notes made of a
 * few decaying partials, the same recipes as the indoor unit's chime tones.
 * Each partial is a two-multiply recursive oscillator, so switching chimes
 * takes a few milliseconds. A thread feeds the PCM to the speaker one driver
 * frame at a time; the driver paces playback and switches the amplifier.
 */
#include "tuya_cloud_types.h"
#include "tal_api.h"
#include "tkl_memory.h"
#include "tdl_audio_manage.h"
#include "doorbell_sound.h"
#include <math.h>
#include <string.h>

#define SAMPLE_RATE 16000

const char *const chime_names[CHIME_COUNT] = {"Ding Dong", "Westminster", "Triple Chime", "Marimba", "Church Bell"};

/* ---------- chime recipes ---------- */

typedef struct {
    float ratio, level, decay; /* to the fundamental; decay time constant in s */
} partial_t;

typedef struct {
    float start, freq, level;
} note_t;

static const partial_t TUBULAR[] = {{1.0f, 1.0f, 1.4f}, {2.76f, 0.45f, 0.7f}, {5.40f, 0.22f, 0.38f}, {8.93f, 0.10f, 0.2f}};
static const partial_t MARIMBA[] = {{1.0f, 1.0f, 0.45f}, {3.93f, 0.35f, 0.12f}, {9.2f, 0.08f, 0.05f}};
static const partial_t CHURCH[] = {{0.5f, 0.55f, 2.6f}, {1.0f, 1.0f, 2.0f}, {1.19f, 0.5f, 1.6f},
                                   {1.5f, 0.35f, 1.2f}, {2.0f, 0.4f, 1.0f}, {2.74f, 0.2f, 0.6f}};
/* brass temple bell: inharmonic partials, and a slightly detuned twin of the fundamental that makes it shimmer */
static const partial_t GHANTI[] = {{1.0f, 1.0f, 1.8f}, {1.006f, 0.5f, 1.8f}, {2.32f, 0.6f, 1.0f},
                                   {4.25f, 0.35f, 0.6f}, {6.63f, 0.2f, 0.35f}};
static const partial_t GLOCK[] = {{1.0f, 1.0f, 0.6f}, {2.76f, 0.3f, 0.25f}, {5.4f, 0.12f, 0.12f}};

#define G4 392.00f
#define C5 523.25f
#define D5 587.33f
#define E5 659.26f
#define G5 783.99f
#define C6 1046.50f
#define E6 1318.51f
#define G6 1567.98f
#define A5 880.00f

static const note_t N_DING_DONG[] = {{0.0f, E5, 1}, {0.55f, C5, 1}};
static const note_t N_WESTMINSTER[] = {{0.0f, E5, 1}, {0.5f, C5, 1}, {1.0f, D5, 1}, {1.5f, G4, 1},
                                       {2.3f, G4, 1}, {2.8f, D5, 1}, {3.3f, E5, 1}, {3.8f, C5, 1}};
static const note_t N_TRIPLE[] = {{0.0f, C6, 0.9f}, {0.22f, E6, 0.9f}, {0.44f, G6, 1}};
static const note_t N_MARIMBA[] = {{0.0f, G5, 1}, {0.18f, E5, 0.9f}, {0.36f, C5, 0.9f}, {0.72f, G5, 0.7f}};
/* an octave above the indoor church bell: a small speaker cannot reproduce C4's low hum */
static const note_t N_CHURCH[] = {{0.0f, C5, 1}, {1.6f, C5, 0.9f}};
/* festivals: temple bell strikes (Diwali), the openings of Jingle Bells and Auld Lang Syne */
static const note_t N_GHANTI[] = {{0.0f, A5, 1}, {0.35f, A5, 0.75f}, {0.7f, A5, 0.9f}, {1.4f, A5, 1}};
static const note_t N_JINGLE[] = {{0.0f, E5, 1},     {0.28f, E5, 1},    {0.56f, E5, 1},    {1.12f, E5, 1},
                                  {1.40f, E5, 1},    {1.68f, E5, 1},    {2.24f, E5, 1},    {2.52f, G5, 1},
                                  {2.80f, C5, 1},    {3.22f, D5, 0.9f}, {3.36f, E5, 1}};
static const note_t N_AULD[] = {{0.0f, G4, 0.8f}, {0.4f, C5, 1},    {1.0f, C5, 0.8f}, {1.2f, C5, 0.9f},
                                {1.6f, E5, 1},    {2.0f, D5, 1},    {2.6f, C5, 0.8f}, {2.8f, D5, 0.9f},
                                {3.2f, E5, 1},    {3.6f, C5, 1},    {4.2f, C5, 0.8f}, {4.4f, E5, 0.9f},
                                {4.8f, G5, 1},    {5.2f, A5, 1}};

#define LEN(a) (sizeof(a) / sizeof((a)[0]))
static const struct {
    const note_t *notes;
    uint32_t note_count;
    const partial_t *partials;
    uint32_t partial_count;
    float seconds; /* includes the quiet tail before a repeat */
} chimes[CHIME_ALL] = {
    {N_DING_DONG, LEN(N_DING_DONG), TUBULAR, LEN(TUBULAR), 2.6f},
    {N_WESTMINSTER, LEN(N_WESTMINSTER), TUBULAR, LEN(TUBULAR), 5.6f},
    {N_TRIPLE, LEN(N_TRIPLE), TUBULAR, LEN(TUBULAR), 2.4f},
    {N_MARIMBA, LEN(N_MARIMBA), MARIMBA, LEN(MARIMBA), 2.0f},
    {N_CHURCH, LEN(N_CHURCH), CHURCH, LEN(CHURCH), 4.4f},
    {N_GHANTI, LEN(N_GHANTI), GHANTI, LEN(GHANTI), 4.0f},
    {N_JINGLE, LEN(N_JINGLE), GLOCK, LEN(GLOCK), 4.8f},
    {N_AULD, LEN(N_AULD), TUBULAR, LEN(TUBULAR), 7.2f},
};

/* ---------- state ---------- */

static TDL_AUDIO_HANDLE_T audio;
static TDL_AUDIO_INFO_T info;
static int16_t *pcm;       /* the current chime */
static float *mix;         /* synthesis scratch, sized for the longest chime */
static uint32_t pcm_bytes;
static SEM_HANDLE start_sem;
static THREAD_HANDLE thread;
static volatile bool playing, repeat, stop_req;

/* Intercom rings: one writer and one reader each, so free-running indices are enough. */
#define RING_BYTES  32768                   /* ~1 s of audio, a power of two */
#define CALL_PREFILL (SAMPLE_RATE * 2 / 12) /* ~80 ms buffered before the speaker starts */
#define CALL_MAX_LAG (SAMPLE_RATE * 2 / 3)  /* beyond ~330 ms queued, skip ahead */
typedef struct {
    uint8_t *buf;
    volatile uint32_t head, tail; /* bytes written / read so far */
} ring_t;
static ring_t rx, mic;
static uint8_t *call_frame; /* one driver frame of far-end audio */
static volatile bool in_call;

static void ring_put(ring_t *r, const uint8_t *data, uint32_t len)
{
    if (RING_BYTES - (r->head - r->tail) < len)
        return; /* full: the reader fell behind; drop rather than overwrite what it reads */
    for (uint32_t i = 0; i < len; i++)
        r->buf[(r->head + i) & (RING_BYTES - 1)] = data[i];
    r->head += len;
}

static void ring_get(ring_t *r, uint8_t *out, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++)
        out[i] = r->buf[(r->tail + i) & (RING_BYTES - 1)];
    r->tail += len;
}

static void mic_cb(TDL_AUDIO_FRAME_FORMAT_E type, TDL_AUDIO_STATUS_E status, uint8_t *data, uint32_t len)
{
    (void)status;
    if (in_call && type == TDL_AUDIO_FRAME_FORMAT_PCM)
        ring_put(&mic, data, len);
}

/* Plays far-end audio while the call lasts, smoothing over network jitter. */
static void call_loop(void)
{
    bool started = false;
    while (in_call) {
        uint32_t queued = rx.head - rx.tail;
        if (queued > CALL_MAX_LAG)
            rx.tail = rx.head - (CALL_PREFILL & ~1u); /* a burst after a stall: catch up */
        if (queued < (started ? info.frame_size : CALL_PREFILL)) {
            started = false; /* ran dry: wait for a little buffer again */
            tal_system_sleep(5);
            continue;
        }
        started = true;
        ring_get(&rx, call_frame, info.frame_size);
        tdl_audio_play(audio, call_frame, info.frame_size);
    }
}

static void synth(uint32_t c)
{
    uint32_t n = (uint32_t)(chimes[c].seconds * SAMPLE_RATE);
    memset(mix, 0, n * sizeof(float));
    for (uint32_t k = 0; k < chimes[c].note_count; k++) {
        const note_t *note = &chimes[c].notes[k];
        uint32_t s0 = (uint32_t)(note->start * SAMPLE_RATE);
        for (uint32_t p = 0; p < chimes[c].partial_count; p++) {
            const partial_t *pt = &chimes[c].partials[p];
            float w = 2.0f * 3.14159265f * note->freq * pt->ratio / SAMPLE_RATE;
            if (w >= 3.1f)
                continue; /* above the speaker's Nyquist frequency */
            /* sin(i*w) by recurrence: s[i] = 2cos(w) s[i-1] - s[i-2] */
            float k2 = 2.0f * cosf(w), s1 = 0.0f, s2 = -sinf(w);
            float fall = expf(-1.0f / (pt->decay * SAMPLE_RATE)), env = pt->level * note->level;
            uint32_t end = s0 + (uint32_t)(pt->decay * 7.0f * SAMPLE_RATE); /* down to ~0.1 % */
            for (uint32_t i = s0; i < n && i < end; i++, env *= fall) {
                float s = k2 * s1 - s2;
                s2 = s1;
                s1 = s;
                float attack = i - s0 < 64 ? (i - s0) / 64.0f : 1.0f; /* 4 ms: no click */
                mix[i] += env * attack * s2;
            }
        }
    }
    float peak = 1e-6f;
    for (uint32_t i = 0; i < n; i++)
        peak = fmaxf(peak, fabsf(mix[i]));
    uint32_t fade = SAMPLE_RATE / 50; /* 20 ms fade-out: no click at the loop point */
    for (uint32_t i = 0; i < n; i++)
        pcm[i] = (int16_t)(mix[i] / peak * 0.85f * 32767.0f * (n - i < fade ? (n - i) / (float)fade : 1.0f));
    pcm_bytes = n * sizeof(int16_t);
}

static void sound_thread(void *arg)
{
    (void)arg;
    for (;;) {
        tal_semaphore_wait_forever(start_sem);
        if (in_call) {
            call_loop();
            playing = false;
            continue;
        }
        do {
            for (uint32_t off = 0; off < pcm_bytes && !stop_req; off += info.frame_size) {
                uint32_t len = pcm_bytes - off < info.frame_size ? pcm_bytes - off : info.frame_size;
                tdl_audio_play(audio, (uint8_t *)pcm + off, len);
            }
        } while (repeat && !stop_req);
        playing = false;
    }
}

void sound_init(uint32_t chime, uint8_t volume)
{
    if (tdl_audio_find(AUDIO_CODEC_NAME, &audio) != OPRT_OK || tdl_audio_open(audio, mic_cb) != OPRT_OK ||
        tdl_audio_get_info(audio, &info) != OPRT_OK || info.frame_size == 0) {
        PR_ERR("[SOUND] speaker not available");
        audio = NULL;
        return;
    }
    float longest = 0.0f;
    for (uint32_t c = 0; c < CHIME_ALL; c++)
        longest = fmaxf(longest, chimes[c].seconds);
    uint32_t n = (uint32_t)(longest * SAMPLE_RATE);
    mix = tkl_system_psram_malloc(n * sizeof(float));
    pcm = tkl_system_psram_malloc(n * sizeof(int16_t));
    rx.buf = tkl_system_psram_malloc(RING_BYTES);
    mic.buf = tkl_system_psram_malloc(RING_BYTES);
    call_frame = tkl_system_psram_malloc(info.frame_size);
    if (!mix || !pcm || !rx.buf || !mic.buf || !call_frame) {
        PR_ERR("[SOUND] no memory for chimes");
        audio = NULL;
        return;
    }
    sound_set_volume(volume);
    synth(chime < CHIME_ALL ? chime : CHIME_DING_DONG);
    tal_semaphore_create_init(&start_sem, 0, 1);
    THREAD_CFG_T cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.stackDepth = 4 * 1024;
    cfg.priority = THREAD_PRIO_2;
    cfg.thrdname = "doorbell_snd";
    tal_thread_create_and_start(&thread, NULL, NULL, sound_thread, NULL, &cfg);
    PR_NOTICE("[SOUND] speaker ready, frame %u bytes", (unsigned)info.frame_size);
}

void sound_stop(void)
{
    if (!audio || !playing || in_call)
        return;
    stop_req = true;
    tdl_audio_play_stop(audio); /* drop what the driver has queued */
    for (int i = 0; i < 20 && playing; i++)
        tal_system_sleep(10); /* the thread notices within one frame */
}

void sound_set_chime(uint32_t chime)
{
    if (!audio || chime >= CHIME_ALL)
        return;
    sound_stop(); /* never rewrite the buffer under the player */
    synth(chime);
}

void sound_play(bool rep)
{
    if (!audio || playing || in_call)
        return;
    repeat = rep;
    stop_req = false; /* here, not in the thread: a stop right after this must not be lost */
    playing = true;
    tal_semaphore_post(start_sem);
}

void sound_set_volume(uint8_t volume)
{
    if (audio)
        tdl_audio_volume_set(audio, volume > 100 ? 100 : volume);
}

void sound_call_begin(void)
{
    if (!audio || in_call)
        return;
    sound_stop(); /* a chime gives way to the call */
    rx.head = rx.tail = 0;
    mic.head = mic.tail = 0;
    in_call = true;
    playing = true;
    tal_semaphore_post(start_sem);
}

void sound_call_end(void)
{
    if (!in_call)
        return;
    in_call = false;
    tdl_audio_play_stop(audio);
    for (int i = 0; i < 20 && playing; i++)
        tal_system_sleep(10);
}

bool sound_in_call(void)
{
    return in_call;
}

void sound_call_feed(const uint8_t *data, uint32_t len)
{
    if (in_call)
        ring_put(&rx, data, len);
}

uint32_t sound_call_mic(uint8_t *out, uint32_t len)
{
    if (!in_call || mic.head - mic.tail < len)
        return 0;
    ring_get(&mic, out, len);
    return len;
}
