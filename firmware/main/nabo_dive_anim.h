#pragma once
// NABO's clip state machine and sprite transform for DIVE (same rules as the web
// prototype): swim/lowair loop, dash in/loop/out, one-shot hit/gulp/out and the
// mirrored turn. Produces the frame, cross-fade and 2x2 transform the renderer needs.
#include <stdbool.h>
#include "nabo_dive_model.h"
#include "nabo_dive_render.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int clip;   // base clip: swim, lowair, dash_in, dash or dash_out
    int over;   // one-shot clip playing on top, -1 if none
    float clip_t, over_t;
    int fade_frame;
    float fade_t;
    int last_frame;
    uint32_t last_events;
} dive_anim_t;

void dive_anim_reset(dive_anim_t* a);
// Call once per rendered frame after stepping the model. events: dive_take_events() result.
void dive_anim_update(dive_anim_t* a, const dive_t* d, dive_screen_t screen, bool dash_held, uint32_t events,
                      float dt, dive_view_t* view);

#ifdef __cplusplus
}
#endif
