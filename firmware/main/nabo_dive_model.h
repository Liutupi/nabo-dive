#pragma once
// DIVE game rules: terrain, oxygen, bubbles, creatures and collisions. Pure logic in
// world pixels (y grows with depth); no display, audio or RTOS dependencies.
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DIVE_W 240
#define DIVE_H 320
#define DIVE_SCREEN_Y 112      // NABO's screen row while swimming normally
#define DIVE_DASH_SCREEN_Y 78  // camera looks further ahead while dashing
#define DIVE_ZONES 5
#define DIVE_MAX_OBS 12
#define DIVE_MAX_BUBBLES 28
#define DIVE_MAX_PARTS 48
#define DIVE_MAX_VENTS 4
#define DIVE_MAX_TEXTS 4
#define DIVE_NOISE 256
#define DIVE_TURN_T (5.0f / 24.0f)  // turn clip: 3 frames + 2 mirrored at 24 fps
#define DIVE_O2_MAX 100.0f

typedef enum { DIVE_PLAY, DIVE_DYING, DIVE_OVER } dive_phase_t;
typedef enum { DIVE_JELLY, DIVE_ANGLER } dive_obs_kind_t;
typedef enum { DIVE_BUB_SMALL, DIVE_BUB_LARGE, DIVE_BUB_CLUSTER, DIVE_BUB_VENT } dive_bubble_kind_t;
typedef enum { DIVE_PART_BUBBLE, DIVE_PART_RING, DIVE_PART_NEAR, DIVE_PART_STREAK } dive_part_kind_t;
typedef enum { DIVE_ACT_NONE, DIVE_ACT_HIT, DIVE_ACT_GULP, DIVE_ACT_NEAR, DIVE_ACT_RECORD } dive_act_t;
typedef enum { DIVE_TEXT_MINUS, DIVE_TEXT_PLUS, DIVE_TEXT_NEAR, DIVE_TEXT_RESCUE } dive_text_kind_t;

// Events raised since the last dive_take_events() call (for sound and animation).
enum {
    DIVE_EV_FLIP = 1 << 0,
    DIVE_EV_BUBBLE = 1 << 1,
    DIVE_EV_HIT = 1 << 2,
    DIVE_EV_NEAR = 1 << 3,
    DIVE_EV_ZONE = 1 << 4,
    DIVE_EV_RECORD = 1 << 5,
    DIVE_EV_LAST_BREATH = 1 << 6,
    DIVE_EV_RESCUE = 1 << 7,
    DIVE_EV_DIE = 1 << 8,
    DIVE_EV_HEART = 1 << 9,
    DIVE_EV_DASH_ON = 1 << 10,
    DIVE_EV_DASH_OFF = 1 << 11,
};

typedef struct {
    bool alive, passed, hit_me, big;
    uint8_t kind;
    int8_t face;
    float bx, by, x, y, rad, amp, ph, sp, min_gap;
} dive_obs_t;

typedef struct {
    bool alive;
    uint8_t kind, value;
    float bx, x, y, r, vy, ph;
} dive_bubble_t;

typedef struct {
    bool alive;
    uint8_t kind;
    float x, y, vx, vy, r, life, max, len, ph;
} dive_part_t;

typedef struct {
    bool alive;
    int8_t side;
    float x, y, t;
} dive_vent_t;

typedef struct {
    bool alive;
    uint8_t kind;
    int16_t value;
    float x, y, t;
} dive_text_t;

typedef struct {
    // NABO
    float x, y, vx, vy, kx, o2, lb_t, stun, inv, turn_t, act_t, dash_k, gulp_t;
    int8_t dir, face;
    bool lb, dashing, queued_flip;
    uint8_t act;
    // world
    dive_phase_t phase;
    uint32_t seed, rng;
    int8_t noise[8][DIVE_NOISE];
    float t, cam_y, gen_y, next_bubble_y, die_t;
    int zone;
    dive_obs_t obs[DIVE_MAX_OBS];
    dive_bubble_t bubbles[DIVE_MAX_BUBBLES];
    dive_part_t parts[DIVE_MAX_PARTS];
    dive_vent_t vents[DIVE_MAX_VENTS];
    dive_text_t texts[DIVE_MAX_TEXTS];
    // feedback
    float slow_t, shake_t, o2_flash, trail_t, heart_t, streak_t, last_pick, toast_t;
    int toast_zone;  // -1: none, 0..4 zone, DIVE_ZONES: new record
    uint32_t flips, chain, events;
    // records
    float best_px;
    bool passed_best, new_record;
    uint16_t stat_bubbles, stat_near, stat_hits;
} dive_t;

typedef struct {
    float speed, drain, bubbles, obstacles;  // tuning multipliers, 1.0 = default
} dive_tune_t;

void dive_reset(dive_t* d, uint32_t seed, float best_px);
// Advances the game. flip: one OK press since the last step; dash: DOWN held.
void dive_step(dive_t* d, const dive_tune_t* tune, float dt, bool flip, bool dash);
uint32_t dive_take_events(dive_t* d);

// Terrain queries (also used by the renderer for every world row).
void dive_corridor(const dive_t* d, float y, float* l, float* r);
void dive_far(const dive_t* d, float y, float l, float r, float* fl, float* fr);
float dive_strata(const dive_t* d, float y);

int dive_zone_of(float px);
float dive_depth_m(float px);
// Head circle centre, the "mouth" used for bubble pickup and collisions.
void dive_head(const dive_t* d, float* x, float* y);

extern const float dive_zone_px[DIVE_ZONES];
extern const int dive_zone_m[DIVE_ZONES];

#ifdef __cplusplus
}
#endif
