#pragma once
// Internal to the DIVE renderer: draw operations and per-row primitives.
#include "nabo_dive_render.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    OP_BUBBLE,   // a: radius, b: glow 0..1, i: bubble kind
    OP_JELLY,    // i: obstacle index
    OP_ANGLER,   // i: obstacle index
    OP_GLOW,     // additive radial glow; a: radius, b: strength, c: colour
    OP_NABO,     // sprite through the inverse transform
    OP_PART,     // i: particle index
    OP_TEXT,     // i: layout index
    OP_SHADOW,   // i: layout index, drawn 1 px down-right in translucent ink
    OP_RECT,     // filled rectangle; c: colour, b: alpha, i: corner radius
    OP_LINE,     // 1 px line from (x, y) to (x2, y2); c: colour, b: alpha
    OP_O2,       // oxygen gauge
    OP_DIM,      // darkens everything drawn before it; b: amount
    OP_VENT,     // i: vent index
    OP_PROFILE,  // game-over depth profile bar
    OP_GAUGE,    // title depth scale
} dive_op_kind_t;

enum { LAYER_WORLD = 0, LAYER_UI = 1 };

struct dive_op {
    uint8_t kind, layer;
    bool dynamic;  // dynamic ops create dirty rectangles; static ones redraw only when covered
    bool opaque;   // paints every pixel of its box: nothing beneath it needs drawing
    int16_t x0, y0, x1, y1;
    int16_t i;
    float x, y, x2, y2, a, b;
    uint16_t c;
};

static inline uint16_t rgb565(int r, int g, int b) {
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}
static inline uint16_t blend565(uint16_t dst, uint16_t src, int a) {
    if (a >= 255)
        return src;
    if (a <= 0)
        return dst;
    int r = (((src >> 11) - (dst >> 11)) * a >> 8) + (dst >> 11);
    int g = ((((src >> 5) & 63) - ((dst >> 5) & 63)) * a >> 8) + ((dst >> 5) & 63);
    int b = (((src & 31) - (dst & 31)) * a >> 8) + (dst & 31);
    return (uint16_t)((r << 11) | (g << 5) | b);
}
static inline uint16_t add565(uint16_t dst, uint16_t src, int a) {
    int r = (dst >> 11) + ((src >> 11) * a >> 8);
    int g = ((dst >> 5) & 63) + (((src >> 5) & 63) * a >> 8);
    int b = (dst & 31) + ((src & 31) * a >> 8);
    return (uint16_t)(((r > 31 ? 31 : r) << 11) | ((g > 63 ? 63 : g) << 5) | (b > 31 ? 31 : b));
}

// Background for one screen row segment: world rows (play) or the title scene.
void dive_draw_world_row(dive_gfx_t* g, int world_y, int x0, int x1, uint16_t* row);
void dive_draw_title_row(dive_gfx_t* g, int y, int x0, int x1, uint16_t* row);
// One operation on row y, columns [x0, x1).
void dive_draw_op(dive_gfx_t* g, const dive_op_t* op, int y, int x0, int x1, uint16_t* row);
// Keeps the terrain cache valid for world row y.
void dive_rows_fill(dive_gfx_t* g, int world_y);

#ifdef __cplusplus
}
#endif
