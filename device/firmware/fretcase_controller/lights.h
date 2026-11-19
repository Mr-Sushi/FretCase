// Light state and animation for the ring and the key LEDs.
#pragma once

#include <FastLED.h>

#include "pins.h"
#include "protocol.h"

namespace lights {

struct KeyLight {
  protocol::KeyMode mode;
  CRGB color;
  bool fixedColor; // the colour is part of the key; key.light colours are ignored
};

// Fixed colours: the capture key is red, track keys have their track colour.
inline CRGB hex(uint32_t rgb) { return CRGB((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF); }

inline CRGB ringLeds[RING_PIXELS];
inline CRGB keyLeds[KEY_COUNT];
inline CRGB ringTarget[RING_PIXELS];
inline uint8_t ringBrightness = 150; // 0.6 of 255, the protocol's default
inline KeyLight keys[KEY_COUNT] = {
    {protocol::MODE_ON, hex(0xD0332B), true},   // capture
    {protocol::MODE_OFF, hex(0xF2E6C8), false}, // play
    {protocol::MODE_OFF, hex(0xF2E6C8), false}, // undo
    {protocol::MODE_OFF, hex(0xF2E6C8), false}, // another
    {protocol::MODE_ON, hex(0xE2725B), true},   // vocal
    {protocol::MODE_ON, hex(0xE3A14A), true},   // melody
    {protocol::MODE_ON, hex(0x49B8B3), true},   // guitar
    {protocol::MODE_ON, hex(0x5B8DD6), true},   // bass
    {protocol::MODE_ON, hex(0x9A7BD1), true},   // drums
    {protocol::MODE_ON, hex(0x7FAE6A), true},   // ambience
};

inline uint8_t from7(uint8_t v) { return (uint16_t(v & 0x7F) * 255 + 63) / 127; }

inline void begin() {
  FastLED.addLeds<WS2812, PIN_RING_DATA, FRETCASE_LED_ORDER>(ringLeds, RING_PIXELS);
  FastLED.addLeds<WS2812, PIN_KEYLED_DATA, FRETCASE_LED_ORDER>(keyLeds, KEY_COUNT);
  FastLED.setBrightness(255);
  fill_solid(ringTarget, RING_PIXELS, CRGB::Black);
}

inline int keyIndexForNote(uint8_t note) {
  for (uint8_t i = 0; i < KEY_COUNT; i++)
    if (protocol::NOTE_KEY[i] == note) return i;
  return -1;
}

// data: the bytes after the SysEx command byte. Returns false if the length is wrong.
inline bool setRing(const uint8_t *d, uint16_t n) {
  if (n != 1 + RING_PIXELS * 3) return false;
  ringBrightness = (uint16_t(d[0] & 0x7F) * 255) / 127;
  for (uint8_t i = 0; i < RING_PIXELS; i++) {
    uint8_t p = RING_CLOCKWISE_WIRING ? i : (RING_PIXELS - i) % RING_PIXELS;
    ringTarget[p] = CRGB(from7(d[1 + 3 * i]), from7(d[2 + 3 * i]), from7(d[3 + 3 * i]));
  }
  return true;
}

inline bool setKeyLight(const uint8_t *d, uint16_t n) {
  if (n != 6) return false;
  int k = keyIndexForNote(d[0] & 0x7F);
  if (k < 0 || d[1] > protocol::MODE_PULSE) return false;
  keys[k].mode = static_cast<protocol::KeyMode>(d[1]);
  if (d[2] && !keys[k].fixedColor) keys[k].color = CRGB(from7(d[3]), from7(d[4]), from7(d[5]));
  return true;
}

// Call from loop(); redraws about 60 times a second.
inline void update(uint32_t nowMs) {
  static uint32_t last = 0;
  if (nowMs - last < 16) return;
  last = nowMs;
  for (uint8_t i = 0; i < RING_PIXELS; i++) {
    CRGB c = ringTarget[i];
    c.nscale8_video(ringBrightness);
    ringLeds[i] = c;
  }
  for (uint8_t k = 0; k < KEY_COUNT; k++) {
    CRGB c = keys[k].color;
    switch (keys[k].mode) {
    case protocol::MODE_OFF: c = CRGB::Black; break;
    case protocol::MODE_ON: break;
    case protocol::MODE_BLINK: if ((nowMs / 500) % 2) c = CRGB::Black; break;
    case protocol::MODE_PULSE: c.nscale8_video(beatsin8(50, 30, 255)); break; // about 1.2 s
    }
    keyLeds[k] = c;
  }
  FastLED.show();
}

} // namespace lights
