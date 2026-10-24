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
#include "board_com_api.h"
#include "doorbell_net.h"
#include <math.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>

#ifndef DISPLAY_NAME
#define DISPLAY_NAME "display"
#endif

#define SCREEN_SIZE 466
#define HOLD_MS     5000 /* home screen long press that opens settings */
#define DONE_Y      374  /* bottom "Done" pill on settings pages */
#define DOTS_Y      346  /* page indicator on settings pages */
#define KV_UI       "db_ui"

/* Settings pages are consecutive so prev/next is just -1/+1. */
typedef enum { HOME, WIFI, APPEARANCE, DURATION, CONTROLLER, WIFI_LIST, ENTRY, PAGE_COUNT } page_t;
#define FIRST_SETTING WIFI
#define LAST_SETTING  CONTROLLER

typedef enum { ENTRY_WIFI_PASSWORD, ENTRY_BROKER } entry_mode_t;

typedef struct {
    const char *name;
    uint32_t bg_top, bg_bottom, text, muted, card, card_border, pressed, accent, on_accent, bell;
} theme_t;

static const theme_t themes[] = {
    {"Clean & Light", 0xFFFFFF, 0xDCEBFA, 0x173B5C, 0x5B7894, 0xFFFFFF, 0xC9DCEF, 0xE3EEF9, 0x2F80ED, 0xFFFFFF, 0},
    /* Near-black background: AMOLED pixels are off, which also saves power. */
    {"Midnight & Gold", 0x1B2533, 0x000000, 0xF2F5F8, 0x9AA8B8, 0x1C2735, 0x33445A, 0x2A3A4F, 0xD4A537, 0x14100A, 1},
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

static page_t page = HOME;
static lv_obj_t *pages[PAGE_COUNT];
static lv_timer_t *ring_timer;
static bool is_ringing;
static uint32_t press_start;
static net_status_t ns; /* latest network status, refreshed by net_poll_cb */

/* Shared styles: switching theme only rewrites these and refreshes. */
static lv_style_t st_screen, st_text, st_muted, st_accent_text, st_card, st_card_pressed, st_card_checked;
static lv_style_t st_accent, st_accent_pressed, st_wave, st_progress, st_dot, st_swatch_checked;

static lv_obj_t *bell_img;
static lv_obj_t *home_clock, *home_date;
static lv_obj_t *hold_arc;
static lv_obj_t *wifi_icon;
static lv_obj_t *wifi_slash;
static lv_obj_t *ring_waves[4];
static lv_obj_t *theme_cards[THEME_COUNT];
static lv_obj_t *swatches[BELL_COLOR_COUNT];
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

static void save_config(void)
{
    uint8_t v[3] = {(uint8_t)theme_idx, (uint8_t)bell_idx, (uint8_t)ring_seconds};
    if (tal_kv_set(KV_UI, v, sizeof(v)) != OPRT_OK)
        PR_ERR("[DOORBELL] saving settings failed");
    net_report_settings(theme_idx, bell_idx, ring_seconds); /* keeps the indoor settings page in step */
}

static void load_config(void)
{
    uint8_t *v = NULL;
    size_t len = 0;
    if (tal_kv_get(KV_UI, &v, &len) != OPRT_OK || !v)
        return;
    if (len == 3 && v[0] < THEME_COUNT && v[1] < BELL_COLOR_COUNT) {
        theme_idx = v[0];
        bell_idx = v[1];
        for (uint32_t i = 0; i < DURATION_COUNT; i++)
            if (durations[i] == v[2])
                ring_seconds = v[2];
    }
    tal_kv_free(v);
}

/* ---------- bell artwork ----------
 * A shaded bell drawn per pixel into an ARGB8888 buffer: knob ring, dome,
 * flared body, rim and clapper, each lit as a 3D surface with a soft
 * specular highlight, anti-aliased with 3x3 supersampling. Rendered once at
 * start-up and again only when the bell colour changes.
 */
#define BELL_W     216
#define BELL_H     236
#define BELL_CX    108.0f
#define BELL_PIVOT 22 /* knob centre: the bell swings around it */
#define BELL_SS    3  /* supersampling per axis */

static lv_image_dsc_t bell_dsc;
static uint8_t *bell_buf;
/* Body half-width and its slope dr/dy for each sample row (y is constant along a row). */
static float body_w[BELL_H * BELL_SS], body_slope[BELL_H * BELL_SS];

/*
 * Body below the dome: slight waist, then a flare towards the rim. The slope
 * is zero where it meets the dome, so the shading has no crease there.
 */
static void init_body_profile(void)
{
    for (int r = 0; r < BELL_H * BELL_SS; r++) {
        float s = ((r + 0.5f) / BELL_SS - 84.0f) / 102.0f;
        body_w[r] = 62.0f - 24.0f * s * s + 60.0f * s * s * s;
        body_slope[r] = (-48.0f * s + 180.0f * s * s) / 102.0f;
    }
}

/* Returns the topmost part covering sample (x, row) and its surface normal, or 0 if none. */
static int bell_hit(float x, int row, float n[3])
{
    float y = (row + 0.5f) / BELL_SS;
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
    /* body: surface of revolution, normal = (cos, -dr/dy, sin) */
    if (y >= 84.0f && y <= 186.0f) {
        float w = body_w[row];
        if (fabsf(dx) <= w) {
            float u = dx / w;
            n[0] = u;
            n[1] = -body_slope[row];
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

static void render_bell(uint32_t color)
{
    /* Light from the upper left, viewer straight ahead. */
    const float l[3] = {-0.45f, -0.6f, 0.66f};
    const float hl = sqrtf(l[0] * l[0] + l[1] * l[1] + (l[2] + 1.0f) * (l[2] + 1.0f));
    const float h[3] = {l[0] / hl, l[1] / hl, (l[2] + 1.0f) / hl}; /* Blinn half vector */
    float base[3] = {(float)((color >> 16) & 0xFF), (float)((color >> 8) & 0xFF), (float)(color & 0xFF)};

    for (int py = 0; py < BELL_H; py++) {
        uint8_t *px = bell_buf + py * BELL_W * 4;
        for (int x = 0; x < BELL_W; x++, px += 4) {
            float acc[3] = {0, 0, 0};
            int hits = 0;
            for (int sy = 0; sy < BELL_SS; sy++) {
                for (int sx = 0; sx < BELL_SS; sx++) {
                    float n[3];
                    int part = bell_hit(x + (sx + 0.5f) / BELL_SS, py * BELL_SS + sy, n);
                    if (!part)
                        continue;
                    float nl = sqrtf(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
                    float diff = fmaxf(0.0f, (n[0] * l[0] + n[1] * l[1] + n[2] * l[2]) / nl);
                    float spec = fmaxf(0.0f, (n[0] * h[0] + n[1] * h[1] + n[2] * h[2]) / nl);
                    spec *= spec; /* ^32 */
                    spec *= spec;
                    spec *= spec;
                    spec *= spec;
                    spec *= spec;
                    /* Rim and knob catch a little more light; the clapper sits in shadow. */
                    float amb = part == 3 ? 0.25f : 0.38f, kd = part == 1 || part == 4 ? 0.8f : 0.7f;
                    for (int c = 0; c < 3; c++)
                        acc[c] += fminf(255.0f, base[c] * (amb + kd * diff) + 255.0f * 0.6f * spec);
                    hits++;
                }
            }
            /* lv_color32_t byte order: blue, green, red, alpha (straight alpha). */
            px[0] = hits ? (uint8_t)(acc[2] / hits) : 0;
            px[1] = hits ? (uint8_t)(acc[1] / hits) : 0;
            px[2] = hits ? (uint8_t)(acc[0] / hits) : 0;
            px[3] = (uint8_t)(hits * 255 / (BELL_SS * BELL_SS));
        }
    }
}

static void update_bell_art(void)
{
    render_bell(bell_colors[bell_idx].color);
    lv_image_cache_drop(&bell_dsc);
    if (bell_img)
        lv_obj_invalidate(bell_img);
}

static void init_bell_art(void)
{
    bell_buf = lv_malloc(BELL_W * BELL_H * 4);
    LV_ASSERT_MALLOC(bell_buf);
    memset(&bell_dsc, 0, sizeof(bell_dsc));
    bell_dsc.header.magic = LV_IMAGE_HEADER_MAGIC;
    bell_dsc.header.cf = LV_COLOR_FORMAT_ARGB8888;
    bell_dsc.header.w = BELL_W;
    bell_dsc.header.h = BELL_H;
    bell_dsc.header.stride = BELL_W * 4;
    bell_dsc.data_size = BELL_W * BELL_H * 4;
    bell_dsc.data = bell_buf;
    init_body_profile();
}

/* ---------- theme ---------- */

static void apply_theme(void)
{
    const theme_t *t = &themes[theme_idx];

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
    lv_style_set_arc_color(&st_wave, lv_color_hex(bell_colors[bell_idx].color));
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
    for (uint32_t i = 0; i < DURATION_COUNT; i++)
        lv_obj_set_state(duration_btns[i], LV_STATE_CHECKED, durations[i] == ring_seconds);
    refresh_net();
}

static void set_page(page_t p)
{
    lv_obj_add_flag(pages[page], LV_OBJ_FLAG_HIDDEN);
    page = p;
    refresh_values();
    lv_obj_remove_flag(pages[page], LV_OBJ_FLAG_HIDDEN);
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

static void set_ring_animation(bool run)
{
    lv_anim_t a;

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
    set_ring_animation(true);
    ring_timer = lv_timer_create(timeout_cb, ring_seconds * 1000, NULL);
    lv_timer_set_repeat_count(ring_timer, 1);
}

/* Local time once NTP has set the system clock; placeholders until then. */
static void update_clock(void)
{
    static const char *const days[] = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};
    static const char *const months[] = {"January", "February", "March",     "April",   "May",      "June",
                                         "July",    "August",   "September", "October", "November", "December"};
    static int shown = -1; /* minute of the day on screen */

    if (!ns.time_synced)
        return;
    TIME_T t = tal_time_get_posix() + DOORBELL_UTC_OFFSET_S;
    POSIX_TM_S tm;
    tal_time_gmtime_r(&t, &tm);
    if (tm.tm_hour * 60 + tm.tm_min == shown)
        return;
    shown = tm.tm_hour * 60 + tm.tm_min;
    int h12 = tm.tm_hour % 12 ? tm.tm_hour % 12 : 12;
    lv_label_set_text_fmt(home_clock, "%d:%02d %s", h12, tm.tm_min, tm.tm_hour < 12 ? "AM" : "PM");
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
    PR_NOTICE("[DOORBELL] settings from indoor unit: theme %u, bell %u, ring %us", (unsigned)theme_idx,
              (unsigned)bell_idx, (unsigned)ring_seconds);
    if (art)
        update_bell_art();
    apply_theme();
    refresh_values();
    save_config();
}

/* Network status arrives from the net thread; picked up here on the LVGL thread. */
static void net_poll_cb(lv_timer_t *t)
{
    static net_status_t prev;
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
    if (ns.scan_seq != prev.scan_seq || ns.scanning != prev.scanning)
        rebuild_ap_list();
    if (memcmp(&ns, &prev, sizeof(ns)) != 0)
        refresh_net();
    prev = ns;
}

/* ---------- event handlers ---------- */

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
        lv_image_set_scale(bell_img, 244); /* small press-down feedback */
    } else if (code == LV_EVENT_PRESSING) {
        if (held >= HOLD_MS) {
            /* Swallow the rest of this touch so the release does not ring. */
            lv_indev_wait_release(lv_indev_active());
            lv_obj_add_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
            lv_image_set_scale(bell_img, LV_SCALE_NONE);
            stop_ring();
            set_page(FIRST_SETTING);
        } else if (held >= 600) {
            lv_arc_set_value(hold_arc, (int32_t)((held - 600) * 100 / (HOLD_MS - 600)));
            lv_obj_remove_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
        }
    } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
        lv_obj_add_flag(hold_arc, LV_OBJ_FLAG_HIDDEN);
        lv_image_set_scale(bell_img, LV_SCALE_NONE);
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
    update_bell_art();
    apply_theme();
    refresh_values();
    save_config();
}

static void swatch_cb(lv_event_t *e)
{
    bell_idx = (uint32_t)(intptr_t)lv_event_get_user_data(e);
    update_bell_art();
    apply_theme();
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
    /* Sound waves either side of the bell's dome (centre y=192), hidden until it rings. */
    static const struct {
        int16_t size, start, end;
    } waves[] = {{280, 155, 205}, {340, 155, 205}, {280, 335, 25}, {340, 335, 25}};

    lv_obj_add_flag(p, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_PRESSED, NULL);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_PRESSING, NULL);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_RELEASED, NULL);
    lv_obj_add_event_cb(p, home_touch_cb, LV_EVENT_PRESS_LOST, NULL);

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
        lv_obj_align(a, LV_ALIGN_TOP_MID, 0, 192 - waves[i].size / 2);
        ring_waves[i] = a;
    }

    bell_img = lv_image_create(p);
    lv_image_set_src(bell_img, &bell_dsc);
    lv_image_set_pivot(bell_img, BELL_W / 2, BELL_PIVOT);
    lv_image_set_antialias(bell_img, true);
    lv_obj_remove_flag(bell_img, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_align(bell_img, LV_ALIGN_TOP_MID, 0, 82);

    /* Filled in by update_clock() once NTP has answered; never a made-up time. */
    home_clock = add_text(p, &lv_font_montserrat_48, 318, "--:--");
    home_date = add_muted(p, &lv_font_montserrat_16, 374, "Waiting for network time");

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

    init_styles();
    init_bell_art();
    render_bell(bell_colors[bell_idx].color);

    /* Nothing scrolls; gestures reach the screen from any page. */
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(scr, gesture_cb, LV_EVENT_GESTURE, NULL);
    for (uint32_t i = 0; i < PAGE_COUNT; i++)
        pages[i] = add_page();

    create_home(pages[HOME]);
    create_status_page(pages[WIFI], WIFI, LV_SYMBOL_WIFI, "Wi-Fi", &wifi_view, LV_SYMBOL_LIST "  Choose network",
                       scan_cb);
    create_appearance(pages[APPEARANCE]);
    create_duration(pages[DURATION]);
    create_status_page(pages[CONTROLLER], CONTROLLER, LV_SYMBOL_HOME, "Indoor Unit", &ctrl_view,
                       LV_SYMBOL_EDIT "  Set address", broker_cb);
    create_wifi_list(pages[WIFI_LIST]);
    create_entry(pages[ENTRY]);

    net_get_status(&ns);
    apply_theme();
    set_page(HOME);
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
    net_start();
    net_report_settings(theme_idx, bell_idx, ring_seconds);

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
