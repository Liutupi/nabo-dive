#include "nabo_dive_model.h"
#include <math.h>
#include <string.h>

// Rules match the web prototype (game-art/dive/prototype/index.html).
#define HIT_COST 25.0f
#define ANGLER_COST 35.0f
#define NEAR_BONUS 4.0f
#define LAST_BREATH 1.5f
#define CHEST_R 7.0f
#define HEAD_R 7.5f
#define HEAD_DX 9.8f   // head centre relative to the chest anchor (left-facing art)
#define HEAD_DY 12.6f

const float dive_zone_px[DIVE_ZONES] = {0, 900, 3200, 6200, 9500};
const int dive_zone_m[DIVE_ZONES] = {0, 200, 1000, 4000, 6000};
static const float zone_drain[DIVE_ZONES] = {5, 6, 7, 8, 9};
static const float jelly_density[DIVE_ZONES] = {0.16f, 0.42f, 0.52f, 0.6f, 0.66f};
static const float angler_density[DIVE_ZONES] = {0, 0, 0.12f, 0.2f, 0.26f};
static const uint8_t bubble_value[4] = {8, 20, 40, 5};
static const float bubble_radius[4] = {4, 7, 10, 3.5f};
enum { N_WIDTH, N_PINCH, N_CENTER, N_CENTER2, N_EDGE, N_STRATA, N_FAR1, N_FAR2 };

static inline float clampf(float v, float a, float b) { return v < a ? a : v > b ? b : v; }
static inline float lerpf(float a, float b, float t) { return a + (b - a) * t; }
static inline float smoothf(float t) { return t * t * (3 - 2 * t); }

static float rnd(uint32_t* s) {  // mulberry32, same stream as the prototype
    uint32_t t = (*s += 0x6D2B79F5u);
    t = (t ^ (t >> 15)) * (1u | t);
    t = (t + ((t ^ (t >> 7)) * (61u | t))) ^ t;
    return (float)((t ^ (t >> 14)) >> 8) / 16777216.0f;
}
static float fx_rnd(dive_t* d) {  // cosmetic randomness; does not touch the world stream
    static uint32_t s = 0x9E3779B9u;
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    (void)d;
    return (float)(s >> 8) / 16777216.0f;
}
static float noise(const dive_t* d, int table, float x) {
    float fl = floorf(x);
    int i = (int)fl;
    float f = x - fl;
    float a = d->noise[table][i & (DIVE_NOISE - 1)] / 127.0f;
    float b = d->noise[table][(i + 1) & (DIVE_NOISE - 1)] / 127.0f;
    return a + (b - a) * smoothf(f);
}

int dive_zone_of(float px) {
    int z = 0;
    for (int i = 1; i < DIVE_ZONES; ++i)
        if (px >= dive_zone_px[i])
            z = i;
    return z;
}
float dive_depth_m(float px) {
    if (px <= 0)
        return 0;
    for (int i = 1; i < DIVE_ZONES; ++i)
        if (px < dive_zone_px[i])
            return lerpf(dive_zone_m[i - 1], dive_zone_m[i],
                         (px - dive_zone_px[i - 1]) / (dive_zone_px[i] - dive_zone_px[i - 1]));
    return 6000 + (px - 9500) * 0.8f;
}
static float base_vy(float px) { return lerpf(76, 98, clampf(px / 9500, 0, 1)); }

void dive_corridor(const dive_t* d, float y, float* lo, float* hi) {
    float yy = y < 0 ? 0 : y, k = clampf(yy / 9500, 0, 1);
    float w = lerpf(188, 104, k) + noise(d, N_WIDTH, yy / 240) * 18 * (0.6f + k);
    if (yy > 1000) {
        float p = noise(d, N_PINCH, yy / 520);
        if (p > 0.45f)
            w -= (p - 0.45f) / 0.55f * lerpf(26, 46, k);
    }
    if (w < 66)
        w = 66;
    float c = 120 + noise(d, N_CENTER, yy / 360) * lerpf(16, 56, k) + noise(d, N_CENTER2, yy / 120) * 5;
    float l = c - w / 2, r = c + w / 2;
    if (l < 8) {
        r += 8 - l;
        l = 8;
    }
    if (r > 232) {
        l -= r - 232;
        r = 232;
    }
    l += noise(d, N_EDGE, yy / 13) * 2.4f;
    r += noise(d, N_EDGE, yy / 13 + 71.3f) * 2.4f;
    if (y < 300) {
        float o = smoothf(1 - clampf(y / 300, 0, 1));
        l -= o * 90;
        r += o * 90;
    }
    *lo = l;
    *hi = r;
}
void dive_far(const dive_t* d, float y, float l, float r, float* fl, float* fr) {
    float yy = y < 0 ? 0 : y;
    *fl = l + 3 + (noise(d, N_FAR1, yy / 64) + 1) * 5;
    *fr = r - 3 - (noise(d, N_FAR2, yy / 64) + 1) * 5;
}
float dive_strata(const dive_t* d, float y) { return noise(d, N_STRATA, y / 9); }

void dive_head(const dive_t* d, float* x, float* y) {
    *x = d->x + HEAD_DX * d->face;
    *y = d->y + HEAD_DY;
}

static void add_text(dive_t* d, uint8_t kind, int value, float x, float y) {
    for (int i = 0; i < DIVE_MAX_TEXTS; ++i)
        if (!d->texts[i].alive) {
            d->texts[i] = (dive_text_t){true, kind, (int16_t)value, x, y, 0};
            return;
        }
}
static dive_part_t* add_part(dive_t* d, uint8_t kind) {
    for (int i = 0; i < DIVE_MAX_PARTS; ++i)
        if (!d->parts[i].alive) {
            memset(&d->parts[i], 0, sizeof(dive_part_t));
            d->parts[i].alive = true;
            d->parts[i].kind = kind;
            return &d->parts[i];
        }
    return NULL;
}
static void bubble_part(dive_t* d, float x, float y, float vx, float vy, float r, float life) {
    dive_part_t* p = add_part(d, DIVE_PART_BUBBLE);
    if (p) {
        p->x = x, p->y = y, p->vx = vx, p->vy = vy, p->r = r, p->life = p->max = life;
        p->ph = fx_rnd(d) * 6;
    }
}
static void burst(dive_t* d, float x, float y, int count) {
    for (int i = 0; i < count; ++i) {
        float a = fx_rnd(d) * 6.2831853f, s = 30 + fx_rnd(d) * 45;
        bubble_part(d, x, y, cosf(a) * s, sinf(a) * s - 10, 1 + fx_rnd(d) * 2, 0.9f);
    }
}

void dive_reset(dive_t* d, uint32_t seed, float best_px) {
    memset(d, 0, sizeof(*d));
    d->seed = d->rng = seed;
    for (int t = 0; t < 8; ++t)
        for (int i = 0; i < DIVE_NOISE; ++i)
            d->noise[t][i] = (int8_t)lroundf((rnd(&d->rng) * 2 - 1) * 127);
    d->phase = DIVE_PLAY;
    d->x = 84;
    d->y = 0;
    d->vy = 24;
    d->dir = d->face = -1;
    d->o2 = DIVE_O2_MAX;
    d->cam_y = -104;
    d->next_bubble_y = 260;
    d->last_pick = -9;
    d->toast_zone = -1;
    d->best_px = best_px;
}

uint32_t dive_take_events(dive_t* d) {
    uint32_t e = d->events;
    d->events = 0;
    return e;
}

/* ---------- generation ---------- */

static void place_obstacle(dive_t* d, int kind, float y) {
    float l, r;
    dive_corridor(d, y, &l, &r);
    bool big = kind == DIVE_ANGLER || rnd(&d->rng) < 0.35f;
    float rad = kind == DIVE_ANGLER ? 15 : big ? 13 : 9;
    float amp = kind == DIVE_ANGLER ? 26 : 10 + rnd(&d->rng) * 8;
    if ((r - l) - 2 * (rad + amp) < 52)
        return;
    for (int tries = 0; tries < 6; ++tries) {
        float x = lerpf(l + rad + amp + 4, r - rad - amp - 4, rnd(&d->rng));
        float gl = x - amp - rad - l, gr = r - (x + amp + rad);
        if ((gl > gr ? gl : gr) < 44)
            continue;
        bool crowded = false;
        for (int i = 0; i < DIVE_MAX_OBS; ++i)
            if (d->obs[i].alive && fabsf(d->obs[i].by - y) < 64 && fabsf(d->obs[i].bx - x) < 60)
                crowded = true;
        if (crowded)
            continue;
        for (int i = 0; i < DIVE_MAX_OBS; ++i)
            if (!d->obs[i].alive) {
                d->obs[i] = (dive_obs_t){.alive = true, .kind = (uint8_t)kind, .big = big, .face = 1,
                                         .bx = x, .by = y, .x = x, .y = y, .rad = rad, .amp = amp,
                                         .ph = rnd(&d->rng) * 6.2831853f,
                                         .sp = kind == DIVE_ANGLER ? 0.5f : 0.7f + rnd(&d->rng) * 0.4f,
                                         .min_gap = 1e9f};
                return;
            }
        return;
    }
}

static void gen_chunk(dive_t* d, const dive_tune_t* tune, float y0) {
    int z = dive_zone_of(y0);
    if (y0 < 420)
        return;
    float jd = jelly_density[z] * tune->obstacles;
    if (rnd(&d->rng) < jd)
        place_obstacle(d, DIVE_JELLY, y0 + rnd(&d->rng) * 160);
    if (jd > 1 && rnd(&d->rng) < jd - 1)
        place_obstacle(d, DIVE_JELLY, y0 + rnd(&d->rng) * 160);
    if (rnd(&d->rng) < angler_density[z] * tune->obstacles)
        place_obstacle(d, DIVE_ANGLER, y0 + rnd(&d->rng) * 160);
    if (z >= 2 && rnd(&d->rng) < 0.09f) {
        float y = y0 + rnd(&d->rng) * 160, l, r;
        dive_corridor(d, y, &l, &r);
        int8_t side = rnd(&d->rng) < 0.5f ? -1 : 1;
        for (int i = 0; i < DIVE_MAX_VENTS; ++i)
            if (!d->vents[i].alive) {
                d->vents[i] = (dive_vent_t){true, side, side < 0 ? l : r, y, 0};
                break;
            }
    }
}

static float bubble_spacing(const dive_tune_t* tune, float y) {
    float drain = zone_drain[dive_zone_of(y)] * tune->drain;
    float vy = base_vy(y) * tune->speed;
    float p = lerpf(0.48f, 0.85f, clampf(y / 9500, 0, 1));  // share to collect to break even
    return clampf(13.6f * (vy + 26) * p / drain / tune->bubbles, 60, 360);
}

static void spawn_bubble(dive_t* d, uint8_t kind, float x, float y, float vy) {
    for (int i = 0; i < DIVE_MAX_BUBBLES; ++i)
        if (!d->bubbles[i].alive) {
            d->bubbles[i] = (dive_bubble_t){true, kind, bubble_value[kind], x, x, y, bubble_radius[kind],
                                            vy, fx_rnd(d) * 6.2831853f};
            return;
        }
}

static void place_bubble(dive_t* d, const dive_tune_t* tune) {
    float y = d->next_bubble_y, l, r, x;
    dive_corridor(d, y, &l, &r);
    float roll = rnd(&d->rng);
    uint8_t kind = DIVE_BUB_SMALL;
    if (roll < 0.07f) {
        kind = DIVE_BUB_CLUSTER;
        const dive_obs_t* near = NULL;
        for (int i = 0; i < DIVE_MAX_OBS && !near; ++i)
            if (d->obs[i].alive && fabsf(d->obs[i].by - y) < 110)
                near = &d->obs[i];
        if (near) {
            float side = near->bx - l > r - near->bx ? -1 : 1;
            x = near->bx + side * (near->rad + near->amp + 16);
        } else
            x = rnd(&d->rng) < 0.5f ? l + 20 : r - 20;
    } else if (roll < 0.35f) {
        kind = DIVE_BUB_LARGE;
        x = rnd(&d->rng) < 0.5f ? l + 16 : r - 16;
    } else
        x = lerpf(l + 18, r - 18, rnd(&d->rng));
    x = clampf(x, l + 12, r - 12);
    spawn_bubble(d, kind, x, y, -(22 + rnd(&d->rng) * 10));
    d->next_bubble_y += bubble_spacing(tune, y) * lerpf(0.7f, 1.3f, rnd(&d->rng));
}

/* ---------- events ---------- */

static void set_dir(dive_t* d, int8_t dir) {
    if (d->dir != dir) {
        d->dir = dir;
        d->turn_t = DIVE_TURN_T;
    }
}
static void start_last_breath(dive_t* d) {
    d->lb = true;
    d->lb_t = LAST_BREATH;
    d->events |= DIVE_EV_LAST_BREATH;
}
static void hit(dive_t* d, float cost, int8_t side) {
    if (d->inv > 0)
        return;
    d->o2 = d->o2 - cost < 0 ? 0 : d->o2 - cost;
    d->stun = 0.45f;
    d->inv = 1.25f;
    d->kx = side * 80.0f;
    d->turn_t = 0;  // the hit clip shows the knock, no turn
    d->face = d->dir;
    d->shake_t = 0.25f;
    d->chain = 0;
    d->act = DIVE_ACT_HIT;
    d->act_t = 0.45f;
    ++d->stat_hits;
    burst(d, d->x, d->y, 10);
    add_text(d, DIVE_TEXT_MINUS, (int)cost, d->x, d->y - 20);
    d->events |= DIVE_EV_HIT;
    if (d->o2 <= 0 && !d->lb)
        start_last_breath(d);
}
static void near_miss(dive_t* d) {
    ++d->stat_near;
    d->o2 = d->o2 + NEAR_BONUS > DIVE_O2_MAX ? DIVE_O2_MAX : d->o2 + NEAR_BONUS;
    d->lb = false;
    d->slow_t = 0.22f;
    dive_part_t* p = add_part(d, DIVE_PART_NEAR);
    if (p)
        p->life = p->max = 0.35f, p->r = 10;
    add_text(d, DIVE_TEXT_NEAR, (int)NEAR_BONUS, d->x, d->y - 22);
    if (d->act != DIVE_ACT_HIT)
        d->act = DIVE_ACT_NEAR, d->act_t = 0.3f;
    d->events |= DIVE_EV_NEAR;
}
static void collect(dive_t* d, dive_bubble_t* b) {
    d->o2 = d->o2 + b->value > DIVE_O2_MAX ? DIVE_O2_MAX : d->o2 + b->value;
    ++d->stat_bubbles;
    d->chain = d->t - d->last_pick < 2.5f ? d->chain + 1 : 0;
    d->last_pick = d->t;
    d->o2_flash = 0.3f;
    d->gulp_t = 0.22f;
    if (d->act != DIVE_ACT_HIT)
        d->act = DIVE_ACT_GULP, d->act_t = 0.25f;
    dive_part_t* p = add_part(d, DIVE_PART_RING);
    if (p)
        p->x = b->x, p->y = b->y, p->r = b->r, p->life = p->max = 0.28f;
    for (int i = 0; i < 3; ++i)
        bubble_part(d, b->x, b->y, (fx_rnd(d) - 0.5f) * 50, -fx_rnd(d) * 40, 0.8f + fx_rnd(d), 0.5f);
    if (b->kind == DIVE_BUB_CLUSTER)
        add_text(d, DIVE_TEXT_PLUS, b->value, b->x, b->y - 12);
    d->events |= DIVE_EV_BUBBLE;
    if (d->lb) {
        d->lb = false;
        d->lb_t = 0;
        add_text(d, DIVE_TEXT_RESCUE, 0, d->x, d->y - 24);
        d->events |= DIVE_EV_RESCUE;
    }
}
static void die(dive_t* d) {
    d->phase = DIVE_DYING;
    d->die_t = 0;
    d->lb = false;
    if (d->dashing) {
        d->dashing = false;
        d->events |= DIVE_EV_DASH_OFF;
    }
    if (d->y > d->best_px)
        d->new_record = true;
    d->events |= DIVE_EV_DIE;
}

/* ---------- step ---------- */

static void step_nabo(dive_t* d, const dive_tune_t* tune, float dt, bool flip, bool dash_held) {
    int z = dive_zone_of(d->y);
    if (z > d->zone) {
        d->zone = z;
        d->toast_zone = z;
        d->toast_t = 0;
        d->events |= DIVE_EV_ZONE;
    }
    d->stun = d->stun - dt > 0 ? d->stun - dt : 0;
    d->inv = d->inv - dt > 0 ? d->inv - dt : 0;
    if (d->turn_t > 0) {
        d->turn_t = d->turn_t - dt > 0 ? d->turn_t - dt : 0;
        if (d->turn_t <= DIVE_TURN_T / 2)
            d->face = d->dir;
    } else
        d->face = d->dir;
    if (flip) {
        if (d->stun > 0)
            d->queued_flip = true;
        else {
            set_dir(d, -d->dir);
            ++d->flips;
            d->events |= DIVE_EV_FLIP;
        }
    }
    if (d->stun == 0 && d->queued_flip) {
        d->queued_flip = false;
        set_dir(d, -d->dir);
        ++d->flips;
        d->events |= DIVE_EV_FLIP;
    }

    bool dash = dash_held && d->stun == 0;
    d->dash_k += ((dash ? 1.0f : 0.0f) - d->dash_k) * fminf(1, dt * (dash ? 6 : 4));
    if (dash && !d->dashing) {
        d->dashing = true;
        d->events |= DIVE_EV_DASH_ON;
    } else if (!dash && d->dashing) {
        d->dashing = false;
        d->events |= DIVE_EV_DASH_OFF;
    }
    if (d->dash_k > 0.3f) {
        d->streak_t -= dt;
        while (d->streak_t <= 0) {
            d->streak_t += 0.025f;
            float y = d->cam_y + 30 + fx_rnd(d) * (DIVE_H - 30), l, r;
            dive_corridor(d, y, &l, &r);
            dive_part_t* p = add_part(d, DIVE_PART_STREAK);
            if (!p)
                break;
            p->x = lerpf(l + 4, r - 4, fx_rnd(d));
            p->y = y;
            p->len = 10 + fx_rnd(d) * 18;
            p->life = p->max = 0.3f;
        }
    }

    float base = base_vy(d->y) * tune->speed;
    float tvy = d->stun > 0 ? base * 0.35f : base * (dash ? 2 : 1);
    d->vy += (tvy - d->vy) * fminf(1, dt * 4.5f);
    float tvx = d->stun > 0 ? d->kx : d->dir * base * 0.84f;
    d->vx += (tvx - d->vx) * fminf(1, dt * (d->stun > 0 ? 4 : 13));
    d->kx *= powf(0.05f, dt);
    d->x += d->vx * dt;
    d->y += d->vy * dt;

    // Chest and head circles against the rock walls.
    float hx, hy;
    dive_head(d, &hx, &hy);
    const float cx[2] = {d->x, hx}, cy[2] = {d->y + 1, hy}, cr[2] = {CHEST_R, HEAD_R};
    for (int i = 0; i < 2; ++i) {
        float l, r;
        dive_corridor(d, cy[i], &l, &r);
        if (cx[i] - cr[i] < l) {
            d->x += l - (cx[i] - cr[i]);
            d->vx = fabsf(d->vx) * 0.4f;
            set_dir(d, 1);
            hit(d, HIT_COST, 1);
            break;
        }
        if (cx[i] + cr[i] > r) {
            d->x -= cx[i] + cr[i] - r;
            d->vx = -fabsf(d->vx) * 0.4f;
            set_dir(d, -1);
            hit(d, HIT_COST, -1);
            break;
        }
    }
    dive_head(d, &hx, &hy);
    const float px[2] = {d->x, hx}, py[2] = {d->y + 1, hy};
    for (int i = 0; i < DIVE_MAX_OBS; ++i) {
        dive_obs_t* o = &d->obs[i];
        if (!o->alive)
            continue;
        float gap = 1e9f, dx = 0;
        for (int c = 0; c < 2; ++c) {
            float g = hypotf(o->x - px[c], o->y - py[c]) - cr[c] - o->rad;
            if (g < gap)
                gap = g, dx = o->x - px[c];
        }
        if (gap < o->min_gap)
            o->min_gap = gap;
        if (gap < 0 && d->inv <= 0) {
            o->hit_me = true;
            int8_t side = dx > 0 ? -1 : 1;
            set_dir(d, side);
            hit(d, o->kind == DIVE_ANGLER ? ANGLER_COST : HIT_COST, side);
        }
        if (!o->passed && o->y + o->rad < d->y - 14) {
            o->passed = true;
            if (!o->hit_me && o->min_gap < 10)
                near_miss(d);
        }
    }

    float drain = zone_drain[z] * tune->drain * (dash ? 1.5f : 1);
    if (!d->lb) {
        d->o2 -= drain * dt;
        if (d->o2 <= 0) {
            d->o2 = 0;
            start_last_breath(d);
        }
    } else {
        d->lb_t -= dt;
        if (d->lb_t <= 0) {
            die(d);
            return;
        }
    }
    if (d->o2 < 30 || d->lb) {
        d->heart_t -= dt;
        if (d->heart_t <= 0) {
            d->events |= DIVE_EV_HEART;
            d->heart_t = d->lb ? 0.38f : lerpf(0.45f, 0.95f, d->o2 / 30);
        }
    } else
        d->heart_t = 0;

    if (d->best_px > 0 && !d->passed_best && d->y > d->best_px) {
        d->passed_best = true;
        d->toast_zone = DIVE_ZONES;
        d->toast_t = 0;
        d->act = DIVE_ACT_RECORD;
        d->act_t = 0.6f;
        d->events |= DIVE_EV_RECORD;
    }
    if (d->act_t > 0 && (d->act_t -= dt) <= 0)
        d->act = DIVE_ACT_NONE;
    if (d->gulp_t > 0)
        d->gulp_t -= dt;

    d->trail_t -= dt;
    if (d->trail_t <= 0) {
        d->trail_t = d->dash_k > 0.5f ? 0.05f : d->o2 < 10 ? 0.09f : 0.28f;
        float sp = hypotf(d->vx, d->vy);
        if (sp < 1)
            sp = 1;
        float mx, my;
        if (d->dash_k > 0.5f)
            mx = d->x - d->vx / sp * 26, my = d->y - d->vy / sp * 26;
        else
            dive_head(d, &mx, &my);
        bubble_part(d, mx, my, (fx_rnd(d) - 0.5f) * 10, -12, 0.8f + fx_rnd(d) * 1.2f, 1.2f);
    }
    float target = d->y - lerpf(DIVE_SCREEN_Y, DIVE_DASH_SCREEN_Y, d->dash_k);
    d->cam_y = d->t < 1.2f ? d->cam_y + (target - d->cam_y) * fminf(1, dt * 7) : target;
}

static void step_world(dive_t* d, const dive_tune_t* tune, float dt) {
    while (d->gen_y < d->cam_y + DIVE_H + 240) {
        gen_chunk(d, tune, d->gen_y);
        d->gen_y += 160;
    }
    while (d->next_bubble_y < d->cam_y + DIVE_H + 220)
        place_bubble(d, tune);
    float t = d->t;
    for (int i = 0; i < DIVE_MAX_OBS; ++i) {
        dive_obs_t* o = &d->obs[i];
        if (!o->alive)
            continue;
        if (o->by < d->cam_y - 90) {
            o->alive = false;
            continue;
        }
        o->x = o->bx + sinf(t * o->sp + o->ph) * o->amp;
        if (o->kind == DIVE_JELLY)
            o->y = o->by + sinf(t * 2.2f + o->ph) * 3;
        else
            o->face = cosf(t * o->sp + o->ph) > 0 ? 1 : -1;
    }
    for (int i = 0; i < DIVE_MAX_VENTS; ++i) {
        dive_vent_t* v = &d->vents[i];
        if (!v->alive)
            continue;
        if (v->y < d->cam_y - 40) {
            v->alive = false;
            continue;
        }
        if (v->y > d->cam_y + DIVE_H + 40 || (v->t -= dt) > 0)
            continue;
        v->t = 0.34f;
        spawn_bubble(d, DIVE_BUB_VENT, v->x - v->side * 8, v->y - 4, -40 - fx_rnd(d) * 8);
    }
    bool playing = d->phase == DIVE_PLAY;
    float mx = 0, my = 0;
    if (playing)
        dive_head(d, &mx, &my);
    for (int i = 0; i < DIVE_MAX_BUBBLES; ++i) {
        dive_bubble_t* b = &d->bubbles[i];
        if (!b->alive)
            continue;
        b->y += b->vy * dt;
        float l, r;
        dive_corridor(d, b->y, &l, &r);
        b->bx = clampf(b->bx, l + b->r + 2, r - b->r - 2);
        b->x = b->bx + sinf(t * 3 + b->ph) * 1.8f;
        if (playing) {
            float dx = mx - b->x, dy = my - b->y, dist = hypotf(dx, dy);
            if (dist < 26) {
                b->bx += dx * dt * 7;
                b->y += dy * dt * 7;
            }
            float chest = hypotf(d->x - b->x, d->y + 1 - b->y);
            if (dist < HEAD_R + 0.5f + b->r + 3 || chest < CHEST_R + b->r + 2) {
                collect(d, b);
                b->alive = false;
                continue;
            }
        }
        if (b->y < d->cam_y - 30 || b->y < 3)
            b->alive = false;
    }
    for (int i = 0; i < DIVE_MAX_PARTS; ++i) {
        dive_part_t* p = &d->parts[i];
        if (!p->alive)
            continue;
        if ((p->life -= dt) <= 0) {
            p->alive = false;
            continue;
        }
        p->x += p->vx * dt;
        p->y += p->vy * dt;
        if (p->kind == DIVE_PART_BUBBLE) {
            p->vy -= 30 * dt;
            p->vx *= powf(0.2f, dt);
            p->x += sinf((p->life + p->ph) * 9) * 0.15f;
        }
    }
    for (int i = 0; i < DIVE_MAX_TEXTS; ++i) {
        dive_text_t* x = &d->texts[i];
        if (x->alive && (x->t += dt) > 0.9f)
            x->alive = false;
        else if (x->alive)
            x->y -= 14 * dt;
    }
    if (d->toast_zone >= 0 && (d->toast_t += dt) > 2.4f)
        d->toast_zone = -1;
    if (d->shake_t > 0)
        d->shake_t -= dt;
    if (d->o2_flash > 0)
        d->o2_flash -= dt;
}

void dive_step(dive_t* d, const dive_tune_t* tune, float dt, bool flip, bool dash) {
    if (d->slow_t > 0) {  // near-miss slow motion
        d->slow_t -= dt;
        dt *= 0.45f;
    }
    d->t += dt;
    if (d->phase == DIVE_PLAY)
        step_nabo(d, tune, dt, flip, dash);
    else if (d->phase == DIVE_DYING) {
        d->die_t += dt;
        d->vy = -16;
        d->vx = sinf(d->t * 1.3f) * 6;
        d->x += d->vx * dt;
        d->y += d->vy * dt;
        if (d->die_t > 1.6f)
            d->phase = DIVE_OVER;
    }
    step_world(d, tune, dt);
}
