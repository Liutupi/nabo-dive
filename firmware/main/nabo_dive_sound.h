#pragma once
// DIVE sound: 16 kHz synthesis of the layered score and event cues (same palette as the
// web prototype). Integer per-sample work; one instance lives on the audio task.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DIVE_SOUND_RATE 16000
#define DIVE_SOUND_VOICES 12

typedef struct {
    uint32_t phase, inc;
    int32_t inc_step;      // glide per sample (Q32 phase units)
    int32_t amp;           // Q15
    int32_t peak, decay;   // decay: Q15 multiplier applied every 32 samples
    int32_t attack;        // samples left in the linear attack
    int32_t attack_len;
    int32_t delay;         // samples before the voice starts
    int32_t length;        // samples left
    uint8_t kind;          // 0 sine, 1 triangle, 2 noise
    int32_t lp;            // one-pole state for noise
    int16_t lp_k;          // Q15 low-pass coefficient for noise (0: none)
    bool hp;               // noise through high-pass instead
    bool active, loop;
} dive_voice_t;

typedef struct {
    dive_voice_t v[DIVE_SOUND_VOICES];
    uint32_t noise;
    int32_t beat_left;     // samples until the next beat
    uint32_t beat;
    int zone;
    bool music, playing;   // music: pad on (title/play); playing: full layers
    int32_t master_lp, lp_k, lp_target;  // muffling filter (Q15)
    int dash_voice;        // looping whoosh voice index, -1 if none
} dive_sound_t;

// Event bits match DIVE_EV_* from nabo_dive_model.h.
typedef struct {
    uint32_t events;
    uint8_t zone;
    uint8_t chain;
    uint16_t flips;
} dive_sound_cue_t;

void dive_sound_reset(dive_sound_t* s);
void dive_sound_cue(dive_sound_t* s, const dive_sound_cue_t* cue);
// music: pad layer; playing: in-game layers; o2/lb drive the low-pass "muffled" effect.
void dive_sound_state(dive_sound_t* s, bool music, bool playing, int zone, float o2, bool last_breath);
void dive_sound_start(dive_sound_t* s);  // splash at the start of a dive
void dive_sound_fill(dive_sound_t* s, int16_t* out, size_t count);

#ifdef __cplusplus
}
#endif
