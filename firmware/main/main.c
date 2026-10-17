// main/main.c — DIVE 深潜：NABO 的单键下潜游戏，AI Passport 独立固件。
//
// 开机直接进入游戏，不需要配网或激活。
//   OK    按下换方向（标题页开始，结束页再来一局）
//   下键  按住俯冲
//   上键  单击暂停 / 继续（结束页回标题）；长按切换静音
// 5 分钟无操作自动深睡，任意键唤醒。
#include <stdatomic.h>
#include <string.h>

#include "bsp_audio.h"
#include "bsp_battery.h"
#include "bsp_button.h"
#include "bsp_display.h"
#include "bsp_i2c.h"
#include "bsp_pins.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nabo_dive.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "dive-main";

#define SAMPLE_RATE 16000
#define CHUNK 320                       // 20 ms at 16 kHz
#define VOLUME 70
#define IDLE_SLEEP_US (5LL * 60 * 1000 * 1000)
#define BACKLIGHT 85

static atomic_bool s_mute_toggle;
static _Atomic int64_t s_last_input_us;
static bool s_audio_ok;

/* ---------- settings ---------- */

static bool load_muted(void) {
    uint8_t v = 0;
    nvs_handle_t h;
    if (nvs_open("dive_app", NVS_READONLY, &h) == ESP_OK) {
        nvs_get_u8(h, "muted", &v);
        nvs_close(h);
    }
    return v != 0;
}

static void save_muted(bool muted) {
    nvs_handle_t h;
    if (nvs_open("dive_app", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u8(h, "muted", muted ? 1 : 0);
        nvs_commit(h);
        nvs_close(h);
    }
}

/* ---------- buttons (esp_timer task: bounded work only) ---------- */

static void on_button(bsp_btn_t btn, bsp_btn_ev_t ev, void *user) {
    (void)user;
    atomic_store(&s_last_input_us, esp_timer_get_time());
    uint32_t ms = (uint32_t)(esp_timer_get_time() / 1000);
    switch (btn) {
        case BSP_BTN_OK:
            if (ev == BSP_BTN_PRESS)
                nabo_dive_button(NABO_DIVE_BUTTON_OK, true, ms);
            else if (ev == BSP_BTN_RELEASE)
                nabo_dive_button(NABO_DIVE_BUTTON_OK, false, ms);
            break;
        case BSP_BTN_DOWN:
            if (ev == BSP_BTN_PRESS)
                nabo_dive_button(NABO_DIVE_BUTTON_DOWN, true, ms);
            else if (ev == BSP_BTN_RELEASE)
                nabo_dive_button(NABO_DIVE_BUTTON_DOWN, false, ms);
            break;
        case BSP_BTN_UP:
            if (ev == BSP_BTN_CLICK)
                nabo_dive_key(MUSE_MENU_UP);
            else if (ev == BSP_BTN_LONG)
                atomic_store(&s_mute_toggle, true);
            break;
        default:
            break;
    }
}

/* ---------- deep sleep ---------- */

static void warn(const char *what, esp_err_t err) {
    if (err != ESP_OK)
        ESP_LOGW(TAG, "%s: %s", what, esp_err_to_name(err));
}

// Called from the audio task, which owns all PCM I/O, so nothing else touches the codec.
static void enter_deep_sleep(void) {
    ESP_LOGI(TAG, "idle for 5 min, entering deep sleep");
    nabo_dive_close();  // stops the game task and resets hardware scroll
    bsp_display_backlight(0);

    int level = 0;
    if (bsp_button_prepare_deep_sleep(&level) != ESP_OK)
        esp_restart();
    warn("gpio wake", esp_deep_sleep_enable_gpio_wakeup(1ULL << BSP_BTN_GPIO, ESP_GPIO_WAKEUP_GPIO_LOW));
    warn("battery sleep", bsp_battery_sleep());
    if (s_audio_ok) {
        warn("audio sleep", bsp_audio_sleep());
        warn("i2s release", bsp_audio_prepare_deep_sleep());
    }
    warn("i2c release", bsp_i2c_prepare_deep_sleep());
    warn("display sleep", bsp_display_prepare_deep_sleep());
    esp_deep_sleep_start();
    esp_restart();
}

/* ---------- audio worker ---------- */

static void audio_task(void *arg) {
    (void)arg;
    static int16_t pcm[CHUNK];
    bool muted = load_muted();
    if (s_audio_ok)
        bsp_audio_set_volume(muted ? 0 : VOLUME);
    for (;;) {
        if (atomic_exchange(&s_mute_toggle, false)) {
            muted = !muted;
            if (s_audio_ok)
                bsp_audio_set_volume(muted ? 0 : VOLUME);
            save_muted(muted);
            ESP_LOGI(TAG, "sound %s", muted ? "off" : "on");
        }
        if (esp_timer_get_time() - atomic_load(&s_last_input_us) > IDLE_SLEEP_US)
            enter_deep_sleep();

        memset(pcm, 0, sizeof(pcm));
        nabo_dive_audio_fill(pcm, CHUNK);  // always drain cues so they never pile up
        // The blocking I2S write is the 20 ms clock; only sleep when there is no codec.
        if (!s_audio_ok || bsp_audio_write(pcm, sizeof(pcm)) != ESP_OK)
            vTaskDelay(pdMS_TO_TICKS(20));
    }
}

/* ---------- boot ---------- */

static void clear_screen(void) {
    const int rows = 20;
    uint16_t *line = heap_caps_calloc(BSP_LCD_W * rows, sizeof(uint16_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!line)
        return;
    esp_lcd_panel_handle_t panel = bsp_display_panel();
    for (int y = 0; y < BSP_LCD_H; y += rows)
        esp_lcd_panel_draw_bitmap(panel, 0, y, BSP_LCD_W, y + rows, line);
    esp_lcd_panel_io_tx_param(bsp_display_io(), 0x00, NULL, 0);  // wait for the last transfer
    heap_caps_free(line);
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    warn("nvs", err);

    ESP_ERROR_CHECK(bsp_display_init());
    clear_screen();

    warn("battery", bsp_battery_init());
    s_audio_ok = bsp_audio_init() == ESP_OK && bsp_audio_set_format(SAMPLE_RATE, 16, 1) == ESP_OK;
    if (!s_audio_ok)
        ESP_LOGE(TAG, "audio unavailable, running silent");

    atomic_store(&s_last_input_us, esp_timer_get_time());
    if (!nabo_dive_open(bsp_display_io(), bsp_display_panel(), esp_random())) {
        ESP_LOGE(TAG, "dive failed to start, restarting");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    }
    vTaskDelay(pdMS_TO_TICKS(60));  // let the title frame land before the backlight comes up
    bsp_display_backlight(BACKLIGHT);

    xTaskCreate(audio_task, "dive_audio", 4096, NULL, 5, NULL);
    ESP_ERROR_CHECK(bsp_button_init(on_button, NULL));
    ESP_LOGI(TAG, "DIVE ready, free heap %u", (unsigned)esp_get_free_heap_size());
}
