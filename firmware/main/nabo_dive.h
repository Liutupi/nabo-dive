#pragma once
// DIVE: one-button vertical diving game. It owns the panel directly (hardware
// vertical scroll) while open; LVGL refresh stays paused for that time.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "muse_menu.h"

#ifdef __cplusplus
extern "C" {
#endif

enum { NABO_DIVE_BUTTON_OK = 0, NABO_DIVE_BUTTON_DOWN = 1 };

// Starts the game task. The caller has paused LVGL refresh and waited for its last flush.
bool nabo_dive_open(esp_lcd_panel_io_handle_t io, esp_lcd_panel_handle_t panel, uint32_t seed);
// Stops the game task and resets hardware scroll. Returns once the panel is idle.
void nabo_dive_close(void);
bool nabo_dive_running(void);
// Serial diagnostic: let the game play itself (performance checks and demos).
void nabo_dive_autopilot(bool on);
// Serial diagnostic: per-stage timing in the 5 s log (costs about 1 ms per frame).
void nabo_dive_profile(bool on);
// Physical button edges, safe from any task.
void nabo_dive_button(int button, bool pressed, uint32_t event_ms);
// Menu keys (UP click pauses). Returns true when consumed.
bool nabo_dive_key(muse_menu_key_t key);
// Fills 16 kHz mono PCM for the apps worker.
void nabo_dive_audio_fill(int16_t* out, size_t count);

#ifdef __cplusplus
}
#endif
