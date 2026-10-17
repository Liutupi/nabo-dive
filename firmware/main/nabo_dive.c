#include "nabo_dive.h"
#include <math.h>
#include <stdatomic.h>
#include <string.h>
#include "esp_heap_caps.h"
#include "esp_cpu.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "miniz.h"
#include "nabo_dive_anim.h"
#include "nabo_dive_model.h"
#include "nabo_dive_render.h"
#include "nabo_dive_sound.h"
#include "nvs.h"

#define TAG "NABO-Dive"
#define FRAME_US 16667
#define STEP (1.0f / 120)

// Game task state (owned by the task while it runs).
static esp_lcd_panel_io_handle_t s_io;
static esp_lcd_panel_handle_t s_panel;
static dive_t* s_game;
static dive_gfx_t s_gfx;
static dive_anim_t s_anim;
static tinfl_decompressor* s_inflate;
static TaskHandle_t s_task;
static SemaphoreHandle_t s_done;
static esp_timer_handle_t s_timer;
static atomic_bool s_stop, s_running;
static int s_scroll = -1;
static uint32_t s_seed;

// Inputs from the button / main tasks.
static atomic_int s_ok_presses, s_up_clicks;
static atomic_bool s_down_held, s_autopilot, s_profile;

// Audio: the game task pushes cues, the apps worker drains them while filling PCM.
#define CUE_RING 16
static dive_sound_cue_t s_cues[CUE_RING];
static atomic_uint s_cue_head, s_cue_tail;
static atomic_int s_music_zone, s_music_mode;  // mode: 0 off, 1 pad, 2 full layers
static _Atomic float s_music_o2;
static atomic_bool s_music_lb, s_splash;
static dive_sound_t s_sound;
static bool s_sound_ready;

static void push_cue(uint32_t events, const dive_t* d) {
    unsigned head = atomic_load(&s_cue_head);
    if (head - atomic_load(&s_cue_tail) >= CUE_RING)
        return;
    s_cues[head % CUE_RING] = (dive_sound_cue_t){events, (uint8_t)d->zone, (uint8_t)d->chain, (uint16_t)d->flips};
    atomic_store(&s_cue_head, head + 1);
}

void nabo_dive_audio_fill(int16_t* out, size_t count) {
    if (!s_sound_ready) {
        dive_sound_reset(&s_sound);
        s_sound_ready = true;
    }
    if (atomic_exchange(&s_splash, false))
        dive_sound_start(&s_sound);
    while (atomic_load(&s_cue_tail) != atomic_load(&s_cue_head)) {
        unsigned tail = atomic_load(&s_cue_tail);
        dive_sound_cue(&s_sound, &s_cues[tail % CUE_RING]);
        atomic_store(&s_cue_tail, tail + 1);
    }
    int mode = atomic_load(&s_music_mode);
    dive_sound_state(&s_sound, mode > 0, mode > 1, atomic_load(&s_music_zone), atomic_load(&s_music_o2),
                     atomic_load(&s_music_lb));
    int16_t pcm[320];
    while (count) {
        size_t n = count < 320 ? count : 320;
        dive_sound_fill(&s_sound, pcm, n);
        for (size_t i = 0; i < n; ++i) {  // mix over whatever the worker already put there
            int32_t v = out[i] + pcm[i];
            out[i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
        }
        out += n;
        count -= n;
    }
}

/* ---------- panel callbacks ---------- */

static void send(void* ctx, int x0, int gy, int w, int rows, uint16_t* px) {
    (void)ctx;
    esp_lcd_panel_draw_bitmap(s_panel, x0, gy, x0 + w, gy + rows, px);
}
static void set_scroll(void* ctx, int top) {
    (void)ctx;
    if (top == s_scroll)
        return;
    s_scroll = top;
    uint8_t v[2] = {(uint8_t)(top >> 8), (uint8_t)top};
    esp_lcd_panel_io_tx_param(s_io, 0x37, v, 2);  // VSCSAD
}
static bool decode(void* ctx, int frame, uint8_t* out) {
    (void)ctx;
    const uint8_t* src = &nabo_dive_pixels[nabo_dive_frame_offsets[frame]];
    size_t in = nabo_dive_frame_offsets[frame + 1] - nabo_dive_frame_offsets[frame];
    size_t len = NABO_DIVE_CELL * NABO_DIVE_CELL;
    tinfl_init(s_inflate);
    tinfl_status st = tinfl_decompress(s_inflate, src, &in, out, out, &len, TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
    return st == TINFL_STATUS_DONE && len == NABO_DIVE_CELL * NABO_DIVE_CELL;
}

/* ---------- records ---------- */

static float load_best(void) {
    nvs_handle_t h;
    uint32_t v = 0;
    if (nvs_open("nabo_ui", NVS_READONLY, &h) == ESP_OK) {
        nvs_get_u32(h, "dive_best", &v);
        nvs_close(h);
    }
    return (float)v;
}
static void save_best(float px) {
    nvs_handle_t h;
    esp_err_t err = nvs_open("nabo_ui", NVS_READWRITE, &h);
    if (err == ESP_OK) {
        err = nvs_set_u32(h, "dive_best", (uint32_t)px);
        if (err == ESP_OK)
            err = nvs_commit(h);
        nvs_close(h);
    }
    if (err != ESP_OK)
        ESP_LOGE(TAG, "best save failed: %d", err);
}
static bool load_dashed(void) {
    nvs_handle_t h;
    uint8_t v = 0;
    if (nvs_open("nabo_ui", NVS_READONLY, &h) == ESP_OK) {
        nvs_get_u8(h, "dive_dashed", &v);
        nvs_close(h);
    }
    return v != 0;
}
static void save_dashed(void) {
    nvs_handle_t h;
    if (nvs_open("nabo_ui", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u8(h, "dive_dashed", 1);
        nvs_commit(h);
        nvs_close(h);
    }
}

/* ---------- game task ---------- */

static uint32_t clock_us(void) { return (uint32_t)esp_timer_get_time(); }
static uint32_t cycles(void) { return (uint32_t)esp_cpu_get_cycle_count(); }

static void tick(void* arg) {
    (void)arg;
    if (s_task)
        xTaskNotifyGive(s_task);
}

static void new_dive(float best) {
    dive_reset(s_game, s_seed = s_seed * 1664525u + 1013904223u, best);
    dive_anim_reset(&s_anim);
    dive_gfx_invalidate(&s_gfx);
}

static void new_title(float best) {
    new_dive(best);
    s_game->y = -2;
}

static void game_task(void* arg) {
    (void)arg;
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);  // wait until nabo_dive_open() finished allocating
    if (atomic_load(&s_stop)) {
        xSemaphoreGive(s_done);
        vTaskDelete(NULL);
        return;
    }
    const dive_tune_t tune = {1, 1, 1, 1};
    dive_view_t view = {.fade_frame = -1, .nabo_alpha = 255, .best_m = -1};
    dive_screen_t screen = DIVE_SCREEN_TITLE;
    float best = load_best(), acc = 0, screen_t = 0;
    bool dashed = load_dashed();
    uint8_t vscrdef[6] = {0, 0, DIVE_H >> 8, DIVE_H & 0xFF, 0, 0};
    esp_lcd_panel_io_tx_param(s_io, 0x33, vscrdef, 6);
    new_title(best);
    int64_t last = esp_timer_get_time(), stats_at = last;
    uint32_t frames = 0, work_us = 0, max_work_us = 0, bytes = 0;
    atomic_store(&s_ok_presses, 0);
    atomic_store(&s_up_clicks, 0);
    while (!atomic_load(&s_stop)) {
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(50));
        int64_t now = esp_timer_get_time();
        float dt = (now - last) / 1e6f;
        last = now;
        if (dt > 0.1f)
            dt = 0.1f;
        int ok = atomic_exchange(&s_ok_presses, 0), up = atomic_exchange(&s_up_clicks, 0);
        bool dash = atomic_load(&s_down_held);
        if (atomic_load(&s_autopilot)) {  // serial diagnostic: dive on its own, for measurements and demos
            if (screen == DIVE_SCREEN_TITLE || (screen == DIVE_SCREEN_OVER && screen_t > 1.5f))
                ok = 1;
            else if (screen == DIVE_SCREEN_PLAY && s_game->phase == DIVE_PLAY) {
                float l, r;
                dive_corridor(s_game, s_game->y + 40, &l, &r);
                float target = (l + r) / 2, ahead = s_game->x + s_game->vx * 0.35f;
                if ((s_game->dir < 0 && ahead < target - 20) || (s_game->dir > 0 && ahead > target + 20))
                    ok = 1;
            }
        }
        uint32_t events = 0;
        dive_screen_t before = screen;

        switch (screen) {
            case DIVE_SCREEN_TITLE:
                s_game->t += dt;
                s_game->y = -2 + sinf(s_game->t * 1.6f) * 1.5f;
                if (ok) {
                    new_dive(best);
                    atomic_store(&s_splash, true);
                    screen = DIVE_SCREEN_PLAY;
                    ok = 0;
                    acc = 0;
                }
                break;
            case DIVE_SCREEN_PLAY:
                if (up) {
                    screen = DIVE_SCREEN_PAUSE;
                    break;
                }
                acc += dt;
                for (bool first = true; acc >= STEP; acc -= STEP, first = false) {
                    dive_step(s_game, &tune, STEP, first && ok > 0, dash);
                    events |= dive_take_events(s_game);
                }
                if (ok > 1)  // presses beyond one per frame still count as flips
                    for (int i = 1; i < ok; ++i) {
                        dive_step(s_game, &tune, 0, true, dash);
                        events |= dive_take_events(s_game);
                    }
                if ((events & DIVE_EV_DASH_ON) && !dashed) {
                    dashed = true;
                    save_dashed();
                }
                if (s_game->phase == DIVE_OVER) {
                    if (s_game->new_record) {
                        best = s_game->y;
                        save_best(best);
                    }
                    screen = DIVE_SCREEN_OVER;
                }
                break;
            case DIVE_SCREEN_PAUSE:
                if (up || ok) {
                    screen = DIVE_SCREEN_PLAY;
                    last = esp_timer_get_time();
                }
                break;
            case DIVE_SCREEN_OVER:
                if (screen_t > 0.45f && ok) {
                    new_dive(best);
                    atomic_store(&s_splash, true);
                    screen = DIVE_SCREEN_PLAY;
                    acc = 0;
                } else if (screen_t > 0.45f && up) {
                    new_title(best);
                    screen = DIVE_SCREEN_TITLE;
                }
                break;
        }
        if (screen != before)
            screen_t = 0;
        screen_t += dt;
        if (events)
            push_cue(events, s_game);
        atomic_store(&s_music_mode, screen == DIVE_SCREEN_PAUSE ? 0 : screen == DIVE_SCREEN_PLAY ? 2 : 1);
        atomic_store(&s_music_zone, s_game->zone);
        atomic_store(&s_music_o2, s_game->o2);
        atomic_store(&s_music_lb, s_game->lb);

        view.time = screen_t;
        view.best_m = best > 0 ? (int)dive_depth_m(best) : -1;
        view.dash_hint = !dashed;
        dive_anim_update(&s_anim, s_game, screen, dash, events, screen == DIVE_SCREEN_PAUSE ? 0 : dt, &view);
        bool prof = atomic_load(&s_profile);
        s_gfx.clock_us = prof ? clock_us : NULL;
        s_gfx.cycles = prof ? cycles : NULL;
        int64_t t0 = esp_timer_get_time();
        dive_gfx_frame(&s_gfx, s_game, &view);
        uint32_t used = (uint32_t)(esp_timer_get_time() - t0);
        ++frames, work_us += used, bytes += s_gfx.bytes;
        if (used > max_work_us)
            max_work_us = used;
        if (now - stats_at >= 5000000) {
            ESP_LOGI(TAG, "screen=%d depth=%d fps=%lu frame_us mean=%lu max=%lu bg=%lu ops=%lu send=%lu rows=%lu bytes=%lu heap=%u",
                     (int)screen, (int)dive_depth_m(s_game->y), (unsigned long)(frames * 1000000ULL / (now - stats_at)),
                     (unsigned long)(work_us / frames), (unsigned long)max_work_us, (unsigned long)(s_gfx.us_bg / frames),
                     (unsigned long)(s_gfx.us_ops / frames), (unsigned long)(s_gfx.us_send / frames),
                     (unsigned long)(s_gfx.segments / frames), (unsigned long)(bytes / frames),
                     (unsigned)esp_get_free_heap_size());
            if (prof)
                ESP_LOGI(TAG, "op us/frame: bub=%lu jel=%lu ang=%lu glow=%lu nabo=%lu part=%lu text=%lu shad=%lu rect=%lu line=%lu o2=%lu",
                         (unsigned long)(s_gfx.op_cycles[0] / 160 / frames), (unsigned long)(s_gfx.op_cycles[1] / 160 / frames),
                         (unsigned long)(s_gfx.op_cycles[2] / 160 / frames), (unsigned long)(s_gfx.op_cycles[3] / 160 / frames),
                         (unsigned long)(s_gfx.op_cycles[4] / 160 / frames), (unsigned long)(s_gfx.op_cycles[5] / 160 / frames),
                         (unsigned long)(s_gfx.op_cycles[6] / 160 / frames), (unsigned long)(s_gfx.op_cycles[7] / 160 / frames),
                         (unsigned long)(s_gfx.op_cycles[8] / 160 / frames), (unsigned long)(s_gfx.op_cycles[9] / 160 / frames),
                         (unsigned long)(s_gfx.op_cycles[10] / 160 / frames));
            memset(s_gfx.op_cycles, 0, sizeof(s_gfx.op_cycles));
            stats_at = now, frames = work_us = max_work_us = bytes = 0;
            s_gfx.us_bg = s_gfx.us_ops = s_gfx.us_send = s_gfx.segments = 0;
        }
    }
    set_scroll(NULL, 0);
    esp_lcd_panel_io_tx_param(s_io, 0x00, NULL, 0);  // wait for the last transfer
    atomic_store(&s_music_mode, 0);
    xSemaphoreGive(s_done);
    vTaskDelete(NULL);
}

/* ---------- lifecycle ---------- */

static void release(void) {
    if (s_timer) {
        esp_timer_stop(s_timer);
        esp_timer_delete(s_timer);
        s_timer = NULL;
    }
    dive_gfx_free(&s_gfx);
    heap_caps_free(s_game);
    heap_caps_free(s_inflate);
    s_game = NULL;
    s_inflate = NULL;
}

static void log_heap(const char* what) {
    ESP_LOGI(TAG, "%s: free=%u largest=%u", what, (unsigned)esp_get_free_heap_size(),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
}

bool nabo_dive_open(esp_lcd_panel_io_handle_t io, esp_lcd_panel_handle_t panel, uint32_t seed) {
    if (atomic_load(&s_running))
        return true;
    s_io = io, s_panel = panel, s_seed = seed, s_scroll = -1;
    log_heap("open");
    if (!s_done)
        s_done = xSemaphoreCreateBinary();
    // The task stack needs one contiguous block: take it before the large buffers fragment the heap.
    atomic_store(&s_stop, false);
    atomic_store(&s_down_held, false);
    s_task = NULL;
    // Largest blocks first while the heap still has big holes: inflate state, task stack, game.
    s_inflate = heap_caps_malloc(sizeof(tinfl_decompressor), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!s_done || !s_inflate || xTaskCreate(game_task, "nabo_dive", 6144, NULL, 4, &s_task) != pdPASS) {
        s_task = NULL;
        log_heap("open: task failed");
        release();
        return false;
    }
    s_game = heap_caps_malloc(sizeof(dive_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    const esp_timer_create_args_t args = {.callback = tick, .name = "nabo_dive"};
    bool ok = s_game && s_inflate && dive_gfx_init(&s_gfx, send, set_scroll, decode, NULL) &&
              esp_timer_create(&args, &s_timer) == ESP_OK;

    if (!ok) {
        log_heap("open: buffers failed");
        atomic_store(&s_stop, true);
        xTaskNotifyGive(s_task);  // the task sees s_stop before touching any buffer
        xSemaphoreTake(s_done, pdMS_TO_TICKS(500));
        s_task = NULL;
        release();
        return false;
    }
    atomic_store(&s_running, true);
    xTaskNotifyGive(s_task);  // start
    esp_timer_start_periodic(s_timer, FRAME_US);
    log_heap("open: running");
    return true;
}

void nabo_dive_close(void) {
    if (!atomic_load(&s_running))
        return;
    atomic_store(&s_stop, true);
    xTaskNotifyGive(s_task);
    if (xSemaphoreTake(s_done, pdMS_TO_TICKS(500)) != pdTRUE)
        ESP_LOGE(TAG, "close: game task did not stop");
    s_task = NULL;
    release();
    atomic_store(&s_running, false);
    log_heap("closed");
}

bool nabo_dive_running(void) { return atomic_load(&s_running); }

void nabo_dive_autopilot(bool on) { atomic_store(&s_autopilot, on); }
void nabo_dive_profile(bool on) { atomic_store(&s_profile, on); }

void nabo_dive_button(int button, bool pressed, uint32_t event_ms) {
    (void)event_ms;
    if (button == NABO_DIVE_BUTTON_OK && pressed)
        atomic_fetch_add(&s_ok_presses, 1);
    else if (button == NABO_DIVE_BUTTON_DOWN)
        atomic_store(&s_down_held, pressed);
}

bool nabo_dive_key(muse_menu_key_t key) {
    if (key == MUSE_MENU_UP)
        atomic_fetch_add(&s_up_clicks, 1);
    return true;  // OK / DOWN clicks are handled through their press edges
}
