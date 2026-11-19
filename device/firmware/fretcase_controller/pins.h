// Pin assignments for the FretCase controller. This is the only file to edit when the wiring
// changes. Counts: 1 platter encoder, 4 knob encoders, 6 faders, 10 keys, a 16-pixel ring and
// 10 key LEDs (one addressable pixel under each key).
#pragma once

#include <Arduino.h>

#if defined(TEENSYDUINO)
// ---- Teensy 4.1 (default build) ---------------------------------------------------------
// Encoders: A and B outputs of each. Use pins with interrupts for the platter; every Teensy 4
// digital pin has them.
constexpr uint8_t PIN_PLATTER_A = 0;
constexpr uint8_t PIN_PLATTER_B = 1;
constexpr uint8_t PIN_KNOB_A[4] = {2, 4, 6, 8}; // brightness, complexity, density, tempo
constexpr uint8_t PIN_KNOB_B[4] = {3, 5, 7, 9};

// Faders (slide potentiometers), wiper to analog pin, ends to 3.3 V and GND. Order: vocal,
// melody, guitar, bass, drums, ambience. Top of the travel must read 3.3 V.
constexpr uint8_t PIN_FADER[6] = {A0, A1, A2, A3, A4, A5};

// Keys to GND, internal pull-ups. Order: capture, play, undo, another, then the six track
// keys vocal, melody, guitar, bass, drums, ambience.
constexpr uint8_t PIN_KEY[10] = {30, 31, 32, 33, 34, 35, 36, 37, 38, 39};

// Data pins of the two WS2812 chains (use a 5 V level shifter, e.g. 74HCT245).
constexpr uint8_t PIN_RING_DATA = 10;
constexpr uint8_t PIN_KEYLED_DATA = 11;

#elif defined(ARDUINO_ARCH_RP2040)
// ---- Raspberry Pi Pico (alternative build, not tested) ----------------------------------
// The Pico has only three analog pins, so the six faders go through a CD74HC4051 multiplexer
// (channels 0 to 5). All 26 usable GPIO pins are taken.
constexpr uint8_t PIN_PLATTER_A = 0;
constexpr uint8_t PIN_PLATTER_B = 1;
constexpr uint8_t PIN_KNOB_A[4] = {2, 4, 6, 8};
constexpr uint8_t PIN_KNOB_B[4] = {3, 5, 7, 9};
constexpr uint8_t PIN_KEY[10] = {10, 11, 12, 13, 14, 15, 16, 17, 18, 19};
constexpr uint8_t PIN_RING_DATA = 20;
constexpr uint8_t PIN_KEYLED_DATA = 21;
constexpr uint8_t PIN_MUX_ANALOG = 26; // ADC0
constexpr uint8_t PIN_MUX_SELECT[3] = {22, 27, 28};
#define FRETCASE_FADERS_ON_MUX 1

#else
#error "Unsupported board: use a Teensy 4.1 or a Raspberry Pi Pico"
#endif

// Pulses per click of the encoders (4 for a normal detented encoder, 1 for a smooth jog
// wheel). The platter should give 24 detents per turn.
constexpr uint8_t PLATTER_PULSES_PER_STEP = 4;
constexpr uint8_t KNOB_PULSES_PER_STEP = 4;
constexpr int16_t PLATTER_SPEED = 1; // multiplier on the detent count
constexpr int16_t KNOB_SPEED = 1;

constexpr uint8_t RING_PIXELS = 16;
constexpr uint8_t KEY_COUNT = 10;
// Index of the first pixel of the ring that is at the top of the platter, and the direction.
// The ring is wired clockwise starting at the top, as the panel protocol expects.
constexpr bool RING_CLOCKWISE_WIRING = true;
// WS2812 colour order of both chains.
#define FRETCASE_LED_ORDER GRB
