/*
 * TuyaOpen doorbell UI for WAVESHARE_T5AI_TOUCH_AMOLED_1_75 (466x466 round AMOLED).
 * Every page is built from native LVGL objects and fonts; the bell artwork is
 * rendered on the device at native resolution (no scaled bitmaps).
 *
 * Home screen touch:
 *  - press and release in under HOLD_MS: ring (bell swings, sound waves pulse)
 *    and tell the indoor unit over MQTT
 *  - hold for HOLD_MS: open settings (a ring around the edge shows progress)
 *
 * Round-panel layout rules used throughout:
 *  - Content is centred and stacked vertically (LV_ALIGN_TOP_MID + y offset).
 *  - Rows wider than ~260px only sit between y=80 and y=390, where the
 *    circle is wide enough; corners are checked against the 233px radius.
 *  - Settings pages use prev/next arrows at the left/right middle (the widest
 *    part of the circle) and a "Done" pill at the bottom centre.
 *
 * This source uses LVGL 9 APIs (TuyaOpen src/liblvgl/v9, LVGL 9.1).
 */
#include "tuya_cloud_types.h"
#include "tal_api.h"
#include "tal_kv.h"
#include "tal_time_service.h"
#include "tkl_output.h"
#include "lvgl.h"
#include "lv_vendor.h"
#include "lv_port_disp.h" /* disp_set_backlight, disp_enable_update / disp_disable_update */
#include "board_com_api.h"
#include "doorbell_net.h"
#include "doorbell_sound.h"
#include "doorbell_talk.h"
#include "doorbell_listen.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>

#ifndef DISPLAY_NAME
#define DISPLAY_NAME "display"
#endif

#define SCREEN_SIZE 466
#define HOLD_MS     5000 /* home screen long press that opens settings */
/* How the picture is turned for the way the doorbell is mounted. LVGL names
 * the turn of the panel: ROTATION_90 shows the picture 90 degrees to the left
 * (counter-clockwise). Touches are turned to match by LVGL. */
#define SCREEN_ROTATION LV_DISPLAY_ROTATION_90
#define DONE_Y      374  /* bottom "Done" pill on settings pages */
#define DOTS_Y      346  /* page indicator on settings pages */
#define KV_UI       "db_ui"

/* Settings pages are consecutive so prev/next is just -1/+1. */
typedef enum { HOME, WIFI, APPEARANCE, BELL, SOUND, FESTIVAL, DURATION, CONTROLLER, WIFI_LIST, ENTRY, PAGE_COUNT } page_t;
#define FIRST_SETTING WIFI
#define LAST_SETTING  CONTROLLER

typedef enum { ENTRY_WIFI_PASSWORD, ENTRY_BROKER } entry_mode_t;

typedef struct {
    const char *name;
    uint32_t bg_top, bg_bottom, text, muted, card, card_border, pressed, accent, on_accent, bell;
    uint8_t glow; /* peak opacity of the background glow: bright on black, a pastel tint on white */
} theme_t;

static const theme_t themes[] = {
    {"Clean & Light", 0xFFFFFF, 0xDCEBFA, 0x173B5C, 0x5B7894, 0xFFFFFF, 0xC9DCEF, 0xE3EEF9, 0x2F80ED, 0xFFFFFF, 0, 70},
    /* Near-black background: AMOLED pixels are off, which also saves power. */
    {"Midnight & Gold", 0x1B2533, 0x000000, 0xF2F5F8, 0x9AA8B8, 0x1C2735, 0x33445A, 0x2A3A4F, 0xD4A537, 0x14100A, 1, 150},
};
#define THEME_COUNT (sizeof(themes) / sizeof(themes[0]))

static const struct {
    const char *name;
    uint32_t color;
} bell_colors[] = {
    {"Blue", 0x2F80ED},
    {"Gold", 0xD4A537},
    {"Silver", 0xA7B1BC},
    {"Red", 0xD64545},
};
#define BELL_COLOR_COUNT (sizeof(bell_colors) / sizeof(bell_colors[0]))

static const uint32_t durations[] = {10, 15, 30, 45, 60};
#define DURATION_COUNT (sizeof(durations) / sizeof(durations[0]))

/* Status dot colours */
#define DOT_OK   0x34C759
#define DOT_BUSY 0xE0A030
#define DOT_BAD  0xE5484D
#define DOT_IDLE 0x8E9AA6

/* Saved in KV storage (see load_config/save_config). */
static uint32_t theme_idx;
static uint32_t bell_idx;
static uint32_t ring_seconds = 30;
/* Bell on the home screen (chosen on the Bell settings page). The numbers are
 * stored and sent to the indoor unit, so only ever append new styles. */
enum { STYLE_CLASSIC, STYLE_BUTTON, STYLE_TEMPLE, STYLE_HAND, STYLE_TWIN, STYLE_FLAT, STYLE_COUNT };
static const char *const style_names[STYLE_COUNT] = {"Classic", "Push button", "Temple", "Hand bell", "Twin bells", "Flat"};
static uint32_t bell_style = STYLE_CLASSIC;
static bool glow_on = true; /* aurora glow behind the bell (Appearance page) */
/* Chime on the doorbell's own speaker (Sound page). */
static uint32_t chime_idx = CHIME_DING_DONG;
static bool chime_repeat;      /* false: once per press; true: for the whole ring */
static const struct {
    const char *name;
    uint8_t volume;
} volumes[] = {{"Quiet", 40}, {"Normal", 70}, {"Loud", 100}};
#define VOLUME_COUNT (sizeof(volumes) / sizeof(volumes[0]))
static uint8_t chime_volume = 70;

/*
 * Festival themes, chosen by the indoor unit's calendar (topic
 * home/doorbell/festival). They only change what is shown and played: the
 * user's own settings above stay as they are, are still edited on the
 * settings pages, and come back when the festival ends.
 */
typedef struct {
    const char *key;      /* as sent by the indoor unit */
    const char *greeting; /* when tried on the Festivals page; the indoor unit sends its own */
    theme_t theme;
    uint32_t bell_color, style, chime;
    uint32_t glow[3];
} festival_t;
static const festival_t festivals[] = {
    {"diwali", "Happy Diwali",
     {"Diwali", 0x4A0E12, 0x000000, 0xFFF1D6, 0xD9A86B, 0x3A1416, 0x6A2A22, 0x52201C, 0xFFB43A, 0x2A1200, 1, 170},
     0xE8B23A, STYLE_TEMPLE, CHIME_TEMPLE_GHANTI, {0xFF8A1E, 0xFFC93C, 0xFF3D7F}},
    {"christmas", "Merry Christmas",
     {"Christmas", 0x0F3B24, 0x000000, 0xF4FBF6, 0xA9C9B4, 0x15402A, 0x2B6A46, 0x1E5236, 0xE23B3B, 0xFFFFFF, 1, 150},
     0xD4A537, STYLE_TWIN, CHIME_JINGLE_BELLS, {0xFF3030, 0x2EE66B, 0xFFD54A}},
    {"new_year", "Happy New Year",
     {"New Year", 0x101B4A, 0x000000, 0xF2F5FF, 0xA3AED6, 0x18245A, 0x2F3F85, 0x223070, 0xFFD54A, 0x1A1400, 1, 160},
     0xD4A537, STYLE_CLASSIC, CHIME_AULD_LANG_SYNE, {0xFFD54A, 0xFF3DCB, 0x2EE6FF}},
};
#define FESTIVAL_COUNT (sizeof(festivals) / sizeof(festivals[0]))
static const festival_t *fest;            /* running now, NULL outside festivals */
static bool fest_tones;                   /* play the festival chime instead of the user's */
static uint32_t loaded_chime = CHIME_ALL; /* the chime the sound module has ready */
/* Festivals page, saved: follow the indoor unit's festivals at all, and play their chimes. */
static bool fest_look_on = true, fest_chime_on = true;

/* Night: the screen is off from night_from to night_to (local hours; set from
 * the indoor unit, saved). A touch lights it for WAKE_MS; that first touch only
 * wakes it, never rings. */
static bool night_on = true;
static uint32_t night_from = 23, night_to = 6;
#define WAKE_MS 30000
#ifndef CONFIG_DISPLAY_DEFAULT_BRIGHTNESS
#define CONFIG_DISPLAY_DEFAULT_BRIGHTNESS 80
#endif
static bool screen_off;
static lv_obj_t *wake_catcher; /* invisible, over everything while the screen is off */
/* Screen turned on or off from the indoor unit: holds until the schedule itself
 * changes (night starts or ends), or a touch / ring wakes a screen turned off. */
enum { SCREEN_AUTO, SCREEN_FORCED_ON, SCREEN_FORCED_OFF };
static int screen_force = SCREEN_AUTO;
static uint32_t screen_forced_at; /* lv_tick_get() of the last "screen_off" */
static const festival_t *fest_trial; /* tried on the Festivals page, until fest_trial_end */
static uint32_t fest_trial_end;
#define FEST_TRIAL_MS 60000

/* What is shown and played: the festival look while one runs, else the user's settings. */
static const theme_t *cur_theme(void)
{
    return fest ? &fest->theme : &themes[theme_idx];
}

static uint32_t cur_bell_color(void)
{
    return fest ? fest->bell_color : bell_colors[bell_idx].color;
}

static uint32_t cur_style(void)
{
    return fest ? fest->style : bell_style;
}

static uint32_t ring_chime(void)
{
    return fest && fest_tones ? fest->chime : chime_idx;
}

static void use_chime(uint32_t c)
{
    if (c != loaded_chime)
        sound_set_chime(c);
    loaded_chime = c;
}

static page_t page = HOME;
static lv_obj_t *pages[PAGE_COUNT];
static lv_timer_t *ring_timer;
static bool is_ringing;
static uint32_t press_start;
static net_status_t ns; /* latest network status, refreshed by net_poll_cb */

/* Shared styles: switching theme only rewrites these and refreshes. */
static lv_style_t st_screen, st_text, st_muted, st_accent_text, st_card, st_card_pressed, st_card_checked;
static lv_style_t st_accent, st_accent_pressed, st_wave, st_halo, st_progress, st_dot, st_swatch_checked;

static lv_obj_t *btn_img;  /* the push-button disc */
static lv_obj_t *bell_img; /* the bell symbol on it (swings) */
static lv_obj_t *halo;     /* pulsing ring around the button while idle */
static lv_obj_t *glow_blobs[3];
static lv_obj_t *glow_card;
static lv_timer_t *glow_timer;
static lv_obj_t *home_clock, *home_date;
static lv_obj_t *hold_arc;
static lv_obj_t *wifi_icon;
static lv_obj_t *wifi_slash;
static lv_obj_t *ring_waves[4];
static lv_obj_t *theme_cards[THEME_COUNT];
static lv_obj_t *swatches[BELL_COLOR_COUNT];
static lv_obj_t *style_cards[STYLE_COUNT];
static lv_obj_t *style_thumbs[STYLE_COUNT];
static lv_obj_t *chime_cards[CHIME_COUNT];
static lv_obj_t *repeat_cards[2];
static lv_obj_t *fest_look_cards[2], *fest_chime_cards[2], *fest_now;
static lv_obj_t *volume_cards[VOLUME_COUNT];
static lv_obj_t *duration_btns[DURATION_COUNT];

/* Wi-Fi and Indoor Unit pages share one layout. */
typedef struct {
    lv_obj_t *sub, *dot, *state;
} status_view_t;
static status_view_t wifi_view, ctrl_view;

static lv_obj_t *ap_list, *ap_msg;
static net_ap_t shown_aps[NET_MAX_APS];

static lv_obj_t *entry_title, *entry_sub, *entry_ta, *entry_eye, *entry_kb;
static entry_mode_t entry_mode;
static char entry_ssid[NET_SSID_MAX + 1];

/* ---------- persistent settings ---------- */

/* Keeps the indoor unit's settings page in step. */
static void report_settings(void)
{
    net_settings_t s = {.theme = theme_idx,
                        .bell_color = bell_idx,
                        .ring_seconds = ring_seconds,
                        .bell_style = bell_style,
                        .chime = chime_idx,
                        .volume = chime_volume,
                        .glow = glow_on,
                        .chime_repeat = chime_repeat,
                        .night_on = night_on,
                        .night_from = night_from,
                        .night_to = night_to,
                        .screen_lit = !screen_off};
    net_report_settings(&s);
}

static void save_config(void)
{
    uint8_t v[13] = {(uint8_t)theme_idx,    (uint8_t)bell_idx,      (uint8_t)ring_seconds, (uint8_t)bell_style,
                     (uint8_t)glow_on,      (uint8_t)chime_idx,     (uint8_t)chime_repeat, chime_volume,
                     (uint8_t)fest_look_on, (uint8_t)fest_chime_on, (uint8_t)night_on,     (uint8_t)night_from,
                     (uint8_t)night_to};
    if (tal_kv_set(KV_UI, v, sizeof(v)) != OPRT_OK)
        PR_ERR("[DOORBELL] saving settings failed");
    report_settings();
}

static void load_config(void)
{
    uint8_t *v = NULL;
    size_t len = 0;
    if (tal_kv_get(KV_UI, &v, &len) != OPRT_OK || !v)
        return;
    if (len >= 3 && v[0] < THEME_COUNT && v[1] < BELL_COLOR_COUNT) { /* older firmware saved fewer bytes */
        if (len >= 4 && v[3] < STYLE_COUNT)
            bell_style = v[3];
        if (len >= 5)
            glow_on = v[4] != 0;
        if (len >= 8 && v[5] < CHIME_COUNT && v[7] <= 100) {
            chime_idx = v[5];
            chime_repeat = v[6] != 0;
            chime_volume = v[7];
        }
        if (len >= 10) {
            fest_look_on = v[8] != 0;
            fest_chime_on = v[9] != 0;
        }
        if (len >= 13 && v[11] < 24 && v[12] < 24) {
            night_on = v[10] != 0;
            night_from = v[11];
            night_to = v[12];
        }
        theme_idx = v[0];
        bell_idx = v[1];
        for (uint32_t i = 0; i < DURATION_COUNT; i++)
            if (durations[i] == v[2])
                ring_seconds = v[2];
    }
    tal_kv_free(v);
}

/* ---------- bell artwork ----------
 * Every style is drawn per pixel into ARGB8888 buffers with anti-aliased
 * edges, again whenever the bell colour or style changes:
 *  - Classic, Temple, Hand bell, Twin bells: 3D bells built from simple
 *    shapes (domes, flared bodies, rims, knobs, a wooden handle, a ribbon),
 *    each lit as a surface with a soft specular highlight. Flat: the classic
 *    outline as a modern flat icon.
 *  - Push button: a disc in the bell colour, lit from above, with a raised
 *    rim, a glossy highlight and a drop shadow, so visitors see at once where
 *    to press; on it a white bell symbol (drawn once) that swings when ringing.
 */
#define CLASSIC_W   216
#define CLASSIC_H   236
#define CLASSIC_Y   82     /* top of the classic bell on the screen */
#define CLASSIC_CY  192    /* centre of its dome: the sound waves are centred here */
#define CLASSIC_SS  3      /* supersampling per axis */
#define BTN_SIZE    236    /* button image: disc plus room for its shadow */
#define BTN_R       100.0f /* disc radius */
#define BTN_CY      200    /* button centre on the screen */
#define GLYPH_W     128
#define GLYPH_H     140
#define GLYPH_SCALE 0.54f  /* bell symbol size relative to the bell geometry below */
#define GLYPH_PIVOT 14     /* knob centre in symbol pixels: it swings around it */
#define GLYPH_SS    3      /* supersampling per axis for the symbol */

/* Bell geometry, in units of a 216 x 236 bell. */
#define BELL_CX    108.0f
#define BELL_PIVOT 22.0f

#define THUMB       64     /* style picker thumbnails */

/* classic_* holds the full-size art of every style except the push button */
static lv_image_dsc_t classic_dsc, btn_dsc, glyph_dsc, thumb_dsc[STYLE_COUNT];
static uint8_t *classic_buf, *btn_buf, *glyph_buf, *thumb_buf[STYLE_COUNT];

/* Returns the topmost bell part covering (x, y) and its surface normal, or 0 if none. */
static int bell_hit(float x, float y, float n[3])
{
    float dx = x - BELL_CX;

    /* rim: horizontal capsule */
    if (y >= 180.0f && y <= 204.0f) {
        float ex = fabsf(dx) - 92.0f, ey = y - 192.0f;
        if (ex <= 0.0f || ex * ex + ey * ey <= 144.0f) {
            n[0] = dx / 104.0f;
            n[1] = ey / 12.0f;
            n[2] = 1.0f;
            return 1;
        }
    }
    /* dome: half ellipse on top of the body */
    if (y >= 34.0f && y < 84.0f) {
        float u = dx / 62.0f, v = (y - 84.0f) / 50.0f;
        if (u * u + v * v <= 1.0f) {
            n[0] = u;
            n[1] = v;
            n[2] = sqrtf(fmaxf(0.0f, 1.0f - u * u - v * v));
            return 2;
        }
    }
    /* body: slight waist, then a flare towards the rim; normal = (cos, -dr/dy, sin) */
    if (y >= 84.0f && y <= 186.0f) {
        float s = (y - 84.0f) / 102.0f;
        float w = 62.0f - 24.0f * s * s + 60.0f * s * s * s;
        if (fabsf(dx) <= w) {
            float u = dx / w;
            n[0] = u;
            n[1] = -(-48.0f * s + 180.0f * s * s) / 102.0f;
            n[2] = sqrtf(fmaxf(0.0f, 1.0f - u * u));
            return 2;
        }
    }
    /* clapper: sphere peeking out below the rim */
    {
        float u = dx / 16.0f, v = (y - 214.0f) / 16.0f;
        if (u * u + v * v <= 1.0f) {
            n[0] = u;
            n[1] = v;
            n[2] = sqrtf(1.0f - u * u - v * v);
            return 3;
        }
    }
    /* knob: ring (torus seen from the front) */
    {
        float dy = y - BELL_PIVOT, d = sqrtf(dx * dx + dy * dy);
        float t = (d - 12.0f) / 5.0f;
        if (t >= -1.0f && t <= 1.0f && d > 0.0f) {
            n[0] = dx / d * t;
            n[1] = dy / d * t;
            n[2] = sqrtf(1.0f - t * t);
            return 4;
        }
    }
    return 0;
}

/* ---- more bell shapes, same 216 x 236 box ----
 * Each returns a material (0 = outside) and a surface normal:
 *   1 bright metal (rims, bands, knobs)  2 metal  3 shadowed metal (clapper)
 *   4 knob ring  5 wood  6 ribbon  7/8/9 flat body/clapper/rim (unlit)
 */
enum { MAT_WOOD = 5, MAT_RIBBON = 6, MAT_FLAT = 7 };

static int set_n(float n[3], float x, float y, float z, int part)
{
    n[0] = x;
    n[1] = y;
    n[2] = z;
    return part;
}

/* vertical cylinder of half-width w; `slope` tilts the normal for flared bodies */
static int cyl(float dx, float w, float slope, float n[3], int part)
{
    float u = dx / w;
    return set_n(n, u, -slope, sqrtf(fmaxf(0.0f, 1.0f - u * u)), part);
}

static bool sphere(float dx, float dy, float r, float n[3])
{
    float u = dx / r, v = dy / r, d = u * u + v * v;
    if (d > 1.0f)
        return false;
    set_n(n, u, v, sqrtf(1.0f - d), 0);
    return true;
}

/* horizontal capsule: half-width hw, end radius r */
static bool capsule(float dx, float dy, float hw, float r, float n[3])
{
    float ex = fabsf(dx) - (hw - r);
    if ((ex <= 0.0f && fabsf(dy) <= r) || (ex > 0.0f && ex * ex + dy * dy <= r * r)) {
        set_n(n, dx / hw, dy / r, 1.0f, 0);
        return true;
    }
    return false;
}

/* top half of an ellipse (domes, rounded handle tops) */
static bool dome(float dx, float dy, float a, float b, float n[3])
{
    float u = dx / a, v = dy / b;
    if (dy > 0.0f || u * u + v * v > 1.0f)
        return false;
    set_n(n, u, v, sqrtf(fmaxf(0.0f, 1.0f - u * u - v * v)), 0);
    return true;
}

/* Temple bell (ghanta): finial, shaft, collar, slim flared body with bands. */
static int temple_hit(float x, float y, float n[3])
{
    float dx = x - BELL_CX;
    if (sphere(dx, y - 16.0f, 13.0f, n))
        return 1;
    if (y >= 26.0f && y <= 74.0f && fabsf(dx) <= 6.0f)
        return cyl(dx, 6.0f, 0.0f, n, 2);
    if (capsule(dx, y - 78.0f, 20.0f, 6.0f, n))
        return 1;
    if (capsule(dx, y - 198.0f, 98.0f, 8.0f, n))
        return 1;
    if (y >= 84.0f && dome(dx, y - 100.0f, 30.0f, 16.0f, n))
        return 2;
    if (y >= 100.0f && y <= 192.0f) {
        float s = (y - 100.0f) / 92.0f, w = 30.0f + 14.0f * s + 52.0f * s * s * s;
        if (fabsf(dx) <= w) {
            bool band = fabsf(y - 128.0f) < 2.5f || fabsf(y - 168.0f) < 2.5f;
            return cyl(dx, w, (14.0f + 156.0f * s * s) / 92.0f, n, band ? 1 : 2);
        }
    }
    if (sphere(dx, y - 214.0f, 11.0f, n))
        return 3;
    return 0;
}

/* Hand bell: wooden handle, metal ferrule, wide domed bell. */
static int hand_hit(float x, float y, float n[3])
{
    float dx = x - BELL_CX;
    if (y >= 4.0f && dome(dx, y - 26.0f, 13.0f, 22.0f, n))
        return MAT_WOOD;
    if (y >= 26.0f && y <= 92.0f) {
        float t = (y - 26.0f) / 66.0f, w = 11.0f + 3.0f * t * t;
        if (fabsf(dx) <= w)
            return cyl(dx, w, 0.0f, n, MAT_WOOD);
    }
    if (capsule(dx, y - 97.0f, 20.0f, 7.0f, n))
        return 1;
    if (capsule(dx, y - 200.0f, 100.0f, 8.0f, n))
        return 1;
    if (y >= 102.0f && dome(dx, y - 150.0f, 64.0f, 48.0f, n))
        return 2;
    if (y >= 150.0f && y <= 196.0f) {
        float s = (y - 150.0f) / 46.0f, w = 64.0f + 32.0f * s * s;
        if (fabsf(dx) <= w)
            return cyl(dx, w, 64.0f * s / 46.0f, n, 2);
    }
    if (sphere(dx, y - 216.0f, 12.0f, n))
        return 3;
    return 0;
}

/* Twin bells: two small classic bells swinging outwards under a white bow. */
#define TWIN_SCALE 0.56f
#define TWIN_SIN   0.258819f /* 15 degrees */
#define TWIN_COS   0.965926f

static int twin_hit(float x, float y, float n[3])
{
    if (sphere(x - BELL_CX, y - 56.0f, 9.0f, n)) /* knot */
        return MAT_RIBBON;
    for (int side = -1; side <= 1; side += 2) {
        float lx = BELL_CX + side * 19.0f, ex = x - lx, ey = y - 50.0f;
        float u = ex / 18.0f, v = ey / 10.0f;
        if (u * u + v * v <= 1.0f && ex * ex / 81.0f + ey * ey / 16.0f > 1.0f) /* loop with a hole */
            return set_n(n, u, v, sqrtf(fmaxf(0.0f, 1.0f - u * u - v * v)), MAT_RIBBON);
        float tx = BELL_CX + side * (4.0f + (y - 60.0f) * 0.35f);
        if (y >= 60.0f && y <= 90.0f && fabsf(x - tx) <= 4.0f) /* tails */
            return set_n(n, (x - tx) / 4.0f, 0.0f, 1.0f, MAT_RIBBON);
    }
    int found = 0;
    for (int side = -1; side <= 1; side += 2) { /* the right bell is drawn over the left one */
        float px = BELL_CX + side * 24.0f, dx = x - px, dy = y - 66.0f;
        float s = side * TWIN_SIN; /* rotate the point into the bell's own frame */
        float qx = (dx * TWIN_COS - dy * s) / TWIN_SCALE + BELL_CX;
        float qy = (dx * s + dy * TWIN_COS) / TWIN_SCALE + BELL_PIVOT;
        float m[3];
        int part = bell_hit(qx, qy, m);
        if (part) { /* and the normal back */
            found = set_n(n, m[0] * TWIN_COS + m[1] * s, -m[0] * s + m[1] * TWIN_COS, m[2], part);
        }
    }
    return found;
}

/* Flat: the classic outline as a modern flat icon. */
static int flat_hit(float x, float y, float n[3])
{
    int part = bell_hit(x, y, n);
    return part ? MAT_FLAT + (part == 3) + 2 * (part == 1) : 0;
}

typedef int (*shape_fn)(float x, float y, float n[3]);
static const shape_fn style_shapes[STYLE_COUNT] = {bell_hit, NULL, temple_hit, hand_hit, twin_hit, flat_hit};
/* where each style hangs from (its swing pivot), in shape units */
static const float style_pivot_y[STYLE_COUNT] = {BELL_PIVOT, 0, 16.0f, 10.0f, 50.0f, BELL_PIVOT};

static float clamp01(float v)
{
    return v < 0.0f ? 0.0f : v > 1.0f ? 1.0f : v;
}

/* lv_color32_t byte order: blue, green, red, alpha (straight alpha). */
static void put_px(uint8_t *px, float r, float g, float b, float a)
{
    px[0] = (uint8_t)(255.0f * clamp01(b));
    px[1] = (uint8_t)(255.0f * clamp01(g));
    px[2] = (uint8_t)(255.0f * clamp01(r));
    px[3] = (uint8_t)(255.0f * clamp01(a));
}

/* Colour of one surface sample: lit metal or wood, white ribbon, or unlit flat. */
static void shade(int part, const float n[3], const float base[3], float out[3])
{
    static const float wood[3] = {0x8B / 255.0f, 0x5A / 255.0f, 0x2B / 255.0f};
    static const float ribbon[3] = {0xF4 / 255.0f, 0xF4 / 255.0f, 0xF4 / 255.0f};
    const float *c = part == MAT_WOOD ? wood : part == MAT_RIBBON ? ribbon : base;

    if (part >= MAT_FLAT) { /* flat icon: darker rim and clapper, no lighting */
        float k = part == MAT_FLAT ? 1.0f : part == MAT_FLAT + 1 ? 0.72f : 0.86f;
        for (int i = 0; i < 3; i++)
            out[i] = c[i] * k;
        return;
    }
    /* Light from the upper left, viewer straight ahead; Blinn half vector h. */
    static const float l[3] = {-0.45f, -0.6f, 0.66f}, h[3] = {-0.247035f, -0.329380f, 0.911285f};
    float nl = sqrtf(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
    float diff = fmaxf(0.0f, (n[0] * l[0] + n[1] * l[1] + n[2] * l[2]) / nl);
    float spec = fmaxf(0.0f, (n[0] * h[0] + n[1] * h[1] + n[2] * h[2]) / nl);
    spec *= spec; /* ^32 */
    spec *= spec;
    spec *= spec;
    spec *= spec;
    spec *= spec;
    if (part == MAT_WOOD)
        spec *= 0.25f; /* wood is not shiny */
    /* Rims and knobs catch a little more light; the clapper sits in shadow. */
    float amb = part == 3 ? 0.25f : 0.38f, kd = part == 1 || part == 4 ? 0.8f : 0.7f;
    for (int i = 0; i < 3; i++)
        out[i] = fminf(1.0f, c[i] * (amb + kd * diff) + 0.6f * spec);
}

/*
 * Draws a bell style into a w x h ARGB8888 buffer. `scale` maps shape units to
 * pixels and the shape is centred horizontally (thumbnails are square).
 */
static void render_shape(uint32_t style, uint32_t color, uint8_t *buf, int w, int h, float scale)
{
    const float base[3] = {((color >> 16) & 0xFF) / 255.0f, ((color >> 8) & 0xFF) / 255.0f, (color & 0xFF) / 255.0f};
    const float ox = (w / scale - CLASSIC_W) / 2.0f;
    shape_fn hit = style_shapes[style];

    for (int py = 0; py < h; py++) {
        uint8_t *px = buf + py * w * 4;
        for (int x = 0; x < w; x++, px += 4) {
            float acc[3] = {0, 0, 0};
            int hits = 0;
            for (int sy = 0; sy < CLASSIC_SS; sy++) {
                for (int sx = 0; sx < CLASSIC_SS; sx++) {
                    float n[3], c[3];
                    float u = (x + (sx + 0.5f) / CLASSIC_SS) / scale - ox, v = (py + (sy + 0.5f) / CLASSIC_SS) / scale;
                    int part = hit(u, v, n);
                    if (!part)
                        continue;
                    shade(part, n, base, c);
                    if (style == STYLE_FLAT) { /* shine: a thin white arc on the upper left of the dome */
                        float a = u - 84.0f, b = v - 78.0f, e = a * a / 400.0f + b * b / 900.0f;
                        if (e > 0.55f && e <= 1.0f && a < 0.0f && b < 10.0f)
                            for (int i = 0; i < 3; i++)
                                c[i] += (1.0f - c[i]) * 0.6f;
                    }
                    for (int i = 0; i < 3; i++)
                        acc[i] += c[i];
                    hits++;
                }
            }
            if (hits)
                put_px(px, acc[0] / hits, acc[1] / hits, acc[2] / hits, hits / (float)(CLASSIC_SS * CLASSIC_SS));
            else
                put_px(px, 0, 0, 0, 0);
        }
    }
}

/*
 * One pixel of the push-button disc of radius r, at (fx, fy) from its centre:
 * colour into rgb, returns coverage (0 outside). `edge` is the rim width.
 */
static float button_px(float fx, float fy, float r, float edge, const float base[3], float rgb[3])
{
    float d = sqrtf(fx * fx + fy * fy);
    float cov = clamp01(r - d + 0.5f); /* anti-aliased edge */
    if (cov <= 0.0f)
        return 0.0f;
    float lit = 1.18f - 0.38f * (fy + r) / (2.0f * r); /* lit from above */
    float rim = clamp01(1.0f - (r - d) / edge);        /* darker raised edge */
    float gx = fx / (r * 0.78f), gy = (fy + r * 0.42f) / (r * 0.42f);
    float gloss = clamp01(1.0f - (gx * gx + gy * gy));
    gloss = gloss * sqrtf(gloss) * 0.35f;               /* soft highlight, upper half */
    for (int k = 0; k < 3; k++) {
        float v = clamp01(base[k] * lit * (1.0f - 0.25f * rim));
        rgb[k] = v + (1.0f - v) * gloss;
    }
    return cov;
}

static void render_button(uint32_t color)
{
    const float c = BTN_SIZE / 2.0f;
    const float base[3] = {((color >> 16) & 0xFF) / 255.0f, ((color >> 8) & 0xFF) / 255.0f, (color & 0xFF) / 255.0f};

    for (int y = 0; y < BTN_SIZE; y++) {
        uint8_t *px = btn_buf + y * BTN_SIZE * 4;
        for (int x = 0; x < BTN_SIZE; x++, px += 4) {
            float fx = x + 0.5f - c, fy = y + 0.5f - c, rgb[3];
            float ds = sqrtf(fx * fx + (fy - 7.0f) * (fy - 7.0f)); /* shadow falls a little below */
            float sh = clamp01((BTN_R + 12.0f - ds) / 22.0f);
            sh = sh * sh * 0.45f;
            float cov = button_px(fx, fy, BTN_R, 6.0f, base, rgb);
            if (cov <= 0.0f)
                put_px(px, 0, 0, 0, sh);
            else
                put_px(px, rgb[0], rgb[1], rgb[2], cov + sh * (1.0f - cov));
        }
    }
}

/* Small push-button for the style picker: the disc with the white bell on it. */
static void render_button_thumb(uint32_t color, uint8_t *buf, int size)
{
    const float c = size / 2.0f, r = size * 0.46f, gs = 1.4f * r / CLASSIC_H; /* bell ~70 % of the disc */
    const float base[3] = {((color >> 16) & 0xFF) / 255.0f, ((color >> 8) & 0xFF) / 255.0f, (color & 0xFF) / 255.0f};
    float n[3];

    for (int y = 0; y < size; y++) {
        uint8_t *px = buf + y * size * 4;
        for (int x = 0; x < size; x++, px += 4) {
            float rgb[3];
            float cov = button_px(x + 0.5f - c, y + 0.5f - c, r, 2.0f, base, rgb);
            if (cov <= 0.0f) {
                put_px(px, 0, 0, 0, 0);
                continue;
            }
            int hits = 0;
            for (int sy = 0; sy < CLASSIC_SS; sy++)
                for (int sx = 0; sx < CLASSIC_SS; sx++)
                    hits += bell_hit((x + (sx + 0.5f) / CLASSIC_SS - c) / gs + BELL_CX,
                                     (y + (sy + 0.5f) / CLASSIC_SS - c) / gs + CLASSIC_H / 2.0f, n) != 0;
            float w = hits / (float)(CLASSIC_SS * CLASSIC_SS);
            for (int k = 0; k < 3; k++)
                rgb[k] += (1.0f - rgb[k]) * w;
            put_px(px, rgb[0], rgb[1], rgb[2], cov);
        }
    }
}

/* White bell symbol with a soft shadow down-right (it rotates with the symbol). */
static void render_glyph(void)
{
    const float ox = (GLYPH_W - 216.0f * GLYPH_SCALE) / 2.0f;
    float n[3];

    for (int y = 0; y < GLYPH_H; y++) {
        uint8_t *px = glyph_buf + y * GLYPH_W * 4;
        for (int x = 0; x < GLYPH_W; x++, px += 4) {
            int hits = 0, shadow = 0;
            for (int sy = 0; sy < GLYPH_SS; sy++)
                for (int sx = 0; sx < GLYPH_SS; sx++)
                    hits += bell_hit((x + (sx + 0.5f) / GLYPH_SS - ox) / GLYPH_SCALE,
                                     (y + (sy + 0.5f) / GLYPH_SS - 4.0f) / GLYPH_SCALE, n) != 0;
            for (int sy = 0; sy < 2; sy++)
                for (int sx = 0; sx < 2; sx++)
                    shadow += bell_hit((x - 2.0f + (sx + 0.5f) / 2.0f - ox) / GLYPH_SCALE,
                                       (y - 3.0f + (sy + 0.5f) / 2.0f - 4.0f) / GLYPH_SCALE, n) != 0;
            float a = hits / (float)(GLYPH_SS * GLYPH_SS), sh = shadow / 4.0f * 0.27f;
            if (a <= 0.0f) {
                put_px(px, 0, 0, 0, sh);
                continue;
            }
            /* barely shaded towards the right so the symbol is not flat */
            float lit = 1.0f;
            if (bell_hit((x + 0.5f - ox) / GLYPH_SCALE, (y + 0.5f - 4.0f) / GLYPH_SCALE, n))
                lit = clamp01(0.97f - 0.06f * n[0]);
            put_px(px, lit, lit, lit, a + sh * (1.0f - a));
        }
    }
}

/* ---- background glow ----
 * One soft white disc with a Gaussian falloff, shown three times and tinted
 * magenta, cyan and violet by LVGL's image recolouring; a timer only moves and
 * fades the three, so no pixels are recomputed while it animates. */
#define GLOW_SIZE 300
static lv_image_dsc_t glow_dsc;
static uint8_t *glow_buf;
static const uint32_t glow_colors[3] = {0xFF2BD6, 0x00E5FF, 0x8C50FF};

static void render_glow(void)
{
    const float c = GLOW_SIZE / 2.0f;
    for (int y = 0; y < GLOW_SIZE; y++) {
        uint8_t *px = glow_buf + y * GLOW_SIZE * 4;
        for (int x = 0; x < GLOW_SIZE; x++, px += 4) {
            float dx = (x + 0.5f - c) / c, dy = (y + 0.5f - c) / c;
            put_px(px, 1, 1, 1, expf(-4.5f * (dx * dx + dy * dy))); /* ~1 % at the edge */
        }
    }
}

static void init_dsc(lv_image_dsc_t *dsc, uint8_t **buf, int w, int h)
{
    *buf = lv_malloc(w * h * 4);
    LV_ASSERT_MALLOC(*buf);
    memset(dsc, 0, sizeof(*dsc));
    dsc->header.magic = LV_IMAGE_HEADER_MAGIC;
    dsc->header.cf = LV_COLOR_FORMAT_ARGB8888;
    dsc->header.w = w;
    dsc->header.h = h;
    dsc->header.stride = w * 4;
    dsc->data_size = w * h * 4;
    dsc->data = *buf;
}

/*
 * Redraws the art of the current style in the current bell colour, and with
 * `thumbs` also the style picker's thumbnails (they only change with colour).
 */
static void update_bell_art(bool thumbs)
{
    uint32_t color = cur_bell_color();

    if (cur_style() == STYLE_BUTTON) {
        render_button(color);
        lv_image_cache_drop(&btn_dsc);
    } else {
        render_shape(cur_style(), color, classic_buf, CLASSIC_W, CLASSIC_H, 1.0f);
        lv_image_cache_drop(&classic_dsc);
    }
    if (btn_img)
        lv_obj_invalidate(btn_img);
    if (bell_img)
        lv_obj_invalidate(bell_img);

    color = bell_colors[bell_idx].color; /* the Bell page shows the user's own choice */
    for (uint32_t s = 0; thumbs && s < STYLE_COUNT; s++) {
        if (s == STYLE_BUTTON)
            render_button_thumb(color, thumb_buf[s], THUMB);
        else
            render_shape(s, color, thumb_buf[s], THUMB, THUMB, THUMB / (float)CLASSIC_H);
        lv_image_cache_drop(&thumb_dsc[s]);
        if (style_thumbs[s])
            lv_obj_invalidate(style_thumbs[s]);
    }
}

static void init_bell_art(void)
{
    init_dsc(&classic_dsc, &classic_buf, CLASSIC_W, CLASSIC_H);
    init_dsc(&btn_dsc, &btn_buf, BTN_SIZE, BTN_SIZE);
    init_dsc(&glyph_dsc, &glyph_buf, GLYPH_W, GLYPH_H);
    for (uint32_t s = 0; s < STYLE_COUNT; s++)
        init_dsc(&thumb_dsc[s], &thumb_buf[s], THUMB, THUMB);
    init_dsc(&glow_dsc, &glow_buf, GLOW_SIZE, GLOW_SIZE);
    render_glyph();
    render_glow();
}

/* ---------- theme ---------- */

static void apply_theme(void)
{
    const theme_t *t = cur_theme();

    lv_style_set_bg_color(&st_screen, lv_color_hex(t->bg_top));
    lv_style_set_bg_grad_color(&st_screen, lv_color_hex(t->bg_bottom));
    lv_style_set_text_color(&st_screen, lv_color_hex(t->text));
    lv_style_set_text_color(&st_text, lv_color_hex(t->text));
    lv_style_set_text_color(&st_muted, lv_color_hex(t->muted));
    lv_style_set_line_color(&st_muted, lv_color_hex(t->muted));
    lv_style_set_text_color(&st_accent_text, lv_color_hex(t->accent));
    lv_style_set_bg_color(&st_card, lv_color_hex(t->card));
    lv_style_set_border_color(&st_card, lv_color_hex(t->card_border));
    lv_style_set_bg_color(&st_card_pressed, lv_color_hex(t->pressed));
    lv_style_set_border_color(&st_card_checked, lv_color_hex(t->accent));
    lv_style_set_bg_color(&st_accent, lv_color_hex(t->accent));
    lv_style_set_text_color(&st_accent, lv_color_hex(t->on_accent));
    lv_style_set_bg_color(&st_accent_pressed, lv_color_darken(lv_color_hex(t->accent), LV_OPA_20));
    lv_style_set_arc_color(&st_wave, lv_color_hex(cur_bell_color()));
    lv_style_set_border_color(&st_halo, lv_color_hex(cur_bell_color()));
    lv_style_set_arc_color(&st_progress, lv_color_hex(t->accent));
    lv_style_set_bg_color(&st_dot, lv_color_hex(t->muted));
    lv_style_set_outline_color(&st_swatch_checked, lv_color_hex(t->text));

    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_hex(t->bg_bottom), LV_PART_MAIN);
    lv_obj_report_style_change(NULL);
}

static void init_styles(void)
{
    lv_style_init(&st_screen);
    lv_style_set_bg_opa(&st_screen, LV_OPA_COVER);
    lv_style_set_bg_grad_dir(&st_screen, LV_GRAD_DIR_VER);

    lv_style_init(&st_text);
    lv_style_init(&st_muted);
    lv_style_init(&st_accent_text);

    lv_style_init(&st_card);
    lv_style_set_bg_opa(&st_card, LV_OPA_COVER);
    lv_style_set_radius(&st_card, 18);
    lv_style_set_border_width(&st_card, 1);

    lv_style_init(&st_card_pressed);
    lv_style_init(&st_card_checked);
    lv_style_set_border_width(&st_card_checked, 3);

    lv_style_init(&st_accent);
    lv_style_set_bg_opa(&st_accent, LV_OPA_COVER);
    lv_style_set_radius(&st_accent, LV_RADIUS_CIRCLE);
    lv_style_init(&st_accent_pressed);

    lv_style_init(&st_wave);
    lv_style_set_arc_width(&st_wave, 6);
    lv_style_set_arc_rounded(&st_wave, true);

    lv_style_init(&st_halo);
    lv_style_set_radius(&st_halo, LV_RADIUS_CIRCLE);
    lv_style_set_border_width(&st_halo, 3);

    lv_style_init(&st_progress);
    lv_style_set_arc_width(&st_progress, 6);
    lv_style_set_arc_rounded(&st_progress, true);

    lv_style_init(&st_dot);
    lv_style_set_bg_opa(&st_dot, LV_OPA_50);
    lv_style_set_radius(&st_dot, LV_RADIUS_CIRCLE);

    lv_style_init(&st_swatch_checked);
    lv_style_set_outline_width(&st_swatch_checked, 3);
    lv_style_set_outline_pad(&st_swatch_checked, 4);
}

/* ---------- widget helpers ---------- */

static lv_obj_t *add_box(lv_obj_t *parent, int32_t w, int32_t h)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_set_size(o, w, h);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static lv_obj_t *add_text(lv_obj_t *parent, const lv_font_t *font, int32_t y, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, LV_PART_MAIN);
    lv_label_set_text(l, text);
    lv_obj_align(l, LV_ALIGN_TOP_MID, 0, y);
    return l;
}

static lv_obj_t *add_muted(lv_obj_t *parent, const lv_font_t *font, int32_t y, const char *text)
{
    lv_obj_t *l = add_text(parent, font, y, text);
    lv_obj_add_style(l, &st_muted, LV_PART_MAIN);
    return l;
}

/* Fixed-width centred label that ends in "..." instead of overflowing. */
static void clip_label(lv_obj_t *l, int32_t width)
{
    lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
    lv_obj_set_width(l, width);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
}

/* Centred, wrapped explanatory paragraph. */
static lv_obj_t *add_note(lv_obj_t *parent, int32_t y, const char *text)
{
    lv_obj_t *l = add_muted(parent, &lv_font_montserrat_14, y, text);
    lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(l, 290);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
    lv_obj_align(l, LV_ALIGN_TOP_MID, 0, y);
    return l;
}

/* Tappable card with pressed/checked feedback. */
static lv_obj_t *add_card(lv_obj_t *parent, int32_t w, int32_t h, lv_event_cb_t cb, void *user_data)
{
    lv_obj_t *c = add_box(parent, w, h);
    lv_obj_add_style(c, &st_card, LV_PART_MAIN);
    lv_obj_add_style(c, &st_card_pressed, LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_add_style(c, &st_card_checked, LV_PART_MAIN | LV_STATE_CHECKED);
    if (cb) {
        lv_obj_add_flag(c, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(c, cb, LV_EVENT_CLICKED, user_data);
    }
    return c;
}

static lv_obj_t *add_pill(lv_obj_t *parent, int32_t w, int32_t y, const char *text, lv_event_cb_t cb,
                          void *user_data)
{
    lv_obj_t *b = add_box(parent, w, 44);
    lv_obj_add_style(b, &st_accent, LV_PART_MAIN);
    lv_obj_add_style(b, &st_accent_pressed, LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, user_data);
    lv_obj_align(b, LV_ALIGN_TOP_MID, 0, y);
    lv_obj_t *l = lv_label_create(b);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_16, LV_PART_MAIN);
    lv_label_set_text(l, text);
    lv_obj_center(l);
    return b;
}

static lv_obj_t *add_page(void)
{
    lv_obj_t *p = add_box(lv_screen_active(), SCREEN_SIZE, SCREEN_SIZE);
    lv_obj_add_style(p, &st_screen, LV_PART_MAIN);
    lv_obj_center(p);
    lv_obj_add_flag(p, LV_OBJ_FLAG_HIDDEN);
    return p;
}

/* ---------- network status on screen ---------- */

static void show_status(status_view_t *v, const char *sub, uint32_t dot, const char *state)
{
    lv_label_set_text(v->sub, sub);
    lv_obj_set_style_bg_color(v->dot, lv_color_hex(dot), LV_PART_MAIN);
    lv_label_set_text(v->state, state);
}

static void refresh_net(void)
{
    char buf[48];
    bool online = ns.wifi == NET_WIFI_CONNECTED;

    lv_obj_set_style_text_opa(wifi_icon, online ? LV_OPA_COVER : LV_OPA_60, LV_PART_MAIN);
    if (online)
        lv_obj_add_flag(wifi_slash, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_remove_flag(wifi_slash, LV_OBJ_FLAG_HIDDEN);

    switch (ns.wifi) {
    case NET_WIFI_NONE:
        show_status(&wifi_view, "No network saved", DOT_IDLE, "Not connected");
        break;
    case NET_WIFI_CONNECTING:
        show_status(&wifi_view, ns.ssid, DOT_BUSY, "Connecting...");
        break;
    case NET_WIFI_CONNECTED:
        lv_snprintf(buf, sizeof(buf), "Connected  %s", ns.ip);
        show_status(&wifi_view, ns.ssid, DOT_OK, buf);
        break;
    case NET_WIFI_FAILED:
        show_status(&wifi_view, ns.ssid, DOT_BAD, "Could not connect");
        break;
    }

    if (ns.broker[0])
        lv_snprintf(buf, sizeof(buf), "Broker %s", ns.broker);
    else
        lv_snprintf(buf, sizeof(buf), "No broker address set");
    if (!ns.broker[0])
        show_status(&ctrl_view, buf, DOT_IDLE, "Not set up");
    else if (!online)
        show_status(&ctrl_view, buf, DOT_IDLE, "Waiting for Wi-Fi");
    else if (ns.mqtt == NET_MQTT_UP && ns.ring == NET_RING_FAILED)
        show_status(&ctrl_view, buf, DOT_BAD, "Last ring not confirmed");
    else if (ns.mqtt == NET_MQTT_UP)
        show_status(&ctrl_view, buf, DOT_OK, "Connected");
    else if (ns.mqtt == NET_MQTT_CONNECTING)
        show_status(&ctrl_view, buf, DOT_BUSY, "Connecting...");
    else
        show_status(&ctrl_view, buf, DOT_BAD, "Not reachable");
}

static void ap_cb(lv_event_t *e);

static void rebuild_ap_list(void)
{
    uint32_t count = ns.ap_count;

    lv_obj_clean(ap_list);
    memcpy(shown_aps, ns.aps, sizeof(shown_aps));
    if (ns.scanning || count == 0) {
        lv_label_set_text(ap_msg, ns.scanning ? "Scanning..." : "No networks found");
        lv_obj_remove_flag(ap_msg, LV_OBJ_FLAG_HIDDEN);
        if (ns.scanning)
            return;
    } else {
        lv_obj_add_flag(ap_msg, LV_OBJ_FLAG_HIDDEN);
    }
    for (uint32_t i = 0; i < count; i++) {
        lv_obj_t *row = add_card(ap_list, 290, 48, ap_cb, (void *)(intptr_t)i);

        lv_obj_t *name = lv_label_create(row);
        lv_obj_set_style_text_font(name, &lv_font_montserrat_16, LV_PART_MAIN);
        lv_label_set_long_mode(name, LV_LABEL_LONG_DOT);
        lv_obj_set_width(name, 180);
        lv_label_set_text(name, shown_aps[i].ssid);
        lv_obj_align(name, LV_ALIGN_LEFT_MID, 16, 0);

        if (!shown_aps[i].secure) {
            lv_obj_t *open = lv_label_create(row);
            lv_obj_add_style(open, &st_muted, LV_PART_MAIN);
            lv_obj_set_style_text_font(open, &lv_font_montserrat_14, LV_PART_MAIN);
            lv_label_set_text(open, "open");
            lv_obj_align(open, LV_ALIGN_RIGHT_MID, -50, 0);
        }
        /* signal strength as icon brightness */
        lv_obj_t *sig = lv_label_create(row);
        lv_obj_add_style(sig, &st_accent_text, LV_PART_MAIN);
        lv_label_set_text(sig, LV_SYMBOL_WIFI);
        int8_t rssi = shown_aps[i].rssi;
        lv_obj_set_style_text_opa(sig, rssi >= -60 ? LV_OPA_COVER : rssi >= -72 ? LV_OPA_70 : LV_OPA_40,
                                  LV_PART_MAIN);
        lv_obj_align(sig, LV_ALIGN_RIGHT_MID, -14, 0);
    }
}

/* ---------- page switching ---------- */

static void refresh_values(void)
{
    for (uint32_t i = 0; i < THEME_COUNT; i++)
        lv_obj_set_state(theme_cards[i], LV_STATE_CHECKED, i == theme_idx);
    for (uint32_t i = 0; i < BELL_COLOR_COUNT; i++)
        lv_obj_set_state(swatches[i], LV_STATE_CHECKED, i == bell_idx);
    for (uint32_t i = 0; i < STYLE_COUNT; i++)
        lv_obj_set_state(style_cards[i], LV_STATE_CHECKED, i == bell_style);
    lv_obj_set_state(glow_card, LV_STATE_CHECKED, glow_on);
    for (uint32_t i = 0; i < CHIME_COUNT; i++)
        lv_obj_set_state(chime_cards[i], LV_STATE_CHECKED, i == chime_idx);
    for (uint32_t i = 0; i < 2; i++)
        lv_obj_set_state(repeat_cards[i], LV_STATE_CHECKED, (i == 1) == chime_repeat);
    /* the closest level, so a volume set from the indoor unit still shows */
    uint32_t best = 0;
    for (uint32_t i = 1; i < VOLUME_COUNT; i++)
        if (abs((int)volumes[i].volume - chime_volume) < abs((int)volumes[best].volume - chime_volume))
            best = i;
    for (uint32_t i = 0; i < VOLUME_COUNT; i++)
        lv_obj_set_state(volume_cards[i], LV_STATE_CHECKED, i == best);
    for (uint32_t i = 0; i < 2; i++) {
        lv_obj_set_state(fest_look_cards[i], LV_STATE_CHECKED, (i == 0) == fest_look_on);
        lv_obj_set_state(fest_chime_cards[i], LV_STATE_CHECKED, (i == 0) == fest_chime_on);
    }
    if (fest_trial)
        lv_label_set_text_fmt(fest_now, "Trying %s for a minute", fest_trial->theme.name);
    else if (fest)
        lv_label_set_text_fmt(fest_now, "Now: %s", fest->theme.name);
    else if (ns.festival[0] && !fest_look_on)
        lv_label_set_text(fest_now, "Festival now, festive look off");
    else
        lv_label_set_text(fest_now, "No festival now");
    lv_label_set_text(lv_obj_get_child(glow_card, 0), glow_on ? LV_SYMBOL_EYE_OPEN "  Glow: Aurora" : "Glow: Off");
    for (uint32_t i = 0; i < DURATION_COUNT; i++)
        lv_obj_set_state(duration_btns[i], LV_STATE_CHECKED, durations[i] == ring_seconds);
    refresh_net();
}

static void apply_glow(void);

static void set_page(page_t p)
{
    lv_obj_add_flag(pages[page], LV_OBJ_FLAG_HIDDEN);
    page = p;
    refresh_values();
    lv_obj_remove_flag(pages[page], LV_OBJ_FLAG_HIDDEN);
    apply_glow(); /* the glow only runs on the home screen */
}

/* ---------- ringing animation ---------- */

static void swing_cb(void *obj, int32_t v)
{
    /* +-14 degrees (LVGL rotation is in 0.1 degree units) */
    lv_image_set_rotation((lv_obj_t *)obj, (int32_t)(140 * lv_trigo_sin((int16_t)v) / LV_TRIGO_SIN_MAX));
}

static void settle_cb(void *obj, int32_t v)
{
    lv_image_set_rotation((lv_obj_t *)obj, v);
}

static void wave_opa_cb(void *obj, int32_t v)
{
    lv_obj_set_style_arc_opa((lv_obj_t *)obj, (lv_opa_t)v, LV_PART_MAIN);
}

/* Idle invitation to press: a ring grows out of the button edge and fades. v: 0..1000 */
static void halo_cb(void *obj, int32_t v)
{
    int32_t d = (int32_t)(2 * BTN_R) + 4 + 56 * v / 1000;
    lv_obj_set_size((lv_obj_t *)obj, d, d);
    lv_obj_align((lv_obj_t *)obj, LV_ALIGN_TOP_MID, 0, BTN_CY - d / 2);
    lv_obj_set_style_border_opa((lv_obj_t *)obj, (lv_opa_t)(170 * (1000 - v) / 1000), LV_PART_MAIN);
}

/*
 * Aurora: the three tinted glows circle the bell on slightly different paths
 * and breathe in brightness. Idle: one cycle in ~24 s, updated 10x a second
 * (the motion is slow). Ringing: three times faster, brighter, 30 updates/s.
 */
#define GLOW_IDLE_MS 100
#define GLOW_RING_MS 33

static void glow_tick(lv_timer_t *t)
{
    static float phase;
    const float pi2 = 6.2831853f;
    uint32_t step = is_ringing ? GLOW_RING_MS : GLOW_IDLE_MS; /* the period apply_glow() set */
    float boost = is_ringing ? 1.6f : 1.0f;

    (void)t;

    phase += (is_ringing ? 3.0f : 1.0f) * step / 24000.0f;
    if (phase > 1.0f)
        phase -= 1.0f;
    for (int i = 0; i < 3; i++) {
        float a = phase * pi2 + i * 2.1f;
        float x = SCREEN_SIZE / 2.0f + 95.0f * cosf(a) * (i == 2 ? 0.6f : 1.0f);
        float y = BTN_CY + 70.0f * sinf(a * (i == 1 ? 2.0f : 1.0f)); /* cyan loops twice as often */
        float k = (0.62f + 0.38f * sinf(2.0f * a + i)) * boost;   /* breathing */
        lv_obj_set_pos(glow_blobs[i], (int32_t)x - GLOW_SIZE / 2, (int32_t)y - GLOW_SIZE / 2);
        lv_obj_set_style_image_opa(glow_blobs[i], (lv_opa_t)fminf(255.0f, cur_theme()->glow * k), LV_PART_MAIN);
    }
}

/* Shows or hides the glow and sets its pace; call after any change to theme,
 * glow setting, page or ringing state. */
static void apply_glow(void)
{
    bool run = glow_on && page == HOME && !screen_off;
    for (int i = 0; i < 3; i++) {
        if (run)
            lv_obj_remove_flag(glow_blobs[i], LV_OBJ_FLAG_HIDDEN);
        else
            lv_obj_add_flag(glow_blobs[i], LV_OBJ_FLAG_HIDDEN);
    }
    if (!run) {
        lv_timer_pause(glow_timer);
        return;
    }
    lv_timer_set_period(glow_timer, is_ringing ? GLOW_RING_MS : GLOW_IDLE_MS);
    lv_timer_resume(glow_timer);
    glow_tick(glow_timer);
}

static void set_halo(bool run)
{
    lv_anim_delete(halo, halo_cb);
    if (!run) {
        lv_obj_add_flag(halo, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_remove_flag(halo, LV_OBJ_FLAG_HIDDEN);
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, halo);
    lv_anim_set_exec_cb(&a, halo_cb);
    lv_anim_set_values(&a, 0, 1000);
    lv_anim_set_duration(&a, 1600);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    lv_anim_set_repeat_delay(&a, 900);
    lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    lv_anim_start(&a);
}

/* Arranges the home screen for the current bell style (art must be rendered). */
static void apply_bell_style(void)
{
    bool button = cur_style() == STYLE_BUTTON;
    int32_t cy = button ? BTN_CY : CLASSIC_CY;

    if (button) {
        lv_obj_remove_flag(btn_img, LV_OBJ_FLAG_HIDDEN);
        lv_image_set_src(bell_img, &glyph_dsc);
        lv_image_set_pivot(bell_img, GLYPH_W / 2, GLYPH_PIVOT);
        lv_obj_align(bell_img, LV_ALIGN_TOP_MID, 0, BTN_CY - GLYPH_H / 2 - 4);
    } else {
        lv_obj_add_flag(btn_img, LV_OBJ_FLAG_HIDDEN);
        lv_image_set_src(bell_img, &classic_dsc);
        lv_image_set_pivot(bell_img, CLASSIC_W / 2, (int32_t)style_pivot_y[cur_style()]);
        lv_obj_align(bell_img, LV_ALIGN_TOP_MID, 0, CLASSIC_Y);
    }
    for (uint32_t i = 0; i < 4; i++)
        lv_obj_align(ring_waves[i], LV_ALIGN_TOP_MID, 0, cy - lv_obj_get_height(ring_waves[i]) / 2);
    /* the classic bell is taller, so its clock sits a little higher */
    lv_obj_align(home_clock, LV_ALIGN_TOP_MID, 0, button ? 330 : 318);
    lv_obj_align(home_date, LV_ALIGN_TOP_MID, 0, button ? 388 : 374);
    set_halo(button && !is_ringing);
}

static void set_ring_animation(bool run)
{
    lv_anim_t a;

    set_halo(!run && cur_style() == STYLE_BUTTON); /* the sound waves take over while ringing */
    apply_glow();                                 /* faster and brighter while ringing */

    lv_anim_delete(bell_img, swing_cb);
    lv_anim_delete(bell_img, settle_cb);
    lv_anim_init(&a);
    lv_anim_set_var(&a, bell_img);
    if (run) {
        lv_anim_set_exec_cb(&a, swing_cb);
        lv_anim_set_values(&a, 0, 360);
        lv_anim_set_duration(&a, 700);
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
    } else {
        /* ease back to rest from wherever the swing currently is */
        lv_anim_set_exec_cb(&a, settle_cb);
        lv_anim_set_values(&a, lv_image_get_rotation(bell_img), 0);
        lv_anim_set_duration(&a, 300);
        lv_anim_set_path_cb(&a, lv_anim_path_ease_out);
    }
    lv_anim_start(&a);

    for (uint32_t i = 0; i < 4; i++) {
        lv_anim_delete(ring_waves[i], wave_opa_cb);
        if (!run) {
            lv_obj_add_flag(ring_waves[i], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        lv_obj_remove_flag(ring_waves[i], LV_OBJ_FLAG_HIDDEN);
        lv_anim_init(&a);
        lv_anim_set_var(&a, ring_waves[i]);
        lv_anim_set_exec_cb(&a, wave_opa_cb);
        lv_anim_set_values(&a, LV_OPA_TRANSP, LV_OPA_COVER);
        lv_anim_set_duration(&a, 350);
        lv_anim_set_playback_duration(&a, 350);
        lv_anim_set_delay(&a, (i % 2) * 175); /* outer waves trail the inner ones */
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
        lv_anim_start(&a);
    }
}

static void end_ring(void)
{
    if (ring_timer) {
        lv_timer_delete(ring_timer);
        ring_timer = NULL;
    }
    is_ringing = false;
    set_ring_animation(false);
    if (chime_repeat)
        sound_stop(); /* a single chime just finishes */
}

static void timeout_cb(lv_timer_t *t)
{
    (void)t;
    end_ring(); /* the indoor unit runs the same timer, so nothing is sent */
}

/* Stopped here (opening settings mid-ring): tell the indoor unit too. */
static void stop_ring(void)
{
    if (is_ringing)
        net_publish_stop();
    end_ring();
}

static void start_ring(void)
{
    if (is_ringing)
        return; /* repeated presses by a visitor do not restart or cancel it */
    is_ringing = true;
    net_publish_start(ring_seconds);
    if (ns.broker[0]) /* the indoor unit records the visitor: the microphone from 3 s before the press */
        listen_start(ns.broker, DOORBELL_LISTEN_PORT, LISTEN_PRESS_S, true);
    use_chime(ring_chime());  /* a Sound page preview may have loaded another */
    sound_play(chime_repeat); /* the visitor hears that it rang */
    set_ring_animation(true);
    ring_timer = lv_timer_create(timeout_cb, ring_seconds * 1000, NULL);
    lv_timer_set_repeat_count(ring_timer, 1);
}

static int clock_shown = -1; /* minute of the day on screen, x2, +1 while the greeting shows */

/* Local time once NTP has set the system clock; placeholders until then. */
static void update_clock(void)
{
    static const char *const days[] = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};
    static const char *const months[] = {"January", "February", "March",     "April",   "May",      "June",
                                         "July",    "August",   "September", "October", "November", "December"};

    if (!ns.time_synced)
        return;
    TIME_T t = tal_time_get_posix() + DOORBELL_UTC_OFFSET_S;
    POSIX_TM_S tm;
    tal_time_gmtime_r(&t, &tm);
    const char *text = fest && !fest_trial && ns.festival_greeting[0] ? ns.festival_greeting : fest ? fest->greeting : "";
    if (talk_active())
        text = LV_SYMBOL_AUDIO "  Talking to indoor unit";
    bool greet = text[0] && (talk_active() || (t / 5) % 2 == 0); /* 5 s greeting, 5 s date; a call stays */
    int now = (tm.tm_hour * 60 + tm.tm_min) * 2 + greet;
    if (now == clock_shown)
        return;
    clock_shown = now;
    int h12 = tm.tm_hour % 12 ? tm.tm_hour % 12 : 12;
    lv_label_set_text_fmt(home_clock, "%d:%02d %s", h12, tm.tm_min, tm.tm_hour < 12 ? "AM" : "PM");
    if (greet)
        lv_label_set_text(home_date, text);
    else
        lv_label_set_text_fmt(home_date, "%s, %d %s", days[tm.tm_wday % 7], tm.tm_mday, months[tm.tm_mon % 12]);
}

/* Settings changed from the indoor unit: same effect as tapping them here. */
static void apply_remote_settings(void)
{
    bool art = false;
    if (ns.remote_theme >= 0 && (uint32_t)ns.remote_theme < THEME_COUNT && (uint32_t)ns.remote_theme != theme_idx) {
        theme_idx = ns.remote_theme;
        bell_idx = themes[theme_idx].bell; /* as on the device: a theme brings its bell colour... */
        art = true;
    }
    if (ns.remote_bell >= 0 && (uint32_t)ns.remote_bell < BELL_COLOR_COUNT && (uint32_t)ns.remote_bell != bell_idx) {
        bell_idx = ns.remote_bell; /* ...unless the message names one */
        art = true;
    }
    for (uint32_t i = 0; i < DURATION_COUNT; i++)
        if (ns.remote_ring >= 0 && durations[i] == (uint32_t)ns.remote_ring)
            ring_seconds = durations[i];
    bool style = ns.remote_style >= 0 && (uint32_t)ns.remote_style < STYLE_COUNT &&
                 (uint32_t)ns.remote_style != bell_style;
    if (style)
        bell_style = ns.remote_style;
    if (ns.remote_glow >= 0)
        glow_on = ns.remote_glow != 0;
    if (ns.remote_chime >= 0 && (uint32_t)ns.remote_chime < CHIME_COUNT && (uint32_t)ns.remote_chime != chime_idx) {
        chime_idx = ns.remote_chime;
        use_chime(ring_chime());
    }
    if (ns.remote_repeat >= 0)
        chime_repeat = ns.remote_repeat != 0;
    if (ns.remote_volume >= 0 && ns.remote_volume <= 100) {
        chime_volume = (uint8_t)ns.remote_volume;
        sound_set_volume(chime_volume);
    }
    if (ns.remote_night_on >= 0)
        night_on = ns.remote_night_on != 0;
    if (ns.remote_night_from >= 0 && ns.remote_night_from < 24)
        night_from = ns.remote_night_from;
    if (ns.remote_night_to >= 0 && ns.remote_night_to < 24)
        night_to = ns.remote_night_to;
    PR_NOTICE("[DOORBELL] settings from indoor unit: theme %u, bell %u, style %u, glow %d, chime %u%s vol %u, ring %us",
              (unsigned)theme_idx, (unsigned)bell_idx, (unsigned)bell_style, glow_on, (unsigned)chime_idx,
              chime_repeat ? " repeating," : ",", (unsigned)chime_volume, (unsigned)ring_seconds);
    if (art || style)
        update_bell_art(art); /* thumbnails only change with the colour */
    if (style)
        apply_bell_style();
    apply_glow();
    apply_theme();
    refresh_values();
    save_config();
}

/* Switches between the festival look and the user's own when the indoor unit
 * says so, or when the festival's end time passes on our clock. */
static void check_festival(void)
{
    const festival_t *want = NULL;
    bool over = ns.festival_until && ns.time_synced && (uint32_t)tal_time_get_posix() >= ns.festival_until;
    for (uint32_t i = 0; fest_look_on && ns.festival[0] && !over && i < FESTIVAL_COUNT; i++)
        if (strcmp(ns.festival, festivals[i].key) == 0)
            want = &festivals[i];
    if (fest_trial && (int32_t)(lv_tick_get() - fest_trial_end) >= 0) {
        fest_trial = NULL;
        refresh_values();
    }
    if (fest_trial)
        want = fest_trial;
    bool tones = want && fest_chime_on && (fest_trial || ns.festival_tones);
    if (want == fest && tones == fest_tones)
        return;
    PR_NOTICE("[DOORBELL] festival theme: %s", want ? want->key : "off");
    fest = want;
    fest_tones = tones;
    if (!is_ringing) /* never cut the visitor's chime short */
        use_chime(ring_chime());
    for (int i = 0; i < 3; i++)
        lv_obj_set_style_image_recolor(glow_blobs[i], lv_color_hex(fest ? fest->glow[i] : glow_colors[i]), LV_PART_MAIN);
    update_bell_art(false);
    apply_bell_style();
    apply_theme();
    apply_glow();
    clock_shown = -1;
    update_clock();
    refresh_values();
}

/* ---------- night: screen off ---------- */

static bool night_now(void)
{
    if (!night_on || night_from == night_to || !ns.time_synced)
        return false; /* off, an empty window, or a clock that is not set: never dark */
    TIME_T t = tal_time_get_posix() + DOORBELL_UTC_OFFSET_S;
    POSIX_TM_S tm;
    tal_time_gmtime_r(&t, &tm);
    uint32_t h = (uint32_t)tm.tm_hour;
    if (night_from > night_to) /* over midnight, e.g. 23 to 6 */
        return h >= night_from || h < night_to;
    return h >= night_from && h < night_to;
}

/*
 * The brightness command shares the panel's QSPI bus with the picture, which a
 * separate display task sends whenever LVGL redraws (on the home screen the glow
 * redraws ~10x a second). The driver does not keep the two apart: a command sent
 * during a frame is lost, and "on" would then leave the panel at its dimmest
 * level. So drawing is paused, the frame in flight is given time to finish, and
 * the command is sent twice; drawing stays paused when going dark.
 */
static void set_brightness_quietly(uint8_t level)
{
    lv_display_t *d = lv_display_get_default();
    disp_disable_update(d);
    tal_system_sleep(60); /* a full 466x466 frame takes ~25 ms */
    disp_set_backlight(d, level);
    tal_system_sleep(20);
    disp_set_backlight(d, level);
}

static void set_screen(bool on)
{
    if (on != screen_off)
        return; /* already so */
    lv_display_t *d = lv_display_get_default();
    screen_off = !on;
    if (on) {
        lv_obj_add_flag(wake_catcher, LV_OBJ_FLAG_HIDDEN);
        set_brightness_quietly(CONFIG_DISPLAY_DEFAULT_BRIGHTNESS);
        disp_enable_update(d);
        lv_obj_invalidate(lv_screen_active()); /* redraw everything missed while dark */
    } else {
        if (page != HOME)
            set_page(HOME); /* no settings page left open in the dark */
        lv_obj_remove_flag(wake_catcher, LV_OBJ_FLAG_HIDDEN);
        set_brightness_quietly(0); /* also stops drawing while dark */
    }
    apply_glow();
    PR_NOTICE("[DOORBELL] screen %s", on ? "on" : "off");
    report_settings(); /* the indoor unit shows whether it is lit */
}

/* Dark at night unless ringing, in a call, or touched within WAKE_MS; the
 * indoor unit can turn it on or off until the schedule changes. */
static void night_tick(void)
{
    static int was_night = -1;
    bool night = night_now();
    if (was_night != -1 && night != (bool)was_night)
        screen_force = SCREEN_AUTO; /* night started or ended: back to the schedule */
    was_night = night;
    uint32_t idle = lv_display_get_inactive_time(NULL);
    bool busy = is_ringing || talk_active();
    if (screen_force == SCREEN_FORCED_ON)
        set_screen(true);
    else if (screen_force == SCREEN_FORCED_OFF)
        set_screen(busy || (idle < WAKE_MS && idle < lv_tick_elaps(screen_forced_at))); /* touched since */
    else
        set_screen(!night || busy || idle < WAKE_MS);
}

/* Network status arrives from the net thread; picked up here on the LVGL thread. */
static void net_poll_cb(lv_timer_t *t)
{
    static net_status_t prev;
    static bool prev_talk;
    (void)t;
    net_get_status(&ns);
    update_clock();
    if (ns.stop_seq != prev.stop_seq && is_ringing) {
        PR_NOTICE("[DOORBELL] stopped from the indoor unit");
        end_ring();
        set_page(HOME);
    }
    if (ns.remote_seq != prev.remote_seq)
        apply_remote_settings();
    check_festival();
    if (ns.screen_cmd_seq != prev.screen_cmd_seq) {
        screen_force = ns.screen_cmd_on ? SCREEN_FORCED_ON : SCREEN_FORCED_OFF;
        screen_forced_at = lv_tick_get();
        PR_NOTICE("[DOORBELL] screen turned %s from the indoor unit", ns.screen_cmd_on ? "on" : "off");
    }
    night_tick();
    if (ns.talk_seq != prev.talk_seq) {
        if (ns.talk_on && ns.talk_host[0])
            talk_start(ns.talk_host, ns.talk_port);
        else
            talk_stop();
    }
    if (ns.listen_seq != prev.listen_seq) {
        if (ns.listen_on && ns.listen_host[0])
            listen_start(ns.listen_host, ns.listen_port, ns.listen_secs, false);
        else
            listen_stop();
    }
    if (talk_active() != prev_talk) { /* the date line says so while a call lasts */
        prev_talk = talk_active();
        clock_shown = -1;
        update_clock();
    }
    if (ns.scan_seq != prev.scan_seq || ns.scanning != prev.scanning)
        rebuild_ap_list();
    if (memcmp(&ns, &prev, sizeof(ns)) != 0)
        refresh_net();
    prev = ns;
}

/* ---------- event handlers ---------- */

/* The button sinks slightly while pressed. */
static void press_feedback(bool down)
{
    lv_image_set_scale(btn_img, down ? 244 : LV_SCALE_NONE);
    lv_image_set_scale(bell_img, down ? 244 : LV_SCALE_NONE);
}

/*
 * The whole home page is one touch target. LVGL's own long-press time is
 * far shorter than HOLD_MS (and CLICKED still fires after it), so the hold
 * is timed here from PRESSED.
 */
static void home_touch_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    uint32_t held = lv_tick_elaps(press_start);

    if (code == LV_EVENT_PRESSED) {
        press_start = lv_tick_get();
        press_feedback(true);
    } else if (code == LV_EVENT_PRESSING) {
        if (held >= HOLD_MS) {
            /* Swallow the rest of this touch so the release does not ring. */
            lv_indev_wait_release(lv_indev_active());
            lv_obj_add_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
            press_feedback(false);
            stop_ring();
            set_page(FIRST_SETTING);
        } else if (held >= 600) {
            lv_arc_set_value(hold_arc, (int32_t)((held - 600) * 100 / (HOLD_MS - 600)));
            lv_obj_remove_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
        lv_obj_add_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
        press_feedback(false);
        if (code == LV_EVENT_RELEASED && held < HOLD_MS)
            start_ring();
    }
}

static void goto_cb(lv_event_t *e)
{
    set_page((page_t)(intptr_t)lv_event_get_user_data(e));
}

/* Swipe left/right also moves between settings pages. */
static void gesture_cb(lv_event_t *e)
{
    (void)e;
    if (page < FIRST_SETTING || page > LAST_SETTING)
        return;
    lv_dir_t dir = lv_indev_get_gesture_dir(lv_indev_active());
    page_t target = page;
    if (dir == LV_DIR_LEFT && page < LAST_SETTING)
        target = page + 1;
    else if (dir == LV_DIR_RIGHT && page > FIRST_SETTING)
        target = page - 1;
    if (target != page) {
        lv_indev_wait_release(lv_indev_active()); /* no click on whatever was under the finger */
        set_page(target);
    }
}

static void theme_cb(lv_event_t *e)
{
    theme_idx = (uint32_t)(intptr_t)lv_event_get_user_data(e);
    bell_idx = themes[theme_idx].bell; /* each theme brings its matching bell colour */
    update_bell_art(true);
    apply_theme();
    refresh_values();
    save_config();
}

static void swatch_cb(lv_event_t *e)
{
    bell_idx = (uint32_t)(intptr_t)lv_event_get_user_data(e);
    update_bell_art(true);
    apply_theme();
    refresh_values();
    save_config();
}

/* Sound page: a new chime or volume plays once as a preview. */
static void chime_cb(lv_event_t *e)
{
    chime_idx = (uint32_t)(intptr_t)lv_event_get_user_data(e);
    use_chime(chime_idx); /* the next ring loads the festival chime again if one runs */
    sound_play(false);
    refresh_values();
    save_config();
}

/* Festivals page: the switches, and trying a look for a minute (also plays its chime). */
static void fest_look_cb(lv_event_t *e)
{
    fest_look_on = (intptr_t)lv_event_get_user_data(e) == 0;
    save_config();
    check_festival();
    refresh_values();
}

static void fest_chime_cb(lv_event_t *e)
{
    fest_chime_on = (intptr_t)lv_event_get_user_data(e) == 0;
    save_config();
    check_festival();
    refresh_values();
}

static void fest_try_cb(lv_event_t *e)
{
    intptr_t i = (intptr_t)lv_event_get_user_data(e);
    fest_trial = i < (intptr_t)FESTIVAL_COUNT ? &festivals[i] : NULL;
    fest_trial_end = lv_tick_get() + FEST_TRIAL_MS;
    check_festival();
    refresh_values();
    if (fest_trial && fest_tones && !is_ringing)
        sound_play(false);
}

static void repeat_cb(lv_event_t *e)
{
    chime_repeat = (intptr_t)lv_event_get_user_data(e) != 0;
    refresh_values();
    save_config();
}

static void volume_cb(lv_event_t *e)
{
    chime_volume = volumes[(intptr_t)lv_event_get_user_data(e)].volume;
    sound_set_volume(chime_volume);
    sound_stop();
    sound_play(false);
    refresh_values();
    save_config();
}

static void glow_cb(lv_event_t *e)
{
    (void)e;
    glow_on = !glow_on;
    apply_glow();
    refresh_values();
    save_config();
}

static void style_cb(lv_event_t *e)
{
    bell_style = (uint32_t)(intptr_t)lv_event_get_user_data(e);
    update_bell_art(false);
    apply_bell_style();
    refresh_values();
    save_config();
}

static void duration_cb(lv_event_t *e)
{
    ring_seconds = durations[(uint32_t)(intptr_t)lv_event_get_user_data(e)];
    refresh_values();
    save_config();
}

static void scan_cb(lv_event_t *e)
{
    (void)e;
    net_scan();
    set_page(WIFI_LIST);
}

static void open_entry(entry_mode_t mode, const char *ssid)
{
    entry_mode = mode;
    lv_textarea_set_text(entry_ta, "");
    if (mode == ENTRY_WIFI_PASSWORD) {
        lv_snprintf(entry_ssid, sizeof(entry_ssid), "%s", ssid);
        lv_label_set_text(entry_title, "Wi-Fi password");
        lv_label_set_text(entry_sub, entry_ssid);
        lv_textarea_set_max_length(entry_ta, NET_PSWD_MAX);
        lv_textarea_set_password_mode(entry_ta, true);
        lv_textarea_set_placeholder_text(entry_ta, "Password");
        lv_keyboard_set_mode(entry_kb, LV_KEYBOARD_MODE_TEXT_LOWER);
        lv_obj_remove_flag(entry_eye, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_label_set_text(entry_title, "Indoor unit address");
        lv_label_set_text(entry_sub, "IP address of the Pi's MQTT broker");
        lv_textarea_set_max_length(entry_ta, NET_HOST_MAX);
        lv_textarea_set_password_mode(entry_ta, false);
        lv_textarea_set_placeholder_text(entry_ta, "192.168.1.50");
        lv_textarea_set_text(entry_ta, ns.broker);
        lv_keyboard_set_mode(entry_kb, LV_KEYBOARD_MODE_NUMBER);
        lv_obj_add_flag(entry_eye, LV_OBJ_FLAG_HIDDEN);
    }
    lv_label_set_text(lv_obj_get_child(entry_eye, 0), LV_SYMBOL_EYE_OPEN);
    set_page(ENTRY);
}

static void ap_cb(lv_event_t *e)
{
    const net_ap_t *ap = &shown_aps[(uint32_t)(intptr_t)lv_event_get_user_data(e)];
    if (ap->secure) {
        open_entry(ENTRY_WIFI_PASSWORD, ap->ssid);
    } else {
        net_connect(ap->ssid, "");
        set_page(WIFI);
    }
}

static void eye_cb(lv_event_t *e)
{
    (void)e;
    bool hidden = !lv_textarea_get_password_mode(entry_ta);
    lv_textarea_set_password_mode(entry_ta, hidden);
    lv_label_set_text(lv_obj_get_child(entry_eye, 0), hidden ? LV_SYMBOL_EYE_OPEN : LV_SYMBOL_EYE_CLOSE);
}

static void keyboard_cb(lv_event_t *e)
{
    const char *text = lv_textarea_get_text(entry_ta);
    page_t back = entry_mode == ENTRY_WIFI_PASSWORD ? WIFI_LIST : CONTROLLER;

    if (lv_event_get_code(e) == LV_EVENT_CANCEL) {
        set_page(back);
        return;
    }
    if (entry_mode == ENTRY_WIFI_PASSWORD) {
        if (strlen(text) < 8) { /* WPA/WPA2 minimum */
            lv_label_set_text(entry_sub, "At least 8 characters");
            return;
        }
        net_connect(entry_ssid, text);
        set_page(WIFI);
    } else {
        if (text[0])
            net_set_broker(text);
        set_page(CONTROLLER);
    }
}

/* ---------- pages ---------- */

static void create_home(lv_obj_t *p)
{
    static const lv_point_precise_t slash_pts[] = {{0, 0}, {26, 22}};
    /* Sound waves either side of the button (centre BTN_CY), hidden until it rings. */
    static const struct {
        int16_t size, start, end;
    } waves[] = {{280, 155, 205}, {340, 155, 205}, {280, 335, 25}, {340, 335, 25}};

    lv_obj_add_flag(p, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_PRESSED, NULL);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_PRESSING, NULL);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_RELEASED, NULL);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_PRESS_LOST, NULL);

    /* Created first so they sit behind everything else on the page. */
    for (int i = 0; i < 3; i++) {
        lv_obj_t *g = lv_image_create(p);
        lv_image_set_src(g, &glow_dsc);
        lv_obj_remove_flag(g, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_style_image_recolor(g, lv_color_hex(glow_colors[i]), LV_PART_MAIN);
        lv_obj_set_style_image_recolor_opa(g, LV_OPA_COVER, LV_PART_MAIN);
        glow_blobs[i] = g;
    }
    glow_timer = lv_timer_create(glow_tick, GLOW_IDLE_MS, NULL);
    lv_timer_pause(glow_timer);

    wifi_icon = add_text(p, &lv_font_montserrat_22, 50, LV_SYMBOL_WIFI);
    lv_obj_add_style(wifi_icon, &st_muted, LV_PART_MAIN);
    wifi_slash = lv_line_create(p);
    lv_line_set_points(wifi_slash, slash_pts, 2);
    lv_obj_add_style(wifi_slash, &st_muted, LV_PART_MAIN);
    lv_obj_set_style_line_width(wifi_slash, 3, LV_PART_MAIN);
    lv_obj_set_style_line_rounded(wifi_slash, true, LV_PART_MAIN);
    lv_obj_align(wifi_slash, LV_ALIGN_TOP_MID, 0, 51);

    for (uint32_t i = 0; i < 4; i++) {
        lv_obj_t *a = lv_arc_create(p);
        lv_obj_remove_style_all(a);
        lv_obj_add_style(a, &st_wave, LV_PART_MAIN);
        lv_obj_remove_flag(a, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_flag(a, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_size(a, waves[i].size, waves[i].size);
        lv_arc_set_bg_angles(a, waves[i].start, waves[i].end);
        lv_arc_set_value(a, 0);
        lv_obj_align(a, LV_ALIGN_TOP_MID, 0, BTN_CY - waves[i].size / 2);
        ring_waves[i] = a;
    }

    halo = add_box(p, (int32_t)(2 * BTN_R) + 4, (int32_t)(2 * BTN_R) + 4);
    lv_obj_add_style(halo, &st_halo, LV_PART_MAIN);
    lv_obj_align(halo, LV_ALIGN_TOP_MID, 0, BTN_CY - (int32_t)BTN_R - 2);

    btn_img = lv_image_create(p);
    lv_image_set_src(btn_img, &btn_dsc);
    lv_image_set_antialias(btn_img, true);
    lv_obj_remove_flag(btn_img, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(btn_img, LV_ALIGN_TOP_MID, 0, BTN_CY - BTN_SIZE / 2);

    bell_img = lv_image_create(p);
    lv_image_set_src(bell_img, &glyph_dsc);
    lv_image_set_pivot(bell_img, GLYPH_W / 2, GLYPH_PIVOT);
    lv_image_set_antialias(bell_img, true);
    lv_obj_remove_flag(bell_img, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(bell_img, LV_ALIGN_TOP_MID, 0, BTN_CY - GLYPH_H / 2 - 4);

    /* Filled in by update_clock() once NTP has answered; never a made-up time. */
    home_clock = add_text(p, &lv_font_montserrat_48, 330, "--:--");
    home_date = add_muted(p, &lv_font_montserrat_16, 388, "Waiting for network time");

    /* Hold-to-open-settings progress, traced around the screen edge. */
    hold_arc = lv_arc_create(p);
    lv_obj_remove_style_all(hold_arc);
    lv_obj_add_style(hold_arc, &st_progress, LV_PART_INDICATOR);
    lv_obj_remove_flag(hold_arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_size(hold_arc, SCREEN_SIZE - 12, SCREEN_SIZE - 12);
    lv_arc_set_rotation(hold_arc, 270);
    lv_arc_set_bg_angles(hold_arc, 0, 360);
    lv_arc_set_value(hold_arc, 0);
    lv_obj_center(hold_arc);
}

/* Title, prev/next arrows, page dots and Done: the frame of every settings page. */
static void add_settings_frame(lv_obj_t *p, page_t self, const char *title)
{
    add_text(p, &lv_font_montserrat_24, 42, title);

    for (int dir = -1; dir <= 1; dir += 2) {
        page_t target = self + dir;
        if (target < FIRST_SETTING || target > LAST_SETTING)
            continue;
        lv_obj_t *b = add_card(p, 48, 48, goto_cb, (void *)(intptr_t)target);
        lv_obj_set_style_radius(b, LV_RADIUS_CIRCLE, LV_PART_MAIN);
        lv_obj_align(b, dir < 0 ? LV_ALIGN_LEFT_MID : LV_ALIGN_RIGHT_MID, dir < 0 ? 14 : -14, 0);
        lv_obj_t *l = lv_label_create(b);
        lv_obj_add_style(l, &st_accent_text, LV_PART_MAIN);
        lv_label_set_text(l, dir < 0 ? LV_SYMBOL_LEFT : LV_SYMBOL_RIGHT);
        lv_obj_center(l);
    }

    int32_t count = LAST_SETTING - FIRST_SETTING + 1;
    for (int32_t i = 0; i < count; i++) {
        bool active = FIRST_SETTING + i == (int32_t)self;
        lv_obj_t *d = add_box(p, active ? 22 : 8, 8);
        lv_obj_add_style(d, active ? &st_accent : &st_dot, LV_PART_MAIN);
        lv_obj_align(d, LV_ALIGN_TOP_MID, (i * 2 - (count - 1)) * 10, DOTS_Y);
    }
    add_pill(p, 140, DONE_Y, LV_SYMBOL_OK "  Done", goto_cb, (void *)(intptr_t)HOME);
}

/* Icon, subtitle, status card with a coloured dot, and one action button. */
static void create_status_page(lv_obj_t *p, page_t self, const char *icon, const char *title, status_view_t *v,
                               const char *action, lv_event_cb_t cb)
{
    add_settings_frame(p, self, title);
    lv_obj_t *i = add_text(p, &lv_font_montserrat_48, 84, icon);
    lv_obj_add_style(i, &st_accent_text, LV_PART_MAIN);
    v->sub = add_muted(p, &lv_font_montserrat_16, 146, "");
    clip_label(v->sub, 280);

    lv_obj_t *card = add_card(p, 280, 56, NULL, NULL);
    lv_obj_align(card, LV_ALIGN_TOP_MID, 0, 178);
    v->dot = add_box(card, 14, 14);
    lv_obj_set_style_radius(v->dot, LV_RADIUS_CIRCLE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(v->dot, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_align(v->dot, LV_ALIGN_LEFT_MID, 22, 0);
    v->state = lv_label_create(card);
    lv_obj_set_style_text_font(v->state, &lv_font_montserrat_16, LV_PART_MAIN);
    lv_label_set_long_mode(v->state, LV_LABEL_LONG_DOT);
    lv_obj_set_width(v->state, 214);
    lv_obj_align(v->state, LV_ALIGN_LEFT_MID, 50, 0);

    add_pill(p, 200, 258, action, cb, NULL);
}

static void broker_cb(lv_event_t *e)
{
    (void)e;
    open_entry(ENTRY_BROKER, NULL);
}

static void create_wifi_list(lv_obj_t *p)
{
    add_text(p, &lv_font_montserrat_24, 42, "Choose network");

    ap_list = add_box(p, 300, 240);
    lv_obj_align(ap_list, LV_ALIGN_TOP_MID, 0, 84);
    lv_obj_add_flag(ap_list, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(ap_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(ap_list, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_flex_flow(ap_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(ap_list, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(ap_list, 6, LV_PART_MAIN);
    ap_msg = add_muted(p, &lv_font_montserrat_16, 190, "Scanning...");

    lv_obj_t *b = add_pill(p, 120, 340, LV_SYMBOL_LEFT "  Back", goto_cb, (void *)(intptr_t)WIFI);
    lv_obj_align(b, LV_ALIGN_TOP_MID, -66, 340);
    b = add_pill(p, 120, 340, LV_SYMBOL_REFRESH "  Rescan", scan_cb, NULL);
    lv_obj_align(b, LV_ALIGN_TOP_MID, 66, 340);
}

/*
 * Text entry with an on-screen keyboard sized for the round panel: 380x196
 * with its bottom corners just inside the circle. The keyboard's close key
 * goes back, its OK key submits.
 */
static void create_entry(lv_obj_t *p)
{
    entry_title = add_text(p, &lv_font_montserrat_22, 34, "");
    entry_sub = add_muted(p, &lv_font_montserrat_14, 66, "");
    clip_label(entry_sub, 280);

    entry_ta = lv_textarea_create(p);
    lv_obj_add_style(entry_ta, &st_card, LV_PART_MAIN);
    lv_obj_add_style(entry_ta, &st_text, LV_PART_MAIN);
    lv_obj_set_style_text_font(entry_ta, &lv_font_montserrat_16, LV_PART_MAIN);
    lv_obj_set_style_pad_hor(entry_ta, 16, LV_PART_MAIN);
    lv_obj_set_style_pad_ver(entry_ta, 11, LV_PART_MAIN);
    lv_textarea_set_one_line(entry_ta, true);
    lv_obj_set_size(entry_ta, 250, 44);
    lv_obj_align(entry_ta, LV_ALIGN_TOP_MID, -26, 98);

    entry_eye = add_card(p, 44, 44, eye_cb, NULL);
    lv_obj_set_style_radius(entry_eye, LV_RADIUS_CIRCLE, LV_PART_MAIN);
    lv_obj_align(entry_eye, LV_ALIGN_TOP_MID, 130, 98);
    lv_obj_t *l = lv_label_create(entry_eye);
    lv_obj_add_style(l, &st_accent_text, LV_PART_MAIN);
    lv_obj_center(l);

    entry_kb = lv_keyboard_create(p);
    lv_obj_remove_style_all(entry_kb);
    lv_obj_set_size(entry_kb, 380, 196);
    lv_obj_align(entry_kb, LV_ALIGN_TOP_MID, 0, 156);
    lv_obj_set_style_pad_all(entry_kb, 2, LV_PART_MAIN);
    lv_obj_set_style_pad_row(entry_kb, 5, LV_PART_MAIN);
    lv_obj_set_style_pad_column(entry_kb, 4, LV_PART_MAIN);
    lv_obj_add_style(entry_kb, &st_card, LV_PART_ITEMS);
    lv_obj_add_style(entry_kb, &st_card_pressed, LV_PART_ITEMS | LV_STATE_PRESSED);
    lv_obj_add_style(entry_kb, &st_accent, LV_PART_ITEMS | LV_STATE_CHECKED);
    lv_obj_set_style_radius(entry_kb, 10, LV_PART_ITEMS);
    lv_obj_set_style_radius(entry_kb, 10, LV_PART_ITEMS | LV_STATE_CHECKED);
    lv_obj_set_style_text_font(entry_kb, &lv_font_montserrat_16, LV_PART_ITEMS);
    lv_keyboard_set_textarea(entry_kb, entry_ta);
    lv_obj_add_event_cb(entry_kb, keyboard_cb, LV_EVENT_READY, NULL);
    lv_obj_add_event_cb(entry_kb, keyboard_cb, LV_EVENT_CANCEL, NULL);
}

static void create_appearance(lv_obj_t *p)
{
    add_settings_frame(p, APPEARANCE, "Appearance");
    add_muted(p, &lv_font_montserrat_14, 78, "Theme");
    for (uint32_t i = 0; i < THEME_COUNT; i++) {
        lv_obj_t *card = add_card(p, 132, 104, theme_cb, (void *)(intptr_t)i);
        lv_obj_align(card, LV_ALIGN_TOP_MID, i == 0 ? -71 : 71, 100);

        /* Fixed-colour preview so both themes are visible whichever is active. */
        lv_obj_t *preview = add_box(card, 52, 52);
        lv_obj_set_style_radius(preview, LV_RADIUS_CIRCLE, LV_PART_MAIN);
        lv_obj_set_style_bg_color(preview, lv_color_hex(themes[i].bg_top), LV_PART_MAIN);
        lv_obj_set_style_bg_grad_color(preview, lv_color_hex(themes[i].bg_bottom), LV_PART_MAIN);
        lv_obj_set_style_bg_grad_dir(preview, LV_GRAD_DIR_VER, LV_PART_MAIN);
        lv_obj_set_style_bg_opa(preview, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_set_style_border_color(preview, lv_color_hex(themes[i].card_border), LV_PART_MAIN);
        lv_obj_set_style_border_width(preview, 2, LV_PART_MAIN);
        lv_obj_align(preview, LV_ALIGN_TOP_MID, 0, 12);
        lv_obj_t *accent = add_box(preview, 20, 20);
        lv_obj_set_style_radius(accent, LV_RADIUS_CIRCLE, LV_PART_MAIN);
        lv_obj_set_style_bg_color(accent, lv_color_hex(themes[i].accent), LV_PART_MAIN);
        lv_obj_set_style_bg_opa(accent, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_center(accent);

        lv_obj_t *name = lv_label_create(card);
        lv_obj_set_style_text_font(name, &lv_font_montserrat_14, LV_PART_MAIN);
        lv_label_set_text(name, themes[i].name);
        lv_obj_align(name, LV_ALIGN_BOTTOM_MID, 0, -10);
        theme_cards[i] = card;
    }

    add_muted(p, &lv_font_montserrat_14, 218, "Bell colour");
    for (uint32_t i = 0; i < BELL_COLOR_COUNT; i++) {
        lv_obj_t *s = add_box(p, 44, 44);
        lv_obj_set_style_radius(s, LV_RADIUS_CIRCLE, LV_PART_MAIN);
        lv_obj_set_style_bg_color(s, lv_color_hex(bell_colors[i].color), LV_PART_MAIN);
        lv_obj_set_style_bg_opa(s, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_add_style(s, &st_swatch_checked, LV_PART_MAIN | LV_STATE_CHECKED);
        lv_obj_add_flag(s, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(s, swatch_cb, LV_EVENT_CLICKED, (void *)(intptr_t)i);
        lv_obj_align(s, LV_ALIGN_TOP_MID, -90 + (int32_t)i * 60, 244);
        swatches[i] = s;
    }

    /* glow on/off: one toggle card, its label says the current state */
    glow_card = add_card(p, 170, 38, glow_cb, NULL);
    lv_obj_align(glow_card, LV_ALIGN_TOP_MID, 0, 300);
    lv_obj_t *l = lv_label_create(glow_card);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_14, LV_PART_MAIN);
    lv_obj_center(l);
}

/* Small text card for the Sound page. */
static lv_obj_t *sound_card(lv_obj_t *p, int32_t w, int32_t x, int32_t y, const char *text, lv_event_cb_t cb,
                            intptr_t value)
{
    lv_obj_t *card = add_card(p, w, 36, cb, (void *)value);
    lv_obj_align(card, LV_ALIGN_TOP_MID, x, y);
    lv_obj_t *l = lv_label_create(card);
    lv_obj_set_style_text_font(l, &lv_font_montserrat_14, LV_PART_MAIN);
    lv_label_set_text(l, text);
    lv_obj_center(l);
    return card;
}

/* Chime (2 columns), once / whole ring, and volume; all kept inside the circle. */
static void create_sound_page(lv_obj_t *p)
{
    add_settings_frame(p, SOUND, "Sound");
    for (uint32_t i = 0; i < CHIME_COUNT; i++) {
        bool alone = i == CHIME_COUNT - 1 && CHIME_COUNT % 2; /* odd last one is centred */
        chime_cards[i] = sound_card(p, 130, alone ? 0 : (i % 2 ? 69 : -69), 78 + (int32_t)(i / 2) * 40,
                                    chime_names[i], chime_cb, (intptr_t)i);
    }
    add_muted(p, &lv_font_montserrat_14, 202, "Plays");
    repeat_cards[0] = sound_card(p, 130, -69, 222, "Once", repeat_cb, 0);
    repeat_cards[1] = sound_card(p, 130, 69, 222, "Whole ring", repeat_cb, 1);
    add_muted(p, &lv_font_montserrat_14, 266, "Volume");
    for (uint32_t i = 0; i < VOLUME_COUNT; i++)
        volume_cards[i] = sound_card(p, 86, ((int32_t)i - 1) * 92, 286, volumes[i].name, volume_cb, (intptr_t)i);
}

/* Festive look and chime switches, what runs now, and a one-minute trial of each look. */
static void create_festival_page(lv_obj_t *p)
{
    add_settings_frame(p, FESTIVAL, "Festivals");
    fest_look_cards[0] = sound_card(p, 130, -69, 78, "Festive look", fest_look_cb, 0);
    fest_look_cards[1] = sound_card(p, 130, 69, 78, "My own look", fest_look_cb, 1);
    fest_chime_cards[0] = sound_card(p, 130, -69, 118, "Festive chime", fest_chime_cb, 0);
    fest_chime_cards[1] = sound_card(p, 130, 69, 118, "My own chime", fest_chime_cb, 1);
    fest_now = add_text(p, &lv_font_montserrat_14, 166, "");
    lv_obj_add_style(fest_now, &st_accent_text, LV_PART_MAIN);
    add_muted(p, &lv_font_montserrat_14, 200, "Try for a minute");
    for (uint32_t i = 0; i < FESTIVAL_COUNT; i++)
        sound_card(p, 100, ((int32_t)i - 1) * 106, 220, festivals[i].theme.name, fest_try_cb, (intptr_t)i);
    sound_card(p, 120, 0, 262, "Stop trying", fest_try_cb, (intptr_t)FESTIVAL_COUNT);
}

/* Bell style picker: 3 x 2 cards, each a thumbnail drawn in the current bell colour. */
static void create_bell_page(lv_obj_t *p)
{
    add_settings_frame(p, BELL, "Bell");
    for (uint32_t i = 0; i < STYLE_COUNT; i++) {
        lv_obj_t *card = add_card(p, 92, 98, style_cb, (void *)(intptr_t)i);
        lv_obj_align(card, LV_ALIGN_TOP_MID, ((int32_t)(i % 3) - 1) * 100, 80 + (int32_t)(i / 3) * 106);
        lv_obj_t *img = lv_image_create(card);
        lv_image_set_src(img, &thumb_dsc[i]);
        lv_obj_remove_flag(img, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_align(img, LV_ALIGN_TOP_MID, 0, 6);
        lv_obj_t *name = lv_label_create(card);
        lv_obj_set_style_text_font(name, &lv_font_montserrat_14, LV_PART_MAIN);
        lv_label_set_text(name, style_names[i]);
        lv_obj_align(name, LV_ALIGN_BOTTOM_MID, 0, -6);
        style_cards[i] = card;
        style_thumbs[i] = img;
    }
}

static void create_duration(lv_obj_t *p)
{
    add_settings_frame(p, DURATION, "Ring Duration");
    add_muted(p, &lv_font_montserrat_16, 80, "How long the bell rings");
    for (uint32_t i = 0; i < DURATION_COUNT; i++) {
        lv_obj_t *b = add_card(p, 88, 66, duration_cb, (void *)(intptr_t)i);
        lv_obj_add_style(b, &st_accent, LV_PART_MAIN | LV_STATE_CHECKED);
        lv_obj_set_style_radius(b, 18, LV_PART_MAIN | LV_STATE_CHECKED);
        /* Rows of 3 + 2, each row centred. */
        int32_t row = i / 3, col = i % 3, in_row = row == 0 ? 3 : (int32_t)DURATION_COUNT - 3;
        lv_obj_align(b, LV_ALIGN_TOP_MID, (col * 2 - (in_row - 1)) * 50, 118 + row * 76);

        lv_obj_t *n = lv_label_create(b);
        lv_obj_set_style_text_font(n, &lv_font_montserrat_24, LV_PART_MAIN);
        lv_label_set_text_fmt(n, "%u", (unsigned)durations[i]);
        lv_obj_align(n, LV_ALIGN_TOP_MID, 0, 8);
        lv_obj_t *u = lv_label_create(b);
        lv_obj_set_style_text_font(u, &lv_font_montserrat_14, LV_PART_MAIN);
        lv_label_set_text(u, "seconds");
        lv_obj_align(u, LV_ALIGN_BOTTOM_MID, 0, -8);
        duration_btns[i] = b;
    }
    add_note(p, 284, "The indoor unit rings for the same time unless stopped there");
}

static void create_ui(void)
{
    lv_obj_t *scr = lv_screen_active();

    lv_display_set_rotation(lv_display_get_default(), SCREEN_ROTATION); /* round panel: same size either way */
    init_styles();
    init_bell_art();
    update_bell_art(true);

    /* Nothing scrolls; gestures reach the screen from any page. */
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(scr, gesture_cb, LV_EVENT_GESTURE, NULL);
    for (uint32_t i = 0; i < PAGE_COUNT; i++)
        pages[i] = add_page();

    create_home(pages[HOME]);
    create_status_page(pages[WIFI], WIFI, LV_SYMBOL_WIFI, "Wi-Fi", &wifi_view, LV_SYMBOL_LIST "  Choose network",
                       scan_cb);
    create_appearance(pages[APPEARANCE]);
    create_bell_page(pages[BELL]);
    create_sound_page(pages[SOUND]);
    create_festival_page(pages[FESTIVAL]);
    create_duration(pages[DURATION]);
    create_status_page(pages[CONTROLLER], CONTROLLER, LV_SYMBOL_HOME, "Indoor Unit", &ctrl_view,
                       LV_SYMBOL_EDIT "  Set address", broker_cb);
    create_wifi_list(pages[WIFI_LIST]);
    create_entry(pages[ENTRY]);

    /* Over every page while the screen is off: takes the waking touch, so it never rings. */
    wake_catcher = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(wake_catcher);
    lv_obj_set_size(wake_catcher, LV_PCT(100), LV_PCT(100));
    lv_obj_add_flag(wake_catcher, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_HIDDEN);

    net_get_status(&ns);
    apply_theme();
    set_page(HOME);
    apply_bell_style();
    lv_timer_create(net_poll_cb, 250, NULL);
}

void user_main(void)
{
    tal_log_init(TAL_LOG_LEVEL_DEBUG, 4096, (TAL_LOG_OUTPUT_CB)tkl_log_output);
    /* Encrypts the KV store (saved Wi-Fi password, broker, UI settings). */
    tal_kv_init(&(tal_kv_cfg_t){
        .seed = "db7Kq2xVn4Rt8LwP",
        .key = "Hs3mYc9TfE6uJa1Z",
    });
    tal_sw_timer_init();
    tal_workq_init();
    tal_time_service_init();
    board_register_hardware();
    load_config();
    sound_init(chime_idx, chime_volume); /* after board_register_hardware() and the saved settings */
    loaded_chime = chime_idx;
    talk_init();
    listen_init();
    net_start();
    report_settings();

    lv_vendor_init(DISPLAY_NAME);
    lv_vendor_disp_lock();
    create_ui();
    lv_vendor_disp_unlock();
    lv_vendor_start(5, 1024 * 8);
}
#if OPERATING_SYSTEM == SYSTEM_LINUX
int main(int argc,char **argv){(void)argc;(void)argv;user_main();for(;;)tal_system_sleep(500);return 0;}
#else
static THREAD_HANDLE app_thread=NULL;
static void app_task(void *arg){(void)arg;user_main();tal_thread_delete(app_thread);app_thread=NULL;}
void tuya_app_main(void){THREAD_CFG_T c;memset(&c,0,sizeof(c));c.stackDepth=4096;c.priority=THREAD_PRIO_1;c.thrdname="doorbell";tal_thread_create_and_start(&app_thread,NULL,NULL,app_task,NULL,&c);}
#endif
