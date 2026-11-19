# device/firmware

Controller firmware for Teensy 4.1 (default) or Raspberry Pi Pico, built on the Control Surface library. Owner: agent C.

Sketch: `fretcase_controller/`

| File | What |
| --- | --- |
| `fretcase_controller.ino` | Platter and knob encoders (relative CC), fader potentiometers (absolute CC), key buttons (notes), SysEx in for lights |
| `pins.h` | The only file with pin numbers, encoder resolution and LED wiring |
| `protocol.h` | CC numbers, note numbers and SysEx commands; repeats `../bridge/fretcase_bridge/mapping.default.json` |
| `lights.h` | Ring (16 WS2812) and key LEDs (10 WS2812) state and animation: off, on, blink (1 Hz), pulse |

The MIDI it sends is the bridge's default mapping; see `../bridge/README.md` for the table. Check both after any change.

## Behaviour notes

- Platter and knobs send one relative CC (two's complement) per detent.
- Faders are not motorised. The bridge sends SysEx "dump request" after it (re)connects; the firmware answers with all six fader CCs and its version.
- The capture key is red and the six track keys have their track colours; `key.light` colours apply only to play, undo and another. At power-up the capture and track keys are lit and the three cream keys are off, until the app says otherwise.
- The ring is wired clockwise starting at the top pixel (`RING_CLOCKWISE_WIRING` in `pins.h`).

## Build

Libraries: Control Surface 2.x, FastLED, Encoder (included with Teensyduino).

```
arduino-cli core install teensy:avr         # needs the Teensy package index URL in arduino-cli config
arduino-cli lib install "Control Surface" FastLED
arduino-cli compile --fqbn teensy:avr:teensy41:usb=midi fretcase_controller
```

For the Pico (earlier-Philhower core, TinyUSB stack): `--fqbn rp2040:rp2040:rpipico:usbstack=tinyusb`. The Pico build puts the six faders on a CD74HC4051 multiplexer because the Pico has only three analog pins; see `pins.h`.

## Status

Not compiled with `arduino-cli`: it is not installed here and the sandbox cannot download the Teensy or RP2040 cores. What was checked: the sketch and its headers were compiled with `g++ -fsyntax-only` against the Control Surface 2.1.3 sources and the library's Arduino mock (with FastLED and the USB MIDI class stubbed), once with the Teensy pin branch and once with the Pico branch; no errors in this directory. The encoder, potentiometer, button, multiplexer and SysEx callback calls were checked against the library headers that way. Hardware behaviour (encoder direction, ADC range, LED timing, USB MIDI port name) is untested. If an encoder turns the wrong way, swap its A and B pins in `pins.h`.

The Teensy shows up as "Teensy MIDI"; the bridge finds ports whose name contains `FretCase`, `Teensy` or `Pico`.
