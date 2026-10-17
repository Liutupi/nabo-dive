#include "nabo_dive_render.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nabo_dive_draw.h"

#ifdef NABO_DIVE_HOST
#define dive_alloc(n) malloc(n)
#define dive_free(p) free(p)
#else
#include "esp_heap_caps.h"
#define dive_alloc(n) heap_caps_malloc((n), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)
#define dive_free(p) heap_caps_free(p)
#endif

LV_FONT_DECLARE(nabo_menu_font_16);
LV_FONT_DECLARE(nabo_ui_font_18);
LV_FONT_DECLARE(nabo_poster_font_28);
LV_FONT_DECLARE(nabo_poster_font_48);
LV_FONT_DECLARE(nabo_mono_font_12);

#define STRIP_PX (DIVE_W * 5)
#define TITLE_SURF 104
static const char* const kZoneName[DIVE_ZONES] = {"阳光层", "暮光层", "午夜层", "深渊", "海沟"};
static const char* const kZoneEn[DIVE_ZONES] = {"SUNLIT", "TWILIGHT", "MIDNIGHT", "ABYSS", "HADAL"};

static int mod_h(int v) { return ((v % DIVE_H) + DIVE_H) % DIVE_H; }
static float clampf(float v, float a, float b) { return v < a ? a : v > b ? b : v; }

bool dive_gfx_init(dive_gfx_t* g, dive_send_fn send, dive_scroll_fn scroll, dive_decode_fn decode, void* ctx) {
    memset(g, 0, sizeof(*g));
    g->send = send, g->scroll = scroll, g->decode = decode, g->ctx = ctx;
    g->rows = dive_alloc(sizeof(dive_rows_t));  // largest block first, before the heap fragments
    for (int i = 0; i < 2; ++i) {
#ifdef NABO_DIVE_HOST
        g->strip[i] = malloc(STRIP_PX * 2);
#else
        g->strip[i] = heap_caps_malloc(STRIP_PX * 2, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
#endif
    }
    g->frame_px = dive_alloc(NABO_DIVE_CELL * NABO_DIVE_CELL);
    g->frame_id = -1;
    g->ops = dive_alloc(sizeof(dive_op_t) * DIVE_MAX_OPS);
    g->layouts = dive_alloc(sizeof(dive_text_layout_t) * DIVE_MAX_LAYOUTS);
    if (!g->strip[0] || !g->strip[1] || !g->frame_px || !g->rows || !g->ops ||
        !g->layouts) {
        dive_gfx_free(g);
        return false;
    }
    for (int i = 0; i < DIVE_H; ++i)
        g->rows->y[i] = INT32_MIN;
    for (int i = 0; i < DIVE_H / 4; ++i)
        g->rows->band_y[i] = INT32_MIN;
    g->full = true;
    g->pal_bucket = -999;
    return true;
}

void dive_gfx_free(dive_gfx_t* g) {
    for (int i = 0; i < 2; ++i) {
        dive_free(g->strip[i]);
        g->strip[i] = NULL;
    }
    dive_free(g->frame_px);
    g->frame_px = NULL;
    dive_free(g->rows);
    dive_free(g->ops);
    dive_free(g->layouts);
    g->rows = NULL, g->ops = NULL, g->layouts = NULL;
}

void dive_gfx_invalidate(dive_gfx_t* g) {
    g->full = true;
    for (int i = 0; i < DIVE_H; ++i)  // a new dive may use another seed: terrain cache is stale
        g->rows->y[i] = INT32_MIN;
    for (int i = 0; i < DIVE_H / 4; ++i)
        g->rows->band_y[i] = INT32_MIN;
}

/* ---------- palette: depth tint + zone rim light ---------- */

static void lerp3(const uint8_t (*s)[4], int n, float at, float* out) {
    // s rows: {at/100, r, g, b}
    if (at <= s[0][0] * 100.0f) {
        out[0] = s[0][1], out[1] = s[0][2], out[2] = s[0][3];
        return;
    }
    for (int i = 1; i < n; ++i)
        if (at < s[i][0] * 100.0f) {
            float t = (at - s[i - 1][0] * 100.0f) / ((s[i][0] - s[i - 1][0]) * 100.0f);
            for (int k = 0; k < 3; ++k)
                out[k] = s[i - 1][k + 1] + (s[i][k + 1] - s[i - 1][k + 1]) * t;
            return;
        }
    out[0] = s[n - 1][1], out[1] = s[n - 1][2], out[2] = s[n - 1][3];
}

static void build_palette(dive_gfx_t* g, float depth_px) {
    static const uint8_t tint[5][4] = {{0, 255, 255, 255}, {9, 0xe8, 0xf3, 0xfb}, {32, 0xd4, 0xe2, 0xf2},
                                       {62, 0xc6, 0xd0, 0xea}, {95, 0xc0, 0xc6, 0xe2}};
    static const uint8_t rim[5][4] = {{0, 255, 255, 255}, {9, 0xe6, 0xfb, 0xff}, {32, 0x8f, 0xf3, 0xff},
                                      {62, 0xff, 0x9c, 0xf0}, {95, 0xff, 0xd0, 0x8a}};
    static const uint8_t bg[5][4] = {{0, 0x7a, 0xd3, 0xec}, {9, 0x2b, 0x86, 0xb9}, {32, 0x0e, 0x35, 0x60},
                                     {62, 0x06, 0x13, 0x28}, {95, 0x02, 0x06, 0x0d}};
    float t[3], rc[3], b[3];
    lerp3(tint, 5, depth_px, t);
    lerp3(rim, 5, depth_px, rc);
    lerp3(bg, 5, depth_px, b);
    float deep = clampf(depth_px / 6000, 0, 1), amb = 0.1f * deep;
    float rim_k = 1 + (deep > 0.15f ? deep * 0.8f : 0);
    for (int i = 0; i < NABO_DIVE_PALETTE_SIZE; ++i) {
        const nabo_dive_rgba_t* p = &nabo_dive_palette[i];
        float c[3] = {p->r * t[0] / 255, p->g * t[1] / 255, p->b * t[2] / 255};
        for (int k = 0; k < 3; ++k) {
            c[k] += (b[k] - c[k]) * amb;
            c[k] += rc[k] * p->rim / 255.0f * rim_k;
            c[k] = clampf(c[k], 0, 255);
        }
        g->pal[i] = rgb565((int)c[0], (int)c[1], (int)c[2]);
        g->pal_a[i] = p->a;
    }
}

/* ---------- operation list ---------- */

static dive_op_t* add_op(dive_gfx_t* g, int kind, int layer, bool dynamic, float x0, float y0, float x1,
                         float y1) {
    if (g->op_n >= DIVE_MAX_OPS)
        return NULL;
    dive_op_t* op = &g->ops[g->op_n++];
    memset(op, 0, sizeof(*op));
    op->kind = (uint8_t)kind, op->layer = (uint8_t)layer, op->dynamic = dynamic;
    op->x0 = (int16_t)floorf(x0 < 0 ? 0 : x0), op->y0 = (int16_t)floorf(y0 < 0 ? 0 : y0);
    op->x1 = (int16_t)ceilf(x1 > DIVE_W ? DIVE_W : x1), op->y1 = (int16_t)ceilf(y1 > DIVE_H ? DIVE_H : y1);
    if (op->x1 <= op->x0 || op->y1 <= op->y0) {
        --g->op_n;
        return NULL;
    }
    return op;
}

static void add_dim(dive_gfx_t* g, float amount) {
    dive_op_t* op = add_op(g, OP_DIM, LAYER_UI, false, 0, 0, DIVE_W, DIVE_H);
    if (op)
        op->b = amount;
}

static void add_text(dive_gfx_t* g, const lv_font_t* font, const char* s, int x, int y, dive_align_t al,
                     int spacing, uint16_t color, float alpha, bool shadow, bool dynamic, int layer) {
    if (g->layout_n >= DIVE_MAX_LAYOUTS || alpha <= 0.01f)
        return;
    int li = g->layout_n++;
    dive_text_layout_t* t = &g->layouts[li];
    dive_text_layout(t, font, s, x, y, al, spacing, color, (uint8_t)(clampf(alpha, 0, 1) * 255));
    if (shadow) {
        dive_op_t* sh = add_op(g, OP_SHADOW, layer, dynamic, t->x0, t->y0, t->x1 + 1, t->y1 + 1);
        if (sh)
            sh->i = (int16_t)li;
    }
    dive_op_t* op = add_op(g, OP_TEXT, layer, dynamic, t->x0, t->y0, t->x1, t->y1);
    if (op)
        op->i = (int16_t)li;
}

static void add_rect(dive_gfx_t* g, float x, float y, float x2, float y2, uint16_t c, float alpha, int radius,
                     float outline, bool dynamic, int layer) {
    dive_op_t* op = add_op(g, OP_RECT, layer, dynamic, x, y, x2, y2);
    if (op)
        op->x = x, op->y = y, op->x2 = x2, op->y2 = y2, op->c = c, op->b = alpha, op->i = (int16_t)radius,
        op->a = outline;
}

static void add_line(dive_gfx_t* g, float x, float y, float x2, float y2, uint16_t c, float alpha, float dash,
                     bool dynamic, int layer) {
    dive_op_t* op = add_op(g, OP_LINE, layer, dynamic, fminf(x, x2) - 1, fminf(y, y2), fmaxf(x, x2) + 1,
                           fmaxf(y, y2) + 1);
    if (op)
        op->x = x, op->y = y, op->x2 = x2, op->y2 = y2, op->c = c, op->b = alpha, op->a = dash;
}

static void add_nabo(dive_gfx_t* g, float sx, float sy, bool dynamic) {
    const float* m = g->v->m;
    float det = m[0] * m[3] - m[1] * m[2];
    if (fabsf(det) < 1e-4f)
        return;
    g->inv[0] = m[3] / det, g->inv[1] = -m[1] / det, g->inv[2] = -m[2] / det, g->inv[3] = m[0] / det;
    g->nabo_x = sx, g->nabo_y = sy;
    float minx = 1e9f, miny = 1e9f, maxx = -1e9f, maxy = -1e9f;
    // Union of the opaque boxes of both frames drawn (current and cross-fade source).
    nabo_dive_box_t box = nabo_dive_boxes[g->v->frame];
    for (int i = 0; i < 4; ++i) {
        float u = ((i & 1) ? box.u1 : box.u0) - (float)NABO_DIVE_ANCHOR_X;
        float v = ((i & 2) ? box.v1 : box.v0) - (float)NABO_DIVE_ANCHOR_Y;
        float x = m[0] * u + m[1] * v, y = m[2] * u + m[3] * v;
        minx = fminf(minx, x), maxx = fmaxf(maxx, x), miny = fminf(miny, y), maxy = fmaxf(maxy, y);
    }
    add_op(g, OP_NABO, LAYER_WORLD, dynamic, sx + minx - 1, sy + miny - 1, sx + maxx + 2, sy + maxy + 2);
}

static void world_ops(dive_gfx_t* g, bool animate) {
    const dive_t* d = g->d;
    float cam = (float)g->cam;
    for (int i = 0; i < DIVE_MAX_VENTS; ++i) {
        const dive_vent_t* v = &d->vents[i];
        if (!v->alive)
            continue;
        float sy = v->y - cam, x = v->x;
        dive_op_t* op = add_op(g, OP_VENT, LAYER_WORLD, false, x - 16, sy - 16, x + 16, sy + 16);
        if (op)
            op->i = (int16_t)i;
    }
    if (d->best_px > 0) {
        float by = roundf(d->best_px - cam);
        if (by > -14 && by < DIVE_H + 14) {
            float l, r;
            dive_corridor(d, d->best_px, &l, &r);
            uint16_t c = d->passed_best ? rgb565(255, 181, 71) : 0xFFFF;
            float a = d->passed_best ? 0.95f : 0.55f;
            add_line(g, l + 2, by, r - 2, by, c, a, 3, animate, LAYER_WORLD);
            add_line(g, r - 14, by - 13, r - 14, by, c, a, 0, animate, LAYER_WORLD);
            add_rect(g, r - 21, by - 13, r - 14, by - 8, c, a, 0, 0, animate, LAYER_WORLD);
            char text[24];
            snprintf(text, sizeof(text), "最深 %d", (int)dive_depth_m(d->best_px));
            add_text(g, &nabo_menu_font_16, text, (int)r - 24, (int)by - 3, DIVE_ALIGN_RIGHT, 0, c, a, false,
                     animate, LAYER_WORLD);
        }
    }
    for (int i = 0; i < DIVE_MAX_BUBBLES; ++i) {
        const dive_bubble_t* b = &d->bubbles[i];
        if (!b->alive)
            continue;
        float sy = b->y - cam;
        float glow = clampf((b->y - 900) / 2500, 0, 1) * 0.8f + (b->kind == DIVE_BUB_CLUSTER ? 0.3f : 0.1f);
        float reach = (b->kind == DIVE_BUB_CLUSTER ? 10 : b->r) * (glow > 0.02f ? 2.6f : 1.2f) + 3;
        dive_op_t* op = add_op(g, OP_BUBBLE, LAYER_WORLD, animate, b->x - reach, sy - reach, b->x + reach,
                               sy + reach);
        if (op)
            op->x = b->x, op->y = sy, op->a = b->r, op->b = glow * 97, op->i = b->kind;
    }
    for (int i = 0; i < DIVE_MAX_OBS; ++i) {
        const dive_obs_t* o = &d->obs[i];
        if (!o->alive)
            continue;
        float sy = o->y - cam;
        dive_op_t* op;
        float t = d->t;
        if (o->kind == DIVE_JELLY) {
            float R = o->rad, reach = R * 2.2f + 2;
            op = add_op(g, OP_JELLY, LAYER_WORLD, animate, o->x - reach, sy - reach, o->x + reach,
                        sy + fmaxf(reach, R * 1.9f + 4));
            if (op) {
                float deep = clampf(o->by / 3000, 0.3f, 1);
                op->x = o->x, op->y = sy, op->a = R, op->b = 76 * deep;
                op->x2 = 0.5f + 0.5f * sinf(t * 3.2f + o->ph);
                op->y2 = fmodf((t * 4 + o->ph) * 40.74f, 256);  // radians -> 1/256 turn
            }
        } else {
            op = add_op(g, OP_ANGLER, LAYER_WORLD, animate, o->x - 44, sy - 40, o->x + 44, sy + 18);
            if (op) {
                op->x = o->x, op->y = sy;
                op->x2 = o->x + o->face * 21, op->y2 = sy - 17 + sinf(t * 2 + o->ph) * 2;
                op->a = 0.5f + 0.5f * sinf(t * 1.5f + o->ph);
                op->c = rgb565(0x2a, 0x2e, 0x46);  // dim body, read against the lure light
            }
        }
        if (op)
            op->i = (int16_t)i;
    }
}

static void nabo_ops(dive_gfx_t* g, bool animate) {
    const dive_t* d = g->d;
    float sy = d->y - g->cam;
    float deep = clampf((d->y - 600) / 3000, 0, 1);
    if (deep > 0) {
        dive_op_t* op = add_op(g, OP_GLOW, LAYER_WORLD, animate, d->x - 28, sy + 4 - 28, d->x + 28, sy + 4 + 28);
        if (op)
            op->x = d->x, op->y = sy + 4, op->a = 28, op->b = 0.18f * deep, op->c = rgb565(200, 240, 255);
    }
    add_nabo(g, d->x, sy, animate);
    for (int i = 0; i < DIVE_MAX_PARTS; ++i) {
        const dive_part_t* p = &d->parts[i];
        if (!p->alive)
            continue;
        float px = p->x, py = p->y - g->cam;
        float reach = p->kind == DIVE_PART_RING ? p->r + 11 : p->r + 2;
        if (p->kind == DIVE_PART_NEAR)
            px = d->x, py = sy, reach = 34;
        dive_op_t* op = p->kind == DIVE_PART_STREAK
                            ? add_op(g, OP_PART, LAYER_WORLD, animate, px - 1, py, px + 2, py + p->len + 1)
                            : add_op(g, OP_PART, LAYER_WORLD, animate, px - reach, py - reach, px + reach,
                                     py + reach);
        if (!op)
            continue;
        float a = p->life / p->max;
        op->i = p->kind, op->x = px, op->y = py;
        if (p->kind == DIVE_PART_BUBBLE)
            op->a = p->r, op->b = 217 * a;
        else if (p->kind == DIVE_PART_RING)
            op->a = p->r + (1 - a) * 9, op->b = 255 * a;
        else if (p->kind == DIVE_PART_NEAR)
            op->a = 10 + (1 - a) * 22, op->b = 230 * a;
        else
            op->a = p->len * (0.5f + 0.5f * d->dash_k), op->b = 102 * a * d->dash_k;
    }
    for (int i = 0; i < DIVE_MAX_TEXTS; ++i) {
        const dive_text_t* t = &d->texts[i];
        if (!t->alive)
            continue;
        float a = clampf(1.4f - t->t * 1.5f, 0, 1);
        char s[20];
        static const uint16_t cols[4] = {0xFC4F, 0xCFBF, 0xFF34, 0xCFBF};  // ff8a7a c8f7ff ffe3a3 c8f7ff
        const lv_font_t* f = &nabo_mono_font_12;
        if (t->kind == DIVE_TEXT_MINUS)
            snprintf(s, sizeof(s), "-%d", t->value);
        else if (t->kind == DIVE_TEXT_PLUS)
            snprintf(s, sizeof(s), "+%d", t->value);
        else if (t->kind == DIVE_TEXT_NEAR)
            snprintf(s, sizeof(s), "擦边 +%d", t->value), f = &nabo_menu_font_16;
        else
            snprintf(s, sizeof(s), "得救"), f = &nabo_menu_font_16;
        add_text(g, f, s, (int)t->x, (int)(t->y - g->cam), DIVE_ALIGN_CENTER, 0, cols[t->kind & 3], a, false,
                 animate, LAYER_UI);
    }
}

static void hud_ops(dive_gfx_t* g) {
    const dive_t* d = g->d;
    char s[24];
    snprintf(s, sizeof(s), "%d", (int)dive_depth_m(d->y));
    add_text(g, &nabo_mono_font_12, "m", DIVE_W - 10, 29, DIVE_ALIGN_RIGHT, 0, 0xFFFF, 0.8f, true, true, LAYER_UI);
    add_text(g, &nabo_poster_font_28, s, DIVE_W - 20, 29, DIVE_ALIGN_RIGHT, 0, 0xFFFF, 1, true, true, LAYER_UI);
    float dk = d->dash_k;
    if (dk < 0.95f)
        add_text(g, &nabo_menu_font_16, kZoneName[dive_zone_of(d->y < 0 ? 0 : d->y)], DIVE_W - 10, 47,
                 DIVE_ALIGN_RIGHT, 0, rgb565(225, 245, 255), 0.72f * (1 - dk), true, true, LAYER_UI);
    if (dk > 0.05f) {
        add_text(g, &nabo_menu_font_16, "俯冲 x2", DIVE_W - 10, 47, DIVE_ALIGN_RIGHT, 1, rgb565(127, 243, 255),
                 dk, true, true, LAYER_UI);
        add_text(g, &nabo_mono_font_12, "x1.5", 18, 26, DIVE_ALIGN_LEFT, 0, rgb565(255, 181, 71), dk, true, true,
                 LAYER_UI);
    }
    bool low = d->o2 < 30 || d->lb;
    dive_op_t* gauge = add_op(g, OP_O2, LAYER_UI, true, 3, 12, 15, DIVE_H - 11);
    if (gauge) {
        // Opaque groove in the rock: no background is drawn beneath the gauge each frame.
        int wy = (int)d->cam_y + DIVE_H / 2;
        float t = clampf(wy / 9500.0f, 0, 1);
        gauge->opaque = true;
        gauge->x2 = (float)rgb565((int)(0x2a + (0x02 - 0x2a) * t) * 3 / 4, (int)(0x6f + (0x04 - 0x6f) * t) * 3 / 4,
                                  (int)(0x8f + (0x09 - 0x8f) * t) * 3 / 4);
        float o = clampf(d->o2 / DIVE_O2_MAX, 0, 1);
        int len = DIVE_H - 14 - 30, h = o > 0 ? (int)(len * o) : 0;
        gauge->x = (float)(h < 5 && o > 0 ? 5 : h);
        gauge->y = (0.5f + 0.5f * sinf(g->v->time * 9)) * 255;
        gauge->a = d->o2_flash > 0 ? d->o2_flash / 0.3f * 217 : 0;
        if (o > 0.5f)
            gauge->c = rgb565(0x7f, 0xf3, 0xff);
        else if (o > 0.2f) {
            float t = (o - 0.2f) / 0.3f;
            gauge->c = rgb565((int)(0xff + (0x7f - 0xff) * t), (int)(0xb5 + (0xf3 - 0xb5) * t),
                              (int)(0x47 + (0xff - 0x47) * t));
        } else
            gauge->c = rgb565(0xff, 0x5a, 0x5a);
        gauge->i = (int16_t)((low ? 1 : 0) | (d->lb && ((int)(g->v->time * 8) & 1) ? 2 : 0));
    }
    if (d->lb) {
        float a = 0.6f + 0.4f * sinf(g->v->time * 11);
        add_text(g, &nabo_ui_font_18, "最后一口气", DIVE_W / 2 + 2, 60, DIVE_ALIGN_CENTER, 5, rgb565(255, 122, 122),
                 a, false, true, LAYER_UI);
    } else if (d->toast_zone >= 0) {
        float t = d->toast_t, a = t < 0.3f ? t / 0.3f : t > 1.9f ? fmaxf(0, (2.4f - t) / 0.5f) : 1;
        bool rec = d->toast_zone >= DIVE_ZONES;
        uint16_t c = rec ? rgb565(255, 181, 71) : 0xFFFF;
        const char* title = rec ? "新纪录" : kZoneName[d->toast_zone];
        char sub[32];
        if (rec)
            snprintf(sub, sizeof(sub), "NEW RECORD");
        else
            snprintf(sub, sizeof(sub), "%d M  %s", dive_zone_m[d->toast_zone], kZoneEn[d->toast_zone]);
        int w = dive_text_width(&nabo_ui_font_18, title, 6);
        add_text(g, &nabo_ui_font_18, title, DIVE_W / 2 + 3, 60, DIVE_ALIGN_CENTER, 6, c, a, true, true, LAYER_UI);
        add_line(g, DIVE_W / 2 - w / 2 - 24, 54, DIVE_W / 2 - w / 2 - 8, 54, c, a * 0.55f, 0, true, LAYER_UI);
        add_line(g, DIVE_W / 2 + w / 2 + 10, 54, DIVE_W / 2 + w / 2 + 26, 54, c, a * 0.55f, 0, true, LAYER_UI);
        add_text(g, &nabo_mono_font_12, sub, DIVE_W / 2 + 1, 75, DIVE_ALIGN_CENTER, 1, c, a * 0.7f, false, true,
                 LAYER_UI);
    }
    if (g->v->dash_hint && d->t > 1.5f && d->t < 12) {
        float a = fminf(1, fminf((d->t - 1.5f) / 0.4f, (12 - d->t) / 0.6f));
        const char* msg = "按住下键俯冲  速度 x2 耗氧 x1.5";
        int w = dive_text_width(&nabo_menu_font_16, msg, 0);
        add_rect(g, DIVE_W / 2 - w / 2 - 10, 290, DIVE_W / 2 + w / 2 + 10, 310, rgb565(2, 10, 20), 0.55f * a, 10,
                 0, true, LAYER_UI);
        add_text(g, &nabo_menu_font_16, msg, DIVE_W / 2, 305, DIVE_ALIGN_CENTER, 0, rgb565(225, 245, 255), a, false,
                 true, LAYER_UI);
    }
}

static void over_ops(dive_gfx_t* g) {
    const dive_t* d = g->d;
    char s[48];
    int m = (int)dive_depth_m(d->y);
    add_dim(g, 0.76f);
    snprintf(s, sizeof(s), "氧气耗尽 · %s", kZoneName[dive_zone_of(d->y < 0 ? 0 : d->y)]);
    add_text(g, &nabo_menu_font_16, s, 24, 86, DIVE_ALIGN_LEFT, 3, rgb565(200, 230, 245), 0.75f, false, false,
             LAYER_UI);
    snprintf(s, sizeof(s), "%d", m);
    int w = dive_text_width(&nabo_poster_font_48, s, 0);
    add_text(g, &nabo_poster_font_48, s, 22, 140, DIVE_ALIGN_LEFT, 0, 0xFFFF, 1, false, false, LAYER_UI);
    add_text(g, &nabo_mono_font_12, "m", 26 + w, 140, DIVE_ALIGN_LEFT, 0, 0xFFFF, 1, false, false, LAYER_UI);
    if (d->new_record) {
        add_rect(g, 24, 151, 80, 170, rgb565(255, 181, 71), 1, 9, 0, false, LAYER_UI);
        add_text(g, &nabo_menu_font_16, "新纪录", 52, 166, DIVE_ALIGN_CENTER, 0, rgb565(26, 18, 6), 1, false, false,
                 LAYER_UI);
    } else if (d->best_px > 0) {
        snprintf(s, sizeof(s), "最深 %d m", (int)dive_depth_m(d->best_px));
        add_text(g, &nabo_menu_font_16, s, 24, 166, DIVE_ALIGN_LEFT, 0, 0xFFFF, 0.65f, false, false, LAYER_UI);
    }
    dive_op_t* p = add_op(g, OP_PROFILE, LAYER_UI, false, 16, 188, 224, 208);
    if (p)
        p->y = 200, p->a = d->new_record ? 0 : d->best_px;
    for (int i = 1; i < DIVE_ZONES; ++i) {
        snprintf(s, sizeof(s), "%d", dive_zone_m[i]);
        add_text(g, &nabo_mono_font_12, s, 24 + (int)(dive_zone_px[i] / 11000 * 192), 219, DIVE_ALIGN_CENTER, 0,
                 rgb565(200, 230, 245), 0.5f, false, false, LAYER_UI);
    }
    const char* labels[3] = {"气泡", "擦边", "用时"};
    int values[3] = {d->stat_bubbles, d->stat_near, (int)d->t};
    for (int i = 0; i < 3; ++i) {
        snprintf(s, sizeof(s), i == 2 ? "%dS" : "%d", values[i]);
        add_text(g, &nabo_poster_font_28, s, 24 + i * 70, 254, DIVE_ALIGN_LEFT, 0, 0xFFFF, 1, false, false, LAYER_UI);
        add_text(g, &nabo_menu_font_16, labels[i], 24 + i * 70, 274, DIVE_ALIGN_LEFT, 0, rgb565(200, 230, 245), 0.55f,
                 false, false, LAYER_UI);
    }
    if (g->v->time > 0.45f) {
        float pulse = 0.6f + 0.4f * sinf(g->v->time * 2.6f);
        int pw = dive_text_width(&nabo_menu_font_16, "OK 再来一次", 1) + 24;
        add_rect(g, 24, 283, 24 + pw, 307, 0xFFFF, pulse, 12, 1, true, LAYER_UI);
        add_text(g, &nabo_menu_font_16, "OK 再来一次", 24 + pw / 2, 301, DIVE_ALIGN_CENTER, 1, 0xFFFF, pulse, false,
                 true, LAYER_UI);
        add_text(g, &nabo_menu_font_16, "上键 标题", DIVE_W - 24, 301, DIVE_ALIGN_RIGHT, 0, rgb565(200, 230, 245), 0.5f,
                 false, false, LAYER_UI);
    }
}

static void title_ops(dive_gfx_t* g) {
    static const float stops[DIVE_ZONES] = {0, 0.16f, 0.38f, 0.62f, 0.86f};
    char s[40];
    dive_op_t* gauge = add_op(g, OP_GAUGE, LAYER_UI, false, DIVE_W - 22, TITLE_SURF, DIVE_W, DIVE_H);
    int best = g->v->best_m;
    if (gauge && best > 0) {
        float f = 0.97f;
        for (int i = 1; i < DIVE_ZONES; ++i)
            if (best < dive_zone_m[i]) {
                f = stops[i - 1] + (stops[i] - stops[i - 1]) * (best - dive_zone_m[i - 1]) /
                                       (float)(dive_zone_m[i] - dive_zone_m[i - 1]);
                break;
            }
        if (best >= 6000)
            f = fminf(0.97f, 0.86f + (best - 6000) / 40000.0f);
        gauge->a = TITLE_SURF + f * (DIVE_H - TITLE_SURF);
    }
    for (int i = 1; i < DIVE_ZONES; ++i) {
        snprintf(s, sizeof(s), "%d", dive_zone_m[i]);
        add_text(g, &nabo_mono_font_12, s, DIVE_W - 22, TITLE_SURF + (int)(stops[i] * (DIVE_H - TITLE_SURF)) + 4,
                 DIVE_ALIGN_RIGHT, 0, rgb565(220, 240, 250), 0.6f, false, false, LAYER_UI);
    }
    add_text(g, &nabo_poster_font_48, "DIVE", 18, 194, DIVE_ALIGN_LEFT, 0, 0xFFFF, 1, false, false, LAYER_UI);
    add_text(g, &nabo_ui_font_18, "深潜", 21, 218, DIVE_ALIGN_LEFT, 11, rgb565(205, 235, 250), 0.85f, false, false,
             LAYER_UI);
    float blink = 0.55f + 0.45f * sinf(g->v->time * 2.6f);
    add_text(g, &nabo_ui_font_18, "按 OK 下潜", 20, 270, DIVE_ALIGN_LEFT, 2, 0xFFFF, blink, false, true, LAYER_UI);
    if (best > 0)
        snprintf(s, sizeof(s), "最深 %d m", best);
    else
        snprintf(s, sizeof(s), "还没有纪录");
    add_text(g, &nabo_menu_font_16, s, 20, 294, DIVE_ALIGN_LEFT, 0, rgb565(225, 245, 255), 0.8f, false, false,
             LAYER_UI);
    add_nabo(g, g->d->x, g->d->y - g->d->cam_y, true);
}

static void pause_ops(dive_gfx_t* g) {
    add_dim(g, 0.66f);
    add_text(g, &nabo_ui_font_18, "暂停", DIVE_W / 2 + 4, 158, DIVE_ALIGN_CENTER, 8, 0xFFFF, 1, false, false, LAYER_UI);
    add_text(g, &nabo_menu_font_16, "上键或 OK 继续", DIVE_W / 2, 182, DIVE_ALIGN_CENTER, 0, rgb565(200, 230, 245),
             0.6f, false, false, LAYER_UI);
}

/* ---------- dirty rectangles ---------- */

static int area_of(const dive_rect_t* r) { return (r->x1 - r->x0) * (r->y1 - r->y0); }

// Merges rectangles when the union costs little more than sending both (each transfer
// also pays a CASET/RASET round trip, worth about 512 pixels).
static int merge(dive_rect_t* r, int n) {
    for (bool changed = true; changed;) {
        changed = false;
        for (int i = 0; i < n; ++i)
            for (int j = i + 1; j < n; ++j) {
                dive_rect_t u = {r[i].x0 < r[j].x0 ? r[i].x0 : r[j].x0, r[i].y0 < r[j].y0 ? r[i].y0 : r[j].y0,
                                 r[i].x1 > r[j].x1 ? r[i].x1 : r[j].x1, r[i].y1 > r[j].y1 ? r[i].y1 : r[j].y1};
                if (area_of(&u) * 10 > (area_of(&r[i]) + area_of(&r[j])) * 13 + 5120)
                    continue;
                r[i] = u;
                r[j--] = r[--n];
                changed = true;
            }
    }
    return n;
}

static bool clip(dive_rect_t* r) {
    if (r->x0 < 0) r->x0 = 0;
    if (r->y0 < 0) r->y0 = 0;
    if (r->x1 > DIVE_W) r->x1 = DIVE_W;
    if (r->y1 > DIVE_H) r->y1 = DIVE_H;
    return r->x1 > r->x0 && r->y1 > r->y0;
}

static void render_rect(dive_gfx_t* g, const dive_rect_t* r, bool world) {
    int w = r->x1 - r->x0, max_rows = STRIP_PX / w;
    uint8_t list[DIVE_MAX_OPS];
    int n = 0;
    bool covered = false;  // an opaque op covers the whole rectangle: skip what lies beneath
    for (int pass = 0; pass < 2; ++pass)  // world layer first, then UI
        for (int i = 0; i < g->op_n; ++i) {
            const dive_op_t* op = &g->ops[i];
            if (op->layer != pass || op->x1 <= r->x0 || op->x0 >= r->x1 || op->y1 <= r->y0 || op->y0 >= r->y1)
                continue;
            if (op->opaque && op->x0 <= r->x0 && op->x1 >= r->x1 && op->y0 <= r->y0 && op->y1 >= r->y1)
                n = 0, covered = true;
            list[n++] = (uint8_t)i;
        }
    for (int y = r->y0; y < r->y1;) {
        int gram = mod_h(g->scroll_top + y);
        int rows = r->y1 - y < max_rows ? r->y1 - y : max_rows;
        if (gram + rows > DIVE_H)
            rows = DIVE_H - gram;
        g->which ^= 1;
        uint16_t* buf = g->strip[g->which];
        uint32_t t0 = g->clock_us ? g->clock_us() : 0, t_bg = 0;
        for (int j = 0; j < rows; ++j) {
            uint16_t* row = buf + j * w;
            uint32_t tb = g->clock_us ? g->clock_us() : 0;
            if (covered)
                ;
            else if (world)
                dive_draw_world_row(g, g->cam + y + j, r->x0, r->x1, row);
            else
                dive_draw_title_row(g, y + j, r->x0, r->x1, row);
            if (g->clock_us)
                t_bg += g->clock_us() - tb;
            if (g->cycles)
                for (int k = 0; k < n; ++k) {
                    uint32_t c0 = g->cycles();
                    dive_draw_op(g, &g->ops[list[k]], y + j, r->x0, r->x1, row);
                    g->op_cycles[g->ops[list[k]].kind & 15] += g->cycles() - c0;
                }
            else
                for (int k = 0; k < n; ++k)
                    dive_draw_op(g, &g->ops[list[k]], y + j, r->x0, r->x1, row);
            for (int x = 0; x < w; ++x)
                row[x] = (uint16_t)((row[x] >> 8) | (row[x] << 8));
        }
        uint32_t t1 = g->clock_us ? g->clock_us() : 0;
        g->send(g->ctx, r->x0, gram, w, rows, buf);
        if (g->clock_us) {
            g->us_bg += t_bg;
            g->us_ops += t1 - t0 - t_bg;
            g->us_send += g->clock_us() - t1;
            g->segments += (uint32_t)rows;
        }
        g->bytes += (uint32_t)(w * rows * 2);
        y += rows;
    }
}

static void ensure_frame(dive_gfx_t* g, int frame) {
    if (frame < 0 || frame >= NABO_DIVE_FRAME_COUNT || g->frame_id == frame)
        return;
    if (g->decode(g->ctx, frame, g->frame_px))
        g->frame_id = frame;
}

void dive_gfx_frame(dive_gfx_t* g, const dive_t* d, const dive_view_t* v) {
    g->d = d, g->v = v, g->op_n = 0, g->layout_n = 0, g->bytes = 0;
    bool world = v->screen != DIVE_SCREEN_TITLE, play = v->screen == DIVE_SCREEN_PLAY;
    if (v->screen != g->last_screen)
        g->full = true;
    g->cam = world ? (int)floorf(d->cam_y) : 0;
    ensure_frame(g, v->frame);
    int bucket = world ? (int)(fmaxf(0, d->y) / 48) : -1;
    if (bucket != g->pal_bucket) {
        build_palette(g, world ? fmaxf(0, d->y) : 0);
        g->pal_bucket = bucket;
    }

    if (world) {
        world_ops(g, play);
        nabo_ops(g, play);
        if (play)
            hud_ops(g);
        if (v->screen == DIVE_SCREEN_PAUSE)
            pause_ops(g);
        else if (v->screen == DIVE_SCREEN_OVER)
            over_ops(g);
    } else
        title_ops(g);

    int rows = world && !g->full ? g->cam - g->last_cam : 0;
    if (rows >= DIVE_H || rows <= -DIVE_H)
        g->full = true, rows = 0;
    g->scroll_top = world ? mod_h(g->cam) : 0;
    int shake = 0;
    if (play && d->shake_t > 0)  // vertical shake through the scroll register only
        shake = (int)lroundf(sinf(d->t * 80) * 3 * (d->shake_t / 0.25f));
    g->scroll(g->ctx, mod_h(g->scroll_top + shake));

    dive_rect_t rects[DIVE_MAX_RECTS + DIVE_MAX_OPS + 1];
    int n = 0;
    if (g->full) {
        rects[n++] = (dive_rect_t){0, 0, DIVE_W, DIVE_H};
    } else {
        for (int i = 0; i < g->prev_n; ++i) {
            dive_rect_t r = g->prev[i];
            r.y0 = (int16_t)(r.y0 - rows), r.y1 = (int16_t)(r.y1 - rows);
            if (clip(&r))
                rects[n++] = r;
        }
        if (rows > 0)
            rects[n++] = (dive_rect_t){0, (int16_t)(DIVE_H - rows), DIVE_W, DIVE_H};
        else if (rows < 0)
            rects[n++] = (dive_rect_t){0, 0, DIVE_W, (int16_t)(-rows)};
    }
    int prev_n = 0;
    for (int i = 0; i < g->op_n; ++i) {
        const dive_op_t* op = &g->ops[i];
        if (!op->dynamic)
            continue;
        dive_rect_t r = {op->x0, op->y0, op->x1, op->y1};
        if (!clip(&r))
            continue;
        if (!g->full)
            rects[n++] = r;
        if (prev_n < DIVE_MAX_RECTS)
            g->prev[prev_n++] = r;
    }
    g->prev_n = prev_n;
    n = merge(rects, n);
    int area = 0;
    for (int i = 0; i < n; ++i)
        area += (rects[i].x1 - rects[i].x0) * (rects[i].y1 - rects[i].y0);
    if (area > DIVE_W * DIVE_H * 3 / 4) {  // cheaper as one transfer
        rects[0] = (dive_rect_t){0, 0, DIVE_W, DIVE_H};
        n = 1;
    }
    for (int i = 0; i < n; ++i)
        render_rect(g, &rects[i], world);
    g->last_cam = g->cam;
    g->last_screen = v->screen;
    g->full = false;
}
