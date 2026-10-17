#pragma once
// DIVE renderer: composes the game straight into ST7789 GRAM. World rows are drawn
// once as they scroll in (hardware vertical scroll moves them afterwards); moving
// things are redrawn through merged dirty rectangles. Pixels leave through a
// callback so the host tests can capture exactly what the panel would receive.
#include <stdbool.h>
#include <stdint.h>
#include "nabo_dive_model.h"
#include "nabo_dive_sprites.h"
#include "nabo_dive_text.h"

#ifdef __cplusplus
extern "C" {
#endif

// Sends big-endian RGB565 pixels for GRAM rows [gram_y, gram_y + rows), columns [x0, x0 + w).
typedef void (*dive_send_fn)(void* ctx, int x0, int gram_y, int w, int rows, uint16_t* px);
// Sets the hardware scroll start line (VSCSAD).
typedef void (*dive_scroll_fn)(void* ctx, int top);
// Inflates one sprite frame into CELL x CELL palette indices.
typedef bool (*dive_decode_fn)(void* ctx, int frame, uint8_t* out);

typedef enum { DIVE_SCREEN_TITLE, DIVE_SCREEN_PLAY, DIVE_SCREEN_PAUSE, DIVE_SCREEN_OVER } dive_screen_t;

typedef struct {
    dive_screen_t screen;
    int frame;           // sprite frame drawn now
    int fade_frame;      // previous frame for a cross-fade, -1 if none
    uint8_t fade_alpha;  // opacity of fade_frame
    uint8_t nabo_alpha;  // invulnerability blink
    float m[4];          // art offset (from anchor) -> screen offset: [a b; c d]
    float time;          // seconds since this screen opened, for UI blinking
    int best_m;          // best depth in metres, -1 if none
    bool dash_hint;      // first-run hint about holding DOWN
} dive_view_t;

#define DIVE_MAX_RECTS 48
#define DIVE_MAX_OPS 64
#define DIVE_MAX_LAYOUTS 16

typedef struct {
    int16_t x0, y0, x1, y1;
} dive_rect_t;

typedef struct dive_op dive_op_t;

typedef struct {
    // Terrain noise per world row, indexed by world row mod 320 (colours are cheap to recompute).
    int32_t y[DIVE_H];
    int16_t l16[DIVE_H], r16[DIVE_H], fl16[DIVE_H], fr16[DIVE_H];  // edges in 1/16 px
    int8_t strata[DIVE_H];
    // Span colours per 4-row band (gradients and strata barely change within 4 rows).
    int32_t band_y[DIVE_H / 4];
    uint16_t band_c[DIVE_H / 4][9];  // wall, b1, b2, b3, edge, ao, far, bg, pebble
} dive_rows_t;

typedef struct {
    dive_send_fn send;
    dive_scroll_fn scroll;
    dive_decode_fn decode;
    void* ctx;
    uint16_t* strip[2];
    int which;
    uint8_t* frame_px;  // decoded current sprite frame (no cross-fade buffer: RAM is tight)
    int frame_id;
    dive_rows_t* rows;
    const dive_t* d;
    const dive_view_t* v;
    int cam, scroll_top, last_cam;
    bool full, have_prev;
    dive_screen_t last_screen;
    dive_rect_t prev[DIVE_MAX_RECTS];
    int prev_n;
    uint16_t pal[NABO_DIVE_PALETTE_SIZE];
    uint8_t pal_a[NABO_DIVE_PALETTE_SIZE];
    int pal_bucket;
    float inv[4], nabo_x, nabo_y;  // inverse sprite transform and anchor on screen
    dive_op_t* ops;
    int op_n;
    dive_text_layout_t* layouts;
    int layout_n;
    uint32_t bytes;  // pixel bytes sent by the last frame
    uint32_t (*clock_us)(void);  // optional profiler clock
    uint32_t us_bg, us_ops, us_send, segments;  // accumulated until the caller resets them
    uint32_t (*cycles)(void);         // optional cycle counter for per-op profiling
    uint32_t op_cycles[16];
} dive_gfx_t;

bool dive_gfx_init(dive_gfx_t* g, dive_send_fn send, dive_scroll_fn scroll, dive_decode_fn decode,
                   void* ctx);
void dive_gfx_free(dive_gfx_t* g);
// Forces a full-screen redraw on the next frame and drops the terrain cache (new dive).
void dive_gfx_invalidate(dive_gfx_t* g);
void dive_gfx_frame(dive_gfx_t* g, const dive_t* d, const dive_view_t* v);

#ifdef __cplusplus
}
#endif
