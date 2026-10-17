#include "nabo_dive_anim.h"
#include <math.h>
#include <string.h>

#define FADE_T 0.09f
#define CANON 0.69866f  // atan2(1, -0.84) - pi/2: art heads down-left, ~50 deg below horizontal
static const int kTurnSeq[5] = {0, 1, 2, 1, 0};  // 3 frames, then the first two mirrored

static float clampf(float v, float a, float b) { return v < a ? a : v > b ? b : v; }
static const nabo_dive_clip_t* clip(int id) { return &nabo_dive_clips[id]; }
static bool idle_clip(int c) { return c == NABO_DIVE_CLIP_SWIM || c == NABO_DIVE_CLIP_LOWAIR; }

void dive_anim_reset(dive_anim_t* a) {
    memset(a, 0, sizeof(*a));
    a->clip = NABO_DIVE_CLIP_SWIM;
    a->over = -1;
    a->fade_frame = -1;
}

static int frame_of(const dive_anim_t* a, const dive_t* d, dive_screen_t screen, bool* done) {
    if (a->over >= 0) {
        const nabo_dive_clip_t* c = clip(a->over);
        int f = (int)(a->over_t * c->fps);
        *done = f >= c->count;
        return c->first + (f < c->count ? f : c->count - 1);
    }
    const nabo_dive_clip_t* c = clip(a->clip);
    float fps = c->fps;
    if (a->clip == NABO_DIVE_CLIP_SWIM && screen == DIVE_SCREEN_TITLE)
        fps *= 0.5f;
    int f = (int)(a->clip_t * fps);
    *done = !c->loop && f >= c->count;
    (void)d;
    return c->first + (c->loop ? f % c->count : (f < c->count ? f : c->count - 1));
}

static void start_fade(dive_anim_t* a, float scale) {
    a->fade_frame = a->last_frame;
    a->fade_t = FADE_T * scale;
}
static void switch_clip(dive_anim_t* a, int id, bool seamless) {
    if (!seamless)
        start_fade(a, 1);
    a->clip = id;
    a->clip_t = 0;
}
static void play_over(dive_anim_t* a, int id) {
    if (a->over == NABO_DIVE_CLIP_OUT || (a->over == NABO_DIVE_CLIP_HIT && id == NABO_DIVE_CLIP_GULP))
        return;
    start_fade(a, 0.6f);
    a->over = id;
    a->over_t = 0;
}

void dive_anim_update(dive_anim_t* a, const dive_t* d, dive_screen_t screen, bool dash_held, uint32_t events,
                      float dt, dive_view_t* v) {
    bool play = screen == DIVE_SCREEN_PLAY && d->phase == DIVE_PLAY;
    if (events & DIVE_EV_HIT)
        play_over(a, NABO_DIVE_CLIP_HIT);
    if ((events & DIVE_EV_BUBBLE) && idle_clip(a->clip))
        play_over(a, NABO_DIVE_CLIP_GULP);
    if (events & DIVE_EV_DIE)
        play_over(a, NABO_DIVE_CLIP_OUT);
    if (screen != DIVE_SCREEN_PAUSE) {
        a->clip_t += dt;
        if (a->over >= 0)
            a->over_t += dt;
    }
    if (a->fade_t > 0 && (a->fade_t -= dt) <= 0)
        a->fade_frame = -1;

    bool done;
    int f = frame_of(a, d, screen, &done);
    if (a->over >= 0) {
        if (done && a->over != NABO_DIVE_CLIP_OUT) {
            int finished = a->over;
            a->over = -1;
            if (idle_clip(a->clip)) {
                a->clip = (play && (d->o2 < 30 || d->lb)) ? NABO_DIVE_CLIP_LOWAIR : NABO_DIVE_CLIP_SWIM;
                a->clip_t = 0;
                if (finished != NABO_DIVE_CLIP_HIT)  // hit's last frame leads into swim frame 1
                    start_fade(a, 1);
            }
        }
    } else {
        bool want = play && dash_held && d->stun == 0;
        int base = (play && (d->o2 < 30 || d->lb)) ? NABO_DIVE_CLIP_LOWAIR : NABO_DIVE_CLIP_SWIM;
        int rel = f - clip(a->clip)->first;
        if (idle_clip(a->clip) && want)
            switch_clip(a, NABO_DIVE_CLIP_DASH_IN, a->clip == NABO_DIVE_CLIP_SWIM && rel == 0);
        else if (idle_clip(a->clip)) {
            if (base != a->clip)
                switch_clip(a, base, false);
        } else if (a->clip == NABO_DIVE_CLIP_DASH_IN && done)
            switch_clip(a, want ? NABO_DIVE_CLIP_DASH : NABO_DIVE_CLIP_DASH_OUT, want);
        else if (a->clip == NABO_DIVE_CLIP_DASH && !want)
            switch_clip(a, NABO_DIVE_CLIP_DASH_OUT, rel == 0);
        else if (a->clip == NABO_DIVE_CLIP_DASH_OUT && want)
            switch_clip(a, NABO_DIVE_CLIP_DASH_IN, false);
        else if (a->clip == NABO_DIVE_CLIP_DASH_OUT && done)
            switch_clip(a, base, true);
        if (!play && !idle_clip(a->clip))
            switch_clip(a, NABO_DIVE_CLIP_SWIM, false);
    }
    f = frame_of(a, d, screen, &done);

    // Turn: in the idle loop use the turn clip (old facing for 3 frames, mirrored after).
    int face = d->face;
    bool use_turn = d->turn_t > 0 && idle_clip(a->clip) && a->over < 0 && play;
    if (use_turn) {
        const nabo_dive_clip_t* tc = clip(NABO_DIVE_CLIP_TURN);
        int k = (int)((DIVE_TURN_T - d->turn_t) * tc->fps);
        k = k < 0 ? 0 : k > 4 ? 4 : k;
        f = tc->first + kTurnSeq[k];
        face = k < 3 ? -d->dir : d->dir;
    }
    a->last_frame = f;

    // Sprite transform: mirror, turn squash (dash only), tilt, dash stretch, gulp pulse.
    float rot;
    if (screen == DIVE_SCREEN_TITLE)
        rot = CANON + sinf(d->t * 1.6f) * 0.05f;
    else if (d->phase != DIVE_PLAY)
        rot = CANON + 0.35f * clampf(d->die_t / 1.2f, 0, 1);
    else {
        float vx = d->vx * (face > 0 ? -1 : 1);
        float ang = atan2f(d->vy, vx) - 1.5707963f, step = 3.14159265f / 24;
        float q = roundf((ang - CANON) / step);
        rot = CANON + clampf(q, -3, 3) * step;
    }
    float spin = d->act == DIVE_ACT_HIT ? sinf((0.45f - d->act_t) / 0.45f * 3.14159265f) * 0.35f : 0;
    float k = d->dash_k;
    float g = (d->gulp_t > 0 && a->over != NABO_DIVE_CLIP_GULP) ? sinf((1 - d->gulp_t / 0.22f) * 3.14159265f) * 0.09f : 0;
    float sx = (1 - 0.1f * k) * (1 + g), sy = (1 + 0.12f * k) * (1 + g * 0.5f);
    float squash = 1;
    if (d->turn_t > 0 && !use_turn && play)
        squash = fmaxf(0.3f, fabsf(cosf(3.14159265f * (1 - d->turn_t / DIVE_TURN_T))));
    // M = Mirror * SquashX * R(rot + spin) * S(sx, sy) * R(-CANON); art offset -> screen offset
    float c1 = cosf(rot + spin), s1 = sinf(rot + spin), c0 = cosf(-CANON), s0 = sinf(-CANON);
    float ra[4] = {c1 * sx, -s1 * sy, s1 * sx, c1 * sy};          // R(rot) * S
    float m[4] = {ra[0] * c0 + ra[1] * s0, -ra[0] * s0 + ra[1] * c0,  // * R(-CANON)
                  ra[2] * c0 + ra[3] * s0, -ra[2] * s0 + ra[3] * c0};
    float mirror = face > 0 ? -1.0f : 1.0f;
    v->m[0] = m[0] * squash * mirror, v->m[1] = m[1] * squash * mirror, v->m[2] = m[2], v->m[3] = m[3];

    v->screen = screen;
    v->frame = f;
    v->fade_frame = (a->fade_frame >= 0 && a->fade_t > 0 && !use_turn) ? a->fade_frame : -1;
    v->fade_alpha = (uint8_t)(clampf(a->fade_t / FADE_T, 0, 1) * 255);
    v->nabo_alpha = (d->inv > 0 && play && ((int)(d->inv * 16) % 2 == 0)) ? 115 : 255;
    a->last_events = events;
}
