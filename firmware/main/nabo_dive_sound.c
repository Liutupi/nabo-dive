#include "nabo_dive_sound.h"
#include <math.h>
#include <string.h>
#include "nabo_dive_model.h"

#define RATE DIVE_SOUND_RATE
#define BLOCK 32
#define RELEASE 600  // samples of linear fade at the end of every voice (no clicks)
#define BEAT_SAMPLES (RATE * 60 / 84)
#define MASTER_GAIN 19660  // 0.6 in Q15

static int16_t sine_lut[256];
static const uint8_t kRoot[DIVE_ZONES] = {62, 59, 54, 50, 45};
static const uint8_t kScale[DIVE_ZONES][5] = {
    {0, 2, 4, 7, 9}, {0, 3, 5, 7, 10}, {0, 3, 5, 7, 10}, {0, 2, 3, 7, 8}, {0, 1, 5, 7, 8}};
static const int8_t kMotif[8] = {0, 2, 4, 2, 5, 4, 2, 1};
enum { SINE, TRI, NOISE };

static float mtof(int m) { return 440.0f * powf(2.0f, (m - 69) / 12.0f); }
static int note_of(int z, int d) {
    int o = d >= 0 ? d / 5 : -((4 - d) / 5), i = ((d % 5) + 5) % 5;
    return kRoot[z] + kScale[z][i] + 12 * o;
}
static uint32_t inc_of(float hz) { return (uint32_t)(hz * 4294967296.0f / RATE); }
static int16_t lp_coef(float hz) { return (int16_t)((1 - expf(-6.2831853f * hz / RATE)) * 32767); }

void dive_sound_reset(dive_sound_t* s) {
    if (!sine_lut[64])
        for (int i = 0; i < 256; ++i)
            sine_lut[i] = (int16_t)(sinf(i * 6.2831853f / 256) * 32767);
    memset(s, 0, sizeof(*s));
    s->noise = 0xACE1u;
    s->beat_left = RATE / 10;
    s->lp_k = s->lp_target = s->master_lp = 0;
    s->lp_k = s->lp_target = lp_coef(7000);
    s->dash_voice = -1;
}

// Starts a voice: linear attack, exponential decay to -60 dB over dur, optional pitch glide.
static int voice(dive_sound_t* s, int kind, float hz, float dur, float vol, float attack, float delay,
                 float glide_to) {
    int slot = -1;
    for (int i = 0; i < DIVE_SOUND_VOICES && slot < 0; ++i)
        if (!s->v[i].active)
            slot = i;
    if (slot < 0) {  // steal the quietest non-looping voice
        int32_t low = INT32_MAX;
        for (int i = 0; i < DIVE_SOUND_VOICES; ++i)
            if (!s->v[i].loop && s->v[i].amp < low)
                low = s->v[i].amp, slot = i;
        if (slot < 0)
            return -1;
    }
    dive_voice_t* v = &s->v[slot];
    memset(v, 0, sizeof(*v));
    v->active = true;
    v->kind = (uint8_t)kind;
    v->inc = inc_of(hz);
    int32_t len = (int32_t)(dur * RATE);
    if (glide_to > 0 && len > 0)
        v->inc_step = (int32_t)(((double)inc_of(glide_to) - v->inc) / len);
    v->peak = (int32_t)(vol * 32767);
    v->attack = v->attack_len = (int32_t)(attack * RATE) + 1;
    v->delay = (int32_t)(delay * RATE);
    v->length = len + v->attack_len;
    float blocks = dur * RATE / BLOCK;
    v->decay = blocks > 0 ? (int32_t)(expf(logf(0.001f) / blocks) * 32768) : 0;
    return slot;
}
static void tone(dive_sound_t* s, int kind, int midi, float dur, float vol, float delay) {
    voice(s, kind, mtof(midi), dur, vol, 0.006f, delay, 0);
}
static void noise(dive_sound_t* s, float dur, float vol, float hz, bool high) {
    int i = voice(s, NOISE, 0, dur, vol, 0.002f, 0, 0);
    if (i >= 0)
        s->v[i].lp_k = lp_coef(hz), s->v[i].hp = high;
}

void dive_sound_start(dive_sound_t* s) {
    noise(s, 0.45f, 0.2f, 1200, true);
    voice(s, SINE, 300, 0.15f, 0.08f, 0.006f, 0, 900);
}

void dive_sound_cue(dive_sound_t* s, const dive_sound_cue_t* c) {
    int z = c->zone < DIVE_ZONES ? c->zone : DIVE_ZONES - 1;
    uint32_t e = c->events;
    if (e & DIVE_EV_FLIP)
        tone(s, TRI, note_of(z, kMotif[c->flips % 8] + 5), 0.28f, 0.12f, 0);
    if (e & DIVE_EV_BUBBLE) {
        tone(s, SINE, note_of(z, 7 + (c->chain < 7 ? c->chain : 7)), 0.35f, 0.13f, 0);
        voice(s, SINE, 520, 0.07f, 0.06f, 0.004f, 0, 1150);
    }
    if (e & DIVE_EV_NEAR) {
        tone(s, SINE, note_of(z, 10), 0.25f, 0.09f, 0);
        tone(s, SINE, note_of(z, 12), 0.3f, 0.09f, 0.07f);
    }
    if (e & DIVE_EV_HIT) {
        noise(s, 0.3f, 0.28f, 900, false);
        voice(s, SINE, 110, 0.3f, 0.28f, 0.004f, 0, 45);
    }
    if (e & DIVE_EV_HEART) {
        voice(s, SINE, 58, 0.14f, 0.26f, 0.004f, 0, 38);
        voice(s, SINE, 54, 0.12f, 0.16f, 0.004f, 0.17f, 36);
    }
    if (e & DIVE_EV_LAST_BREATH)
        voice(s, SINE, mtof(note_of(z, -10)), 1.5f, 0.12f, 0.2f, 0, 0);
    if (e & DIVE_EV_RESCUE)
        for (int i = 0; i < 3; ++i)
            tone(s, SINE, note_of(z, (const int[]){7, 9, 12}[i]), 0.3f, 0.1f, i * 0.07f);
    if (e & DIVE_EV_RECORD)
        for (int i = 0; i < 5; ++i)
            tone(s, TRI, note_of(z, (const int[]){5, 7, 9, 10, 12}[i]), 0.4f, 0.1f, i * 0.08f);
    if (e & DIVE_EV_DIE)
        for (int i = 0; i < 4; ++i)
            tone(s, TRI, note_of(z, (const int[]){5, 3, 1, 0}[i]), 0.6f, 0.11f, i * 0.2f);
    if ((e & DIVE_EV_DASH_ON) && s->dash_voice < 0) {
        int i = voice(s, NOISE, 0, 30, 0.08f, 0.12f, 0, 0);
        if (i >= 0) {
            s->v[i].lp_k = lp_coef(1500);
            s->v[i].decay = 32768;  // hold while DOWN is held
            s->v[i].loop = true;
            s->dash_voice = i;
        }
        voice(s, SINE, 200, 0.25f, 0.08f, 0.006f, 0, 520);
    }
    if ((e & (DIVE_EV_DASH_OFF | DIVE_EV_DIE)) && s->dash_voice >= 0) {
        dive_voice_t* v = &s->v[s->dash_voice];
        v->loop = false;
        if (v->length > RELEASE * 4)
            v->length = RELEASE * 4;
        s->dash_voice = -1;
    }
}

void dive_sound_state(dive_sound_t* s, bool music, bool playing, int zone, float o2, bool lb) {
    s->music = music;
    s->playing = playing;
    s->zone = zone < 0 ? 0 : zone >= DIVE_ZONES ? DIVE_ZONES - 1 : zone;
    float hz = lb ? 450 : (playing && o2 < 30) ? 900 + (7000 - 900) * (o2 / 30) : 7000;
    s->lp_target = lp_coef(hz);
}

static void beat(dive_sound_t* s) {
    int z = s->zone, b = (int)s->beat, bar = b / 4, bb = b % 4;
    if (s->music && bb == 0 && bar % 2 == 0) {
        static const int8_t a[3] = {-5, -3, -1}, alt[3] = {-4, -2, 0};
        const int8_t* ch = (bar / 2) % 2 ? alt : a;
        for (int i = 0; i < 3; ++i)
            voice(s, SINE, mtof(note_of(z, ch[i])), 5.7f, 0.045f, 1.1f, 0, 0);
    }
    if (!s->playing)
        return;
    if (z >= 1 && (bb == 0 || bb == 2))
        tone(s, SINE, note_of(z, -10), 0.5f, 0.14f, 0);
    if (z >= 2 && bb == 3 && bar % 2 == 1)
        tone(s, SINE, note_of(z, 12), 1.4f, 0.045f, 0);
    if (z >= 3 && bb == 0)
        voice(s, SINE, 80, 0.28f, 0.18f, 0.004f, 0, 38);
}

static int32_t osc(dive_sound_t* s, dive_voice_t* v) {
    uint32_t p = v->phase;
    v->phase += v->inc;
    v->inc += (uint32_t)v->inc_step;
    switch (v->kind) {
        case SINE:
            return sine_lut[p >> 24];
        case TRI: {
            int32_t t = (int32_t)(p >> 16);  // 0..65535
            return t < 32768 ? t * 2 - 32767 : 98303 - t * 2;
        }
        default: {
            s->noise ^= s->noise << 13, s->noise ^= s->noise >> 17, s->noise ^= s->noise << 5;
            int32_t x = (int16_t)(s->noise >> 16);
            if (v->lp_k) {
                v->lp += (x - v->lp) * v->lp_k >> 15;
                x = v->hp ? x - v->lp : v->lp;
            }
            return x;
        }
    }
}

void dive_sound_fill(dive_sound_t* s, int16_t* out, size_t count) {
    for (size_t n = 0; n < count; ++n) {
        if (--s->beat_left <= 0) {
            s->beat_left = BEAT_SAMPLES;
            if (s->music)
                beat(s);
            ++s->beat;
        }
        bool block = (n & (BLOCK - 1)) == 0;
        if (block)
            s->lp_k += (s->lp_target - s->lp_k) >> 3;
        int32_t mix = 0;
        for (int i = 0; i < DIVE_SOUND_VOICES; ++i) {
            dive_voice_t* v = &s->v[i];
            if (!v->active)
                continue;
            if (v->delay > 0) {
                --v->delay;
                continue;
            }
            if (v->attack > 0) {
                v->amp = (int32_t)((int64_t)v->peak * (v->attack_len - v->attack) / v->attack_len);
                --v->attack;
            } else if (block && v->decay < 32768) {
                if (v->amp == 0)
                    v->amp = v->peak;
                v->amp = (int32_t)((int64_t)v->amp * v->decay >> 15);
            } else if (v->amp == 0)
                v->amp = v->peak;
            int32_t a = v->amp;
            if (!v->loop && v->length < RELEASE)
                a = a * v->length / RELEASE;
            mix += osc(s, v) * a >> 15;
            if (!v->loop && --v->length <= 0)
                v->active = false;
        }
        s->master_lp += (mix - s->master_lp) * s->lp_k >> 15;
        int32_t y = s->master_lp * MASTER_GAIN >> 15;
        out[n] = (int16_t)(y > 32767 ? 32767 : y < -32768 ? -32768 : y);
    }
}
