#include "nabo_dive_draw.h"
#include <math.h>
#include <string.h>

// The C3 has no FPU: everything that runs per row segment or per pixel is integer.
// Per-frame values (pulses, alphas, particle geometry) arrive precomputed in the ops.

typedef struct {
    int32_t at;
    uint8_t r, g, b;
} stop_t;

static const stop_t kBg[] = {{0, 0x7a, 0xd3, 0xec}, {900, 0x2b, 0x86, 0xb9}, {3200, 0x0e, 0x35, 0x60},
                             {6200, 0x06, 0x13, 0x28}, {9500, 0x02, 0x06, 0x0d}};
static const stop_t kWall[] = {{0, 0x2a, 0x6f, 0x8f}, {900, 0x17, 0x4a, 0x6e}, {3200, 0x0a, 0x23, 0x40},
                               {6200, 0x05, 0x0d, 0x1c}, {9500, 0x02, 0x04, 0x09}};
static const stop_t kEdge[] = {{0, 0x9f, 0xe6, 0xf4}, {900, 0x58, 0xb4, 0xda}, {3200, 0x2a, 0x6e, 0xa3},
                               {6200, 0x4b, 0x3a, 0x8c}, {9500, 0x7a, 0x4e, 0x1e}};
static const stop_t kSky[] = {{-400, 0xf4, 0xfb, 0xfd}, {0, 0xbf, 0xe9, 0xf5}};
static const stop_t kTitleWater[] = {{0, 0x7a, 0xd3, 0xec}, {160, 0x2b, 0x86, 0xb9}, {380, 0x0e, 0x35, 0x60},
                                     {620, 0x06, 0x13, 0x28}, {1000, 0x01, 0x04, 0x09}};  // per mille
static const uint8_t kGlow[DIVE_ZONES][3] = {
    {0xff, 0xff, 0xff}, {0x7f, 0xe7, 0xff}, {0x49, 0xf2, 0xe0}, {0xff, 0x5f, 0xd8}, {0xff, 0xb5, 0x47}};
static const uint8_t kJelly[DIVE_ZONES][2][3] = {
    {{0xc8, 0xf7, 0xff}, {0xff, 0xff, 0xff}}, {{0x8f, 0xea, 0xff}, {0xb9, 0xa8, 0xff}},
    {{0x49, 0xf2, 0xe0}, {0x7f, 0xa8, 0xff}}, {{0xff, 0x5f, 0xd8}, {0x9c, 0x7b, 0xff}},
    {{0xff, 0xb5, 0x47}, {0xff, 0x7a, 0x59}}};
#define TITLE_SURF 104
#define RAY_H 1300

static int8_t sin8[256];       // sin * 127, 256 steps per turn
static int8_t wave16[DIVE_W];  // surface wave height in 1/16 px
static uint8_t gauss_lut[64];  // exp(-d^2) * 255 for d in [0, 3)
static void tables_init(void) {
    if (gauss_lut[0])
        return;
    for (int i = 0; i < 256; ++i)
        sin8[i] = (int8_t)lroundf(sinf(i * 6.2831853f / 256) * 127);
    for (int x = 0; x < DIVE_W; ++x)
        wave16[x] = (int8_t)lroundf(1.6f * sinf(x * 0.07f) * 16);
    for (int i = 0; i < 64; ++i) {
        float d = i * 3.0f / 64;
        gauss_lut[i] = (uint8_t)(expf(-d * d) * 255);
    }
}

static void grad(const stop_t* s, int n, int32_t at, int* r, int* g, int* b) {
    if (at <= s[0].at) {
        *r = s[0].r, *g = s[0].g, *b = s[0].b;
        return;
    }
    for (int i = 1; i < n; ++i)
        if (at < s[i].at) {
            int t = (int)((at - s[i - 1].at) * 256 / (s[i].at - s[i - 1].at));
            *r = s[i - 1].r + ((s[i].r - s[i - 1].r) * t >> 8);
            *g = s[i - 1].g + ((s[i].g - s[i - 1].g) * t >> 8);
            *b = s[i - 1].b + ((s[i].b - s[i - 1].b) * t >> 8);
            return;
        }
    *r = s[n - 1].r, *g = s[n - 1].g, *b = s[n - 1].b;
}
static uint16_t mixc(int r1, int g1, int b1, int r2, int g2, int b2, int t256) {
    return rgb565(r1 + ((r2 - r1) * t256 >> 8), g1 + ((g2 - g1) * t256 >> 8), b1 + ((b2 - b1) * t256 >> 8));
}
static uint32_t ihash(uint32_t n) {
    n = (n ^ (n >> 16)) * 0x45d9f3bu;
    n = (n ^ (n >> 16)) * 0x45d9f3bu;
    return n ^ (n >> 16);
}
static int zone_of(int y) {
    int z = 0;
    for (int i = 1; i < DIVE_ZONES; ++i)
        if (y >= (int)dive_zone_px[i])
            z = i;
    return z;
}
static inline void fill(uint16_t* row, int x0, int x1, int a, int b, uint16_t c) {
    if (a < x0)
        a = x0;
    if (b > x1)
        b = x1;
    for (int x = a; x < b; ++x)
        row[x - x0] = c;
}
static inline void plot(int x, int x0, int x1, uint16_t* row, uint16_t c, int a) {
    if (x >= x0 && x < x1)
        row[x - x0] = blend565(row[x - x0], c, a);
}

/* ---------- light rays: per-seed parameters, integer per pixel ---------- */

typedef struct {
    int32_t c0_16;  // ray centre at the surface, 1/16 px
    int32_t step;   // gauss table steps per 1/16 px, Q12
    int16_t half;   // reach in px
    uint8_t k;      // strength, 0..255
} ray_t;
static ray_t ray_tab[5];
static uint32_t ray_seed = 0xFFFFFFFFu;

static void rays(uint32_t seed, int ry, int x0, int x1, int wa, int wb, uint16_t* row) {
    if (ry < 0 || ry >= RAY_H)
        return;
    if (seed != ray_seed) {
        const float inv = 0.921f;  // 1 / sqrt(1 + 0.42^2)
        for (int i = 0; i < 5; ++i) {
            float w = 5 + ((seed >> (i * 3)) & 7) * 1.5f;
            ray_tab[i].c0_16 = ((int)((seed >> (i * 5)) & 63) + i * 54 - 70) * 16;
            ray_tab[i].step = (int32_t)(64 * inv / (3 * w) * 4096 / 16);
            ray_tab[i].half = (int16_t)(3 * w / inv) + 1;
            ray_tab[i].k = (uint8_t)((0.7f + ((seed >> (i * 2)) & 3) * 0.12f) * 255 / 1.06f);
        }
        ray_seed = seed;
    }
    int f = (RAY_H - ry) * 256 / RAY_H;            // 1 - y/H in Q8
    int fade = ((f * f >> 8) * f >> 8) * 34 >> 8;  // ~ (1 - y/H)^3 * 0.13
    if (fade <= 0)
        return;
    int a = wa > x0 ? wa : x0, b = wb < x1 ? wb : x1;
    uint16_t c = rgb565(235, 250, 255);
    for (int i = 0; i < 5; i += 2) {  // three of the five rays: same look, 40% less work
        const ray_t* r = &ray_tab[i];
        int32_t c16 = r->c0_16 + ry * 672 / 100;  // slope 0.42 px per row
        int cx = c16 >> 4, amp = r->k * fade >> 8;
        int s = cx - r->half > a ? cx - r->half : a, e = cx + r->half < b ? cx + r->half : b;
        for (int x = s; x < e; ++x) {
            int32_t dq = ((x * 16 - c16) * r->step) >> 12;
            if (dq < 0)
                dq = -dq;
            if (dq < 64)
                row[x - x0] = add565(row[x - x0], c, gauss_lut[dq] * amp >> 8);
        }
    }
}

/* ---------- world rows ---------- */

void dive_rows_fill(dive_gfx_t* g, int y) {
    dive_rows_t* r = g->rows;
    int k = ((y % DIVE_H) + DIVE_H) % DIVE_H;
    if (r->y[k] == y)
        return;
    float l, rr, fl, fr;
    dive_corridor(g->d, (float)y, &l, &rr);
    dive_far(g->d, (float)y, l, rr, &fl, &fr);
    r->y[k] = y;
    r->l16[k] = (int16_t)(l * 16), r->r16[k] = (int16_t)(rr * 16);
    r->fl16[k] = (int16_t)(fl * 16), r->fr16[k] = (int16_t)(fr * 16);
    r->strata[k] = (int8_t)(dive_strata(g->d, (float)y) * 127);
}

static void surface(int dy, int x0, int x1, uint16_t sky, uint16_t water, uint16_t* row) {
    uint16_t foam = blend565(water, 0xFFFF, 217);
    for (int x = x0; x < x1; ++x) {
        int below16 = dy * 16 - wave16[x];
        row[x - x0] = below16 < 0 ? sky : below16 < 24 ? foam : water;
    }
}

static inline int q4(int v16) { return (v16 + 8) >> 4; }

void dive_draw_world_row(dive_gfx_t* g, int wy, int x0, int x1, uint16_t* row) {
    tables_init();
    int r, gg, b;
    if (wy < 3) {
        int sr, sg, sb;
        grad(kSky, 2, wy, &sr, &sg, &sb);
        grad(kBg, 5, 0, &r, &gg, &b);
        uint16_t sky = rgb565(sr, sg, sb), water = rgb565(r, gg, b);
        if (wy < -3)
            fill(row, x0, x1, x0, x1, sky);
        else
            surface(wy, x0, x1, sky, water, row);
        if (wy < 0)
            return;
    }
    dive_rows_fill(g, wy);
    dive_rows_t* rc = g->rows;
    int k = ((wy % DIVE_H) + DIVE_H) % DIVE_H;
    int l16 = rc->l16[k], r16 = rc->r16[k];
    int band = wy >> 2, bk = band % (DIVE_H / 4);
    uint16_t* c = rc->band_c[bk];
    if (rc->band_y[bk] != band) {  // colours for this 4-row band, always from its first row
        int by = band * 4 + 2, br, bgc, bb, wr, wg, wb, er, eg, eb;
        dive_rows_fill(g, band * 4);
        int fk = ((band * 4) % DIVE_H + DIVE_H) % DIVE_H;
        grad(kBg, 5, by, &br, &bgc, &bb);
        grad(kWall, 5, by, &wr, &wg, &wb);
        grad(kEdge, 5, by, &er, &eg, &eb);
        int st = 256 + rc->strata[fk] * 51 / 127;  // 1 + strata * 0.2
        int cr = wr * st >> 8, cg = wg * st >> 8, cb = wb * st >> 8;
        c[0] = rgb565(cr, cg, cb), c[1] = mixc(cr, cg, cb, er, eg, eb, 31);
        c[2] = mixc(cr, cg, cb, er, eg, eb, 72), c[3] = mixc(cr, cg, cb, er, eg, eb, 141);
        c[4] = rgb565(er, eg, eb), c[5] = mixc(br, bgc, bb, 0, 0, 0, 41);
        c[6] = mixc(br, bgc, bb, wr, wg, wb, 77), c[7] = rgb565(br, bgc, bb);
        c[8] = mixc(cr, cg, cb, 0, 0, 0, 64);
        rc->band_y[bk] = band;
    }
    uint16_t wall = c[0], b1 = c[1], b2 = c[2], b3 = c[3], edge = c[4], ao = c[5], far = c[6], bg = c[7];
    int e[14];
    e[0] = q4(l16 - 256), e[1] = q4(l16 - 112), e[2] = q4(l16 - 42), e[3] = q4(l16 - 19), e[4] = q4(l16);
    e[5] = e[4] + 4, e[6] = q4(rc->fl16[k]), e[7] = q4(rc->fr16[k]), e[9] = q4(r16), e[8] = e[9] - 4;
    e[10] = q4(r16 + 19), e[11] = q4(r16 + 42), e[12] = q4(r16 + 112), e[13] = q4(r16 + 256);
    if (e[6] < e[5])
        e[6] = e[5];
    if (e[7] > e[8])
        e[7] = e[8];
    if (e[7] < e[6])
        e[7] = e[6];
    const uint16_t span_c[15] = {wall, b1, b2, b3, edge, ao, far, bg, far, ao, edge, b3, b2, b1, wall};
    int prev = -1000;
    for (int i = 0; i < 15; ++i) {
        int a = i ? e[i - 1] : -1000, z = i < 14 ? e[i] : 1000;
        if (a < prev)
            a = prev;
        if (z > a)
            fill(row, x0, x1, a, z, span_c[i]);
        if (z > prev)
            prev = z;
    }
    if (wy < RAY_H)
        rays(g->d->seed, wy, x0, x1, e[4], e[9], row);
    uint32_t h = ihash((uint32_t)(wy >> 1) + g->d->seed);
    if (h % 11 == 0) {  // pebble in the rock
        int left = h & 1, w = 3 + (int)((h >> 9) % 4);
        int px = left ? e[0] - 4 - (int)((h >> 3) % 40) : e[13] + 4 + (int)((h >> 3) % 40);
        fill(row, x0, x1, px, px + w, c[8]);
    }
    if (wy > 1400 && h % 31 == 3) {  // glowing lichen on the rock face
        int z = zone_of(wy);
        int px = (h & 2) ? e[4] - 4 - (int)((h >> 5) % 10) : e[9] + 3 + (int)((h >> 5) % 10);
        fill(row, x0, x1, px, px + 2, rgb565(kGlow[z][0], kGlow[z][1], kGlow[z][2]));
    }
    uint32_t s = ihash((uint32_t)wy * 7u + g->d->seed * 13u);
    if (s % 9 == 0) {  // marine snow
        int px = (int)((s >> 8) % DIVE_W);
        if (px >= e[4] && px < e[9] && px >= x0 && px < x1) {
            int vis = (wy - 300) * 256 / 1500;
            vis = vis < 51 ? 51 : vis > 256 ? 256 : vis;
            row[px - x0] = blend565(row[px - x0], rgb565(210, 240, 250), (64 + (int)((s >> 16) & 127)) * vis >> 8);
        }
    }
}

void dive_draw_title_row(dive_gfx_t* g, int y, int x0, int x1, uint16_t* row) {
    tables_init();
    int r, gg, b;
    if (y < TITLE_SURF + 3) {
        int t = y * 256 / TITLE_SURF;
        uint16_t sky = rgb565(0xee + ((0xbd - 0xee) * t >> 8), 0xf9 + ((0xe8 - 0xf9) * t >> 8),
                              0xfc + ((0xf4 - 0xfc) * t >> 8));
        if (y < TITLE_SURF - 3)
            fill(row, x0, x1, x0, x1, sky);
        else
            surface(y - TITLE_SURF, x0, x1, sky, rgb565(0x7a, 0xd3, 0xec), row);
        int dy = y - 22;
        if (y < TITLE_SURF - 3 && dy * dy < 6400)  // sun glow around (196, 22), squared falloff
            for (int x = x0; x < x1; ++x) {
                int dx = x - 196, q = 6400 - dx * dx - dy * dy;
                if (q > 0)
                    row[x - x0] = add565(row[x - x0], 0xFFFF, (q >> 3) * (q >> 3) / 5818);  // 110 * (q/6400)^2
            }
        if (y < TITLE_SURF)
            return;
    }
    int pm = (y - TITLE_SURF) * 1000 / (DIVE_H - TITLE_SURF);
    grad(kTitleWater, 5, pm, &r, &gg, &b);
    if (y >= TITLE_SURF + 3)
        fill(row, x0, x1, x0, x1, rgb565(r, gg, b));
    rays(g->d->seed, y - TITLE_SURF, x0, x1, 0, DIVE_W, row);
    for (int i = 0; i < 46; ++i) {
        uint32_t h = ihash((uint32_t)i * 7919u + 13u);
        int sx = (int)(h % DIVE_W), sy = TITLE_SURF + 20 + (int)((h >> 8) % (DIVE_H - TITLE_SURF - 20));
        int sf = (sy - TITLE_SURF) * 1000 / (DIVE_H - TITLE_SURF);
        bool glowing = sf > 600 && h % 6 == 0;
        if (y != sy && !(glowing && y == sy + 1))
            continue;
        int z = sf > 860 ? 4 : sf > 620 ? 3 : 2;
        uint16_t c = glowing ? rgb565(kGlow[z][0], kGlow[z][1], kGlow[z][2]) : rgb565(215, 240, 250);
        int a = glowing ? 200 : 38 + sf * 89 / 1000;
        for (int x = sx; x < sx + (glowing ? 2 : 1); ++x)
            plot(x, x0, x1, row, c, a);
    }
}

/* ---------- shapes ---------- */

// Soft disc: fill alpha fa, 1 px ring alpha ra (both 0..255); centre/radius in 1/16 px.
static void disc(int y, int x0, int x1, int cx16, int cy16, int r16, uint16_t fc, int fa, uint16_t rc, int ra,
                 uint16_t* row) {
    int dy = y * 16 + 8 - cy16;
    int outer = r16 + 10, inner = r16 - 10;
    if (dy >= outer || -dy >= outer)
        return;
    int32_t o2 = outer * outer, i2 = inner > 0 ? inner * inner : 0, dy2 = dy * dy;
    int a = (cx16 - outer) / 16 - 1, b = (cx16 + outer) / 16 + 2;
    if (a < x0)
        a = x0;
    if (b > x1)
        b = x1;
    for (int x = a; x < b; ++x) {
        int dx = x * 16 + 8 - cx16;
        int32_t d2 = dx * dx + dy2;
        if (d2 >= o2)
            continue;
        uint16_t* p = &row[x - x0];
        if (d2 < i2) {
            if (fa)
                *p = blend565(*p, fc, fa);
        } else if (ra)
            *p = blend565(*p, rc, ra);
        else if (fa)
            *p = blend565(*p, fc, fa / 2);
    }
}
// Additive radial glow; strength 0..255 at the centre, linear-in-d^2 falloff.
static void glow(int y, int x0, int x1, int cx, int cy, int radius, uint16_t c, int strength, uint16_t* row) {
    int dy = y - cy;
    if (dy >= radius || -dy >= radius || strength <= 0 || radius <= 0)
        return;
    int32_t r2 = radius * radius, inv = (strength << 16) / r2, dy2 = dy * dy;
    int a = cx - radius > x0 ? cx - radius : x0, b = cx + radius < x1 ? cx + radius : x1;
    for (int x = a; x < b; ++x) {
        int32_t dx = x - cx, d2 = dx * dx + dy2;
        if (d2 < r2)
            row[x - x0] = add565(row[x - x0], c, (int)((r2 - d2) * inv >> 16));
    }
}
// Filled triangle row span (vertices in screen px).
static void tri(int y, int x0, int x1, const int* px, const int* py, uint16_t c, int a, uint16_t* row) {
    int yc2 = y * 2 + 1, lo = 1 << 20, hi = -(1 << 20);
    for (int i = 0; i < 3; ++i) {
        int j = (i + 1) % 3, ya = py[i] * 2, yb = py[j] * 2;
        if ((yc2 < ya) == (yc2 < yb))
            continue;
        int x = px[i] + (yc2 - ya) * (px[j] - px[i]) / (yb - ya);
        lo = x < lo ? x : lo;
        hi = x > hi ? x : hi;
    }
    for (int x = lo > x0 ? lo : x0; x < (hi < x1 ? hi : x1); ++x)
        row[x - x0] = blend565(row[x - x0], c, a);
}
// Row span of an ellipse (centre cx, cy; radii rx, ry in px) with a small integer sqrt.
static bool ellipse_span(int y, int cx, int cy, int rx, int ry, int* a, int* b) {
    int dy = y - cy;
    if (ry <= 0 || dy <= -ry || dy >= ry)
        return false;
    int q = (ry * ry - dy * dy) * 256 / (ry * ry);  // 1 - (dy/ry)^2 in Q8
    int s = 0;
    while ((s + 1) * (s + 1) <= q)
        ++s;  // sqrt in Q4
    int hw = rx * s / 16;
    *a = cx - hw, *b = cx + hw;
    return true;
}

// op: x, y centre (screen), a radius, b glow 0..255, i bubble kind.
static void draw_bubble(const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    static const int8_t cl[6][3] = {{0, 0, 5}, {-6, 3, 4}, {5, 4, 3}, {3, -6, 4}, {-4, -5, 3}, {7, -2, 2}};
    int n = op->i == DIVE_BUB_CLUSTER ? 6 : 1, glow_a = (int)op->b;
    for (int k = 0; k < n; ++k) {
        int cx16 = (int)(op->x * 16), cy16 = (int)(op->y * 16), r16 = (int)(op->a * 16);
        if (n > 1)
            cx16 += cl[k][0] * 16, cy16 += cl[k][1] * 16, r16 = cl[k][2] * 16;
        if (glow_a > 5)
            glow(y, x0, x1, cx16 >> 4, cy16 >> 4, r16 * 26 / 160, rgb565(140, 235, 255), glow_a, row);
        disc(y, x0, x1, cx16, cy16, r16, rgb565(190, 240, 255), 56, rgb565(225, 250, 255), 235, row);
        int hr16 = r16 * 26 / 100 < 13 ? 13 : r16 * 26 / 100;
        disc(y, x0, x1, cx16 - r16 * 38 / 100, cy16 - r16 * 38 / 100, hr16, 0xFFFF, 255, 0xFFFF, 0, row);
    }
}

// op: x centre, y screen centre, a radius, x2 pulse 0..1, y2 tentacle phase (0..255), b glow 0..255.
static void draw_jelly(dive_gfx_t* g, const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    const dive_obs_t* o = &g->d->obs[op->i];
    const uint8_t* c3 = kJelly[zone_of((int)o->by)][o->big ? 1 : 0];
    uint16_t col = rgb565(c3[0], c3[1], c3[2]);
    int cx = (int)op->x, sy = (int)op->y, R16 = (int)(op->a * 16);
    glow(y, x0, x1, cx, sy, R16 * 22 / 160, col, (int)op->b, row);
    int top16 = sy * 16 + 32, seg16 = R16 * 34 / 100, yc16 = y * 16 + 8;
    if (seg16 > 0 && yc16 >= top16 && yc16 < top16 + 5 * seg16) {  // tentacles
        int k16 = (yc16 - top16) * 16 / seg16;                       // 0..80
        int base = (int)op->y2;
        for (int i = 0; i < 4; ++i) {
            int ang = base + i * 41 + k16 * 37 / 160;               // +1 rad per tentacle, +0.9 rad per segment
            int sway16 = sin8[ang & 255] * 35 * k16 / (127 * 80);  // 2.2 px * k / 5
            int tx16 = cx * 16 - R16 * 6 / 10 + i * R16 * 4 / 10 + sway16;
            plot((tx16 + 8) >> 4, x0, x1, row, col, 178);
        }
    }
    int pulse = (int)(op->x2 * 256);
    int rw = (R16 * (256 + pulse * 12 / 100) >> 8) / 16, rh = (R16 * (218 - pulse * 15 / 100) >> 8) / 16;
    int a, b, dtop = sy + 2;
    if (y <= dtop && ellipse_span(y, cx, dtop, rw > 0 ? rw : 1, rh > 0 ? rh : 1, &a, &b)) {  // upper dome
        bool rim = y == dtop || y <= dtop - rh + 1;
        for (int x = a; x < b; ++x)
            plot(x, x0, x1, row, col, rim || x == a || x == b - 1 ? 242 : 128);
        int hx = cx - rw * 35 / 100, hy = dtop - rh * 55 / 100, ha, hb;
        if (ellipse_span(y, hx, hy, rw * 22 / 100 + 1, rh * 18 / 100 + 1, &ha, &hb))
            for (int x = ha; x < hb; ++x)
                plot(x, x0, x1, row, 0xFFFF, 140);
    }
}

// op: x, y body centre (screen), x2/y2 lure (screen), a mouth open 0..1, c body colour, i obstacle.
static void draw_angler(dive_gfx_t* g, const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    const dive_obs_t* o = &g->d->obs[op->i];
    int x = (int)op->x, sy = (int)op->y, f = o->face, lx = (int)op->x2, ly = (int)op->y2;
    int z = zone_of((int)o->by);
    uint16_t gc = rgb565(kGlow[z][0], kGlow[z][1], kGlow[z][2]);
    glow(y, x0, x1, lx, ly, 18, gc, 153, row);
    int er, eg, eb;
    grad(kEdge, 5, (int32_t)o->by, &er, &eg, &eb);
    uint16_t body = op->c, edge = rgb565(er, eg, eb);
    int sx0 = x + f * 6, sy0 = sy - 10, mx = x + f * 10, my = sy - 19;  // stalk via the control point
    for (int seg = 0; seg < 2; ++seg) {
        int ax = seg ? mx : sx0, ay = seg ? my : sy0, bx = seg ? lx : mx, by = seg ? ly : my;
        if ((y >= ay) != (y >= by) && by != ay)
            plot(ax + (y - ay) * (bx - ax) / (by - ay), x0, x1, row, edge, 204);
    }
    int tx[3] = {x - f * 15, x - f * 25, x - f * 25}, ty[3] = {sy, sy - 7, sy + 7};
    tri(y, x0, x1, tx, ty, body, 255, row);
    int a, b;
    if (ellipse_span(y, x, sy, 17, 12, &a, &b)) {
        bool er_row = y <= sy - 11 || y >= sy + 11;
        for (int px = a; px < b; ++px)
            plot(px, x0, x1, row, er_row || px == a || px == b - 1 ? edge : body, er_row ? 204 : 255);
    }
    int m6 = (int)(op->a * 6);
    int mx3[3] = {x + f * 17, x + f * 4, x + f * 16}, my3[3] = {sy - 1, sy + 2, sy + 3 + m6};
    tri(y, x0, x1, mx3, my3, rgb565(1, 3, 10), 255, row);
    if (y == sy || y == sy + 1)
        for (int k = 0; k < 4; ++k)
            plot(x + f * (15 - k * 3) + (y == sy + 1 ? f : 0), x0, x1, row, rgb565(238, 246, 255), 255);
    disc(y, x0, x1, lx * 16, ly * 16, 32, gc, 242, gc, 0, row);
    disc(y, x0, x1, (x + f * 8) * 16, (sy - 4) * 16, 27, rgb565(233, 247, 255), 255, 0, 0, row);
}

static void draw_nabo(dive_gfx_t* g, const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    // Inverse affine sampling of the decoded frame(s), 16.16 fixed point.
    const int cell = NABO_DIVE_CELL;
    int a = op->x0 > x0 ? op->x0 : x0, b = op->x1 < x1 ? op->x1 : x1;
    if (a >= b)
        return;
    float dy = y + 0.5f - g->nabo_y, dx = a + 0.5f - g->nabo_x;
    int32_t u = (int32_t)((g->inv[0] * dx + g->inv[1] * dy + NABO_DIVE_ANCHOR_X) * 65536);
    int32_t v = (int32_t)((g->inv[2] * dx + g->inv[3] * dy + NABO_DIVE_ANCHOR_Y) * 65536);
    int32_t du = (int32_t)(g->inv[0] * 65536), dv = (int32_t)(g->inv[2] * 65536);
    const uint8_t* cur = g->frame_px;
    int alpha = g->v->nabo_alpha;
    for (int x = a; x < b; ++x, u += du, v += dv) {
        int iu = u >> 16, iv = v >> 16;
        if ((unsigned)iu >= (unsigned)cell || (unsigned)iv >= (unsigned)cell)
            continue;
        uint16_t* p = &row[x - x0];
        uint8_t ci = cur[iv * cell + iu];
        if (ci)
            *p = blend565(*p, g->pal[ci], g->pal_a[ci] * alpha >> 8);
    }
}

// op: i kind, x/y centre or streak top (screen), a radius or length, b alpha 0..255.
static void draw_part(const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    int cx16 = (int)(op->x * 16), cy16 = (int)(op->y * 16), r16 = (int)(op->a * 16), al = (int)op->b;
    switch (op->i) {
        case DIVE_PART_BUBBLE:
        case DIVE_PART_RING:
            disc(y, x0, x1, cx16, cy16, r16, 0, 0, rgb565(225, 250, 255), al, row);
            break;
        case DIVE_PART_NEAR:
            disc(y, x0, x1, cx16, cy16, r16, 0, 0, rgb565(255, 227, 163), al, row);
            disc(y, x0, x1, cx16, cy16, r16 - 14, 0, 0, rgb565(255, 227, 163), al * 2 / 3, row);
            break;
        case DIVE_PART_STREAK:
            if (y >= (int)op->y && y < (int)(op->y + op->a))
                plot((int)op->x, x0, x1, row, rgb565(220, 245, 255), al);
            break;
        default:
            break;
    }
}

static void rect_row(const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    int top = (int)op->y, bot = (int)op->y2, l = (int)op->x, r = (int)op->x2, rad = op->i;
    if (y < top || y >= bot)
        return;
    int d = y < top + rad ? top + rad - y : y >= bot - rad ? y - (bot - rad) + 1 : 0, inset = 0;
    if (d > 0) {
        int q = rad * rad - d * d, s = 0;
        while (q > 0 && (s + 1) * (s + 1) <= q)
            ++s;
        inset = rad - s;
    }
    int a = l + inset, b = r - inset, al = (int)(op->b * 255);
    if (op->a > 0) {  // outline only
        if (y == top || y == bot - 1)
            for (int x = a; x < b; ++x)
                plot(x, x0, x1, row, op->c, al);
        else {
            plot(a, x0, x1, row, op->c, al);
            plot(b - 1, x0, x1, row, op->c, al);
        }
        return;
    }
    for (int x = a > x0 ? a : x0; x < (b < x1 ? b : x1); ++x)
        row[x - x0] = blend565(row[x - x0], op->c, al);
}

static void line_row(const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    int al = (int)(op->b * 255), ya = (int)op->y, yb = (int)op->y2, xa = (int)op->x, xb = (int)op->x2;
    if (ya == yb) {
        if (y != ya)
            return;
        int dash = (int)op->a;
        for (int x = xa; x < xb; ++x)
            if (dash <= 0 || ((x - xa) / dash) % 2 == 0)
                plot(x, x0, x1, row, op->c, al);
        return;
    }
    if ((y >= ya) == (y >= yb))
        return;
    plot(xa + (y - ya) * (xb - xa) / (yb - ya), x0, x1, row, op->c, al);
}

// op: x fill height (px), y pulse 0..255 (low air), a flash alpha, c colour, i flags (1 low, 2 track flash).
static void o2_row(const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    const int gx = 6, w = 5, top = 30, bot = DIVE_H - 14, len = bot - top;
    bool low = op->i & 1;
    int pulse = (int)op->y;
    if (y < op->y0 || y >= op->y1)
        return;
    fill(row, x0, x1, op->x0, op->x1, (uint16_t)op->x2);  // opaque groove
    if (low && y >= top - 3 && y < bot + 3)
        for (int x = gx - 3; x < gx + w + 3; ++x)
            plot(x, x0, x1, row, op->c, 41 + pulse * 31 / 255);
    if (y >= top && y < bot) {
        int inset = (y == top || y == bot - 1) ? 1 : 0;
        bool flash = op->i & 2;
        uint16_t track = flash ? rgb565(255, 90, 90) : rgb565(0, 10, 22);
        for (int x = gx + inset; x < gx + w - inset; ++x)
            plot(x, x0, x1, row, track, flash ? 115 : 128);
        plot(gx - 1 + inset, x0, x1, row, 0xFFFF, 56);
        plot(gx + w - inset, x0, x1, row, 0xFFFF, 56);
        int h = (int)op->x;
        if (y >= bot - h) {
            int a = low ? 191 + pulse / 4 : 255;
            for (int x = gx + inset; x < gx + w - inset; ++x)
                plot(x, x0, x1, row, op->c, a);
            if (y > bot - h + 2 && y < bot - 2)
                plot(gx + 1, x0, x1, row, 0xFFFF, 102);
            if (op->a > 0 && y < bot - h + 16)
                for (int x = gx + inset; x < gx + w - inset; ++x)
                    plot(x, x0, x1, row, 0xFFFF, (int)op->a);
        }
        for (int q = 1; q < 4; ++q)
            if (y == bot - len * q / 4)
                for (int x = gx; x < gx + w; ++x)
                    plot(x, x0, x1, row, rgb565(0, 10, 22), 153);
    }
    int cx16 = gx * 16 + w * 8;
    disc(y, x0, x1, cx16 - 8, 20 * 16, 64, 0, 0, 0xFFFF, 230, row);
    disc(y, x0, x1, cx16 + 54, 211, 34, 0, 0, 0xFFFF, 230, row);
}

static void profile_row(dive_gfx_t* g, const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    static const uint8_t cols[5][3] = {{0x7a, 0xd3, 0xec}, {0x2b, 0x86, 0xb9}, {0x35, 0x67, 0xb0},
                                       {0x6a, 0x49, 0xb8}, {0xc2, 0x7a, 0x33}};
    const int maxpx = 11000;
    int by = (int)op->y;
#define PX(p) (24 + ((int)(p) > maxpx ? 192 : (int)(p) < 0 ? 0 : (int)(p) * 192 / maxpx))
    if (y >= by && y < by + 4)
        for (int i = 0; i < DIVE_ZONES; ++i) {
            int a = PX(dive_zone_px[i]), b = i + 1 < DIVE_ZONES ? PX(dive_zone_px[i + 1]) : PX(maxpx);
            fill(row, x0, x1, a, b - 1, rgb565(cols[i][0], cols[i][1], cols[i][2]));
        }
    int mx = PX(g->d->y);
    if (y >= by - 8 && y < by - 2) {  // white marker for this run
        int hw = 4 - (y - (by - 8)) * 4 / 6;
        fill(row, x0, x1, mx - hw, mx + hw + 1, 0xFFFF);
    }
    if (op->a > 0 && y >= by - 3 && y < by + 7)  // amber tick for the previous best
        plot(PX(op->a), x0, x1, row, rgb565(255, 181, 71), 255);
#undef PX
}

static void gauge_row(const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    static const int stops[DIVE_ZONES] = {0, 160, 380, 620, 860};  // per mille
    int gx = DIVE_W - 16;
    if (y >= TITLE_SURF + 6 && y < DIVE_H - 8)
        plot(gx, x0, x1, row, 0xFFFF, 71);
    for (int i = 1; i < DIVE_ZONES; ++i)
        if (y == TITLE_SURF + stops[i] * (DIVE_H - TITLE_SURF) / 1000)
            for (int x = gx - 3; x < gx + 1; ++x)
                plot(x, x0, x1, row, 0xFFFF, 115);
    if (op->a > 0) {  // best depth marker (op->a = screen y)
        int d = y - (int)op->a;
        if (d > -4 && d < 4)
            fill(row, x0, x1, gx + 1 + (d < 0 ? -d : d) * 5 / 4, gx + 7, rgb565(255, 181, 71));
    }
}

static void vent_row(dive_gfx_t* g, const dive_vent_t* v, int y, int x0, int x1, uint16_t* row) {
    int sy = (int)(v->y - g->cam), x = (int)(v->x + v->side * 1.5f);
    int z = zone_of((int)v->y);
    uint16_t gc = rgb565(kGlow[z][0], kGlow[z][1], kGlow[z][2]);
    glow(y, x0, x1, x, sy, 14, gc, 115, row);
    int wr, wg, wb, er, eg, eb, a, b;
    grad(kWall, 5, (int32_t)v->y, &wr, &wg, &wb);
    grad(kEdge, 5, (int32_t)v->y, &er, &eg, &eb);
    if (ellipse_span(y, x, sy, 7, 5, &a, &b))
        for (int px = a; px < b; ++px)
            plot(px, x0, x1, row, mixc(wr, wg, wb, er, eg, eb, 64), 255);
    if (ellipse_span(y, x - v->side * 3, sy - 1, 3, 2, &a, &b))
        for (int px = a; px < b; ++px)
            plot(px, x0, x1, row, gc, 230);
}

void dive_draw_op(dive_gfx_t* g, const dive_op_t* op, int y, int x0, int x1, uint16_t* row) {
    if (y < op->y0 || y >= op->y1 || x1 <= op->x0 || x0 >= op->x1)
        return;
    switch (op->kind) {
        case OP_BUBBLE:
            draw_bubble(op, y, x0, x1, row);
            break;
        case OP_JELLY:
            draw_jelly(g, op, y, x0, x1, row);
            break;
        case OP_ANGLER:
            draw_angler(g, op, y, x0, x1, row);
            break;
        case OP_GLOW:
            glow(y, x0, x1, (int)op->x, (int)op->y, (int)op->a, op->c, (int)(op->b * 255), row);
            break;
        case OP_NABO:
            draw_nabo(g, op, y, x0, x1, row);
            break;
        case OP_PART:
            draw_part(op, y, x0, x1, row);
            break;
        case OP_TEXT:
            dive_text_row(&g->layouts[op->i], y, x0, x1, row);
            break;
        case OP_SHADOW:
            dive_text_row_ex(&g->layouts[op->i], y, x0, x1, row, 1, 1, rgb565(0, 16, 32), 115);
            break;
        case OP_RECT:
            rect_row(op, y, x0, x1, row);
            break;
        case OP_LINE:
            line_row(op, y, x0, x1, row);
            break;
        case OP_O2:
            o2_row(op, y, x0, x1, row);
            break;
        case OP_DIM: {
            uint16_t ink = rgb565(2, 6, 13);
            int a = (int)(op->b * 255);
            for (int x = x0; x < x1; ++x)
                row[x - x0] = blend565(row[x - x0], ink, a);
            break;
        }
        case OP_VENT:
            vent_row(g, &g->d->vents[op->i], y, x0, x1, row);
            break;
        case OP_PROFILE:
            profile_row(g, op, y, x0, x1, row);
            break;
        case OP_GAUGE:
            gauge_row(op, y, x0, x1, row);
            break;
        default:
            break;
    }
}
