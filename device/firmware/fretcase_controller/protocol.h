// MIDI protocol between the controller and the bridge. This repeats
// device/bridge/fretcase_bridge/mapping.default.json: change both together.
#pragma once

#include <stdint.h>

namespace protocol {

constexpr uint8_t VERSION_MAJOR = 0;
constexpr uint8_t VERSION_MINOR = 1;
constexpr uint8_t VERSION_PATCH = 0;

// All messages are on MIDI channel 1.
constexpr uint8_t CC_PLATTER = 16;                 // relative, two's complement
constexpr uint8_t CC_KNOB[4] = {17, 18, 19, 20};   // brightness, complexity, density, tempo
constexpr uint8_t CC_FADER[6] = {21, 22, 23, 24, 25, 26}; // vocal ... ambience, absolute

// Keys: note on / note off. Order: capture, play, undo, another, track.vocal ... track.ambience.
constexpr uint8_t NOTE_KEY[10] = {36, 37, 38, 39, 40, 41, 42, 43, 44, 45};

// SysEx (bytes between F0 and F7).
constexpr uint8_t SYSEX_PREFIX[3] = {0x7D, 0x46, 0x43}; // non-commercial ID, "FC"
constexpr uint8_t SX_RING = 1;         // brightness, then 16 x (r g b), 7 bit each
constexpr uint8_t SX_KEY_LIGHT = 2;    // key note, mode, has-colour, r g b
constexpr uint8_t SX_DUMP_REQUEST = 3; // answer with all fader CCs and a SX_VERSION
constexpr uint8_t SX_VERSION = 4;      // major minor patch (controller to bridge)

enum KeyMode : uint8_t { MODE_OFF = 0, MODE_ON = 1, MODE_BLINK = 2, MODE_PULSE = 3 };

} // namespace protocol
