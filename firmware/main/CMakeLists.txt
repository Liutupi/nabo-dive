idf_component_register(
    SRCS "main.c"
         "nabo_dive.c"
         "nabo_dive_anim.c"
         "nabo_dive_draw.c"
         "nabo_dive_model.c"
         "nabo_dive_render.c"
         "nabo_dive_sound.c"
         "nabo_dive_sprites.c"
         "nabo_dive_text.c"
         "nabo_menu_font_16.c"
         "nabo_mono_font_12.c"
         "nabo_poster_font_28.c"
         "nabo_poster_font_48.c"
         "nabo_ui_font_18.c"
    INCLUDE_DIRS "."
    REQUIRES bsp lvgl esp_lcd esp_timer nvs_flash esp_rom
)

# DIVE renders and synthesizes per pixel/sample on the single-core C3; keep those paths optimized.
set_source_files_properties(nabo_dive_draw.c nabo_dive_render.c nabo_dive_text.c nabo_dive_sound.c
                            PROPERTIES COMPILE_OPTIONS "-O2")
