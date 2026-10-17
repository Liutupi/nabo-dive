#pragma once
// Text for DIVE's direct-to-panel renderer: lays out UTF-8 strings with LVGL's
// uncompressed 4 bpp board fonts and blends them one row segment at a time.
#include <stdint.h>
#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

#define DIVE_TEXT_MAX_GLYPHS 16

typedef struct {
    const uint8_t* bitmap;  // 4 bpp, rows packed without padding, high nibble first
    int16_t x, y;           // top-left in screen pixels
    uint8_t w, h;
} dive_glyph_t;

typedef struct {
    dive_glyph_t glyphs[DIVE_TEXT_MAX_GLYPHS];
    uint8_t count;
    int16_t x0, y0, x1, y1;  // bounding box, exclusive end
    uint16_t color;          // RGB565
    uint8_t alpha;           // 0..255
} dive_text_layout_t;

typedef enum { DIVE_ALIGN_LEFT, DIVE_ALIGN_CENTER, DIVE_ALIGN_RIGHT } dive_align_t;

// Lays out text whose baseline sits at y. spacing adds pixels after every glyph.
int dive_text_layout(dive_text_layout_t* t, const lv_font_t* font, const char* utf8, int x, int y,
                     dive_align_t align, int spacing, uint16_t color, uint8_t alpha);
// Width of the text in pixels.
int dive_text_width(const lv_font_t* font, const char* utf8, int spacing);
// Blends row y, columns [x0, x1) of the text into native RGB565 pixels.
void dive_text_row(const dive_text_layout_t* t, int y, int x0, int x1, uint16_t* row);
// Same, shifted by (dx, dy) and with another colour/opacity (drop shadows).
void dive_text_row_ex(const dive_text_layout_t* t, int y, int x0, int x1, uint16_t* row, int dx,
                      int dy, uint16_t color, uint8_t alpha);

#ifdef __cplusplus
}
#endif
