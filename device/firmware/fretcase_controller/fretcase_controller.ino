// FretCase controller: platter, four knobs, six faders and ten keys as USB MIDI, with SysEx
// in for the ring and key lights. Teensy 4.1 (Tools > USB Type > MIDI) or Raspberry Pi Pico.
//
// Libraries: Control Surface (2.x), FastLED, Encoder (comes with Teensyduino).
// The MIDI it sends and expects is in protocol.h.

#include <Control_Surface.h>

#include "lights.h"
#include "pins.h"
#include "protocol.h"

USBMIDI_Interface midi;

using protocol::CC_FADER;
using protocol::CC_KNOB;
using protocol::NOTE_KEY;

// Platter and knobs: relative CC.
CCRotaryEncoder platter{{PIN_PLATTER_A, PIN_PLATTER_B},
                        {protocol::CC_PLATTER, Channel_1},
                        PLATTER_SPEED,
                        PLATTER_PULSES_PER_STEP};
CCRotaryEncoder knob0{{PIN_KNOB_A[0], PIN_KNOB_B[0]}, {CC_KNOB[0], Channel_1}, KNOB_SPEED, KNOB_PULSES_PER_STEP};
CCRotaryEncoder knob1{{PIN_KNOB_A[1], PIN_KNOB_B[1]}, {CC_KNOB[1], Channel_1}, KNOB_SPEED, KNOB_PULSES_PER_STEP};
CCRotaryEncoder knob2{{PIN_KNOB_A[2], PIN_KNOB_B[2]}, {CC_KNOB[2], Channel_1}, KNOB_SPEED, KNOB_PULSES_PER_STEP};
CCRotaryEncoder knob3{{PIN_KNOB_A[3], PIN_KNOB_B[3]}, {CC_KNOB[3], Channel_1}, KNOB_SPEED, KNOB_PULSES_PER_STEP};

// Faders: absolute CC, 0 at the bottom.
#ifdef FRETCASE_FADERS_ON_MUX
CD74HC4051 mux{PIN_MUX_ANALOG, {PIN_MUX_SELECT[0], PIN_MUX_SELECT[1], PIN_MUX_SELECT[2]}};
#define FADER_PIN(i) (mux.pin(i))
#else
#define FADER_PIN(i) (PIN_FADER[i])
#endif
CCPotentiometer fader0{FADER_PIN(0), {CC_FADER[0], Channel_1}};
CCPotentiometer fader1{FADER_PIN(1), {CC_FADER[1], Channel_1}};
CCPotentiometer fader2{FADER_PIN(2), {CC_FADER[2], Channel_1}};
CCPotentiometer fader3{FADER_PIN(3), {CC_FADER[3], Channel_1}};
CCPotentiometer fader4{FADER_PIN(4), {CC_FADER[4], Channel_1}};
CCPotentiometer fader5{FADER_PIN(5), {CC_FADER[5], Channel_1}};
CCPotentiometer *const faders[6] = {&fader0, &fader1, &fader2, &fader3, &fader4, &fader5};

// Keys: note on and off (debounced by the library).
NoteButton key0{PIN_KEY[0], {NOTE_KEY[0], Channel_1}};
NoteButton key1{PIN_KEY[1], {NOTE_KEY[1], Channel_1}};
NoteButton key2{PIN_KEY[2], {NOTE_KEY[2], Channel_1}};
NoteButton key3{PIN_KEY[3], {NOTE_KEY[3], Channel_1}};
NoteButton key4{PIN_KEY[4], {NOTE_KEY[4], Channel_1}};
NoteButton key5{PIN_KEY[5], {NOTE_KEY[5], Channel_1}};
NoteButton key6{PIN_KEY[6], {NOTE_KEY[6], Channel_1}};
NoteButton key7{PIN_KEY[7], {NOTE_KEY[7], Channel_1}};
NoteButton key8{PIN_KEY[8], {NOTE_KEY[8], Channel_1}};
NoteButton key9{PIN_KEY[9], {NOTE_KEY[9], Channel_1}};

static void sendVersion() {
  const uint8_t msg[] = {0xF0, protocol::SYSEX_PREFIX[0], protocol::SYSEX_PREFIX[1],
                         protocol::SYSEX_PREFIX[2], protocol::SX_VERSION,
                         protocol::VERSION_MAJOR, protocol::VERSION_MINOR,
                         protocol::VERSION_PATCH, 0xF7};
  midi.sendSysEx(msg);
}

// The bridge asks after it (re)connects; faders are not motorised so their positions are only
// known by reading them.
static void dump() {
  for (auto *f : faders) f->forcedUpdate();
  sendVersion();
}

struct Callbacks : MIDI_Callbacks {
  void onSysExMessage(MIDI_Interface &, SysExMessage m) override {
    // m.data holds F0 ... F7.
    constexpr uint16_t P = sizeof(protocol::SYSEX_PREFIX);
    if (m.length < 1 + P + 2 + 0 || m.data[0] != 0xF0 || m.data[m.length - 1] != 0xF7) return;
    for (uint16_t i = 0; i < P; i++)
      if (m.data[1 + i] != protocol::SYSEX_PREFIX[i]) return;
    const uint8_t cmd = m.data[1 + P];
    const uint8_t *args = m.data + 2 + P;
    const uint16_t n = m.length - 3 - P; // minus F0, prefix, cmd, F7
    switch (cmd) {
    case protocol::SX_RING: lights::setRing(args, n); break;
    case protocol::SX_KEY_LIGHT: lights::setKeyLight(args, n); break;
    case protocol::SX_DUMP_REQUEST: dump(); break;
    }
  }
} callbacks;

void setup() {
  RelativeCCSender::setMode(TWOS_COMPLEMENT);
  Control_Surface.begin();
  midi.setCallbacks(callbacks);
  lights::begin();
}

void loop() {
  Control_Surface.loop();
  lights::update(millis());
}
