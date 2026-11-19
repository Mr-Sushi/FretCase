# device/bridge

Async Python service on the Pi: reads the controller over USB MIDI, sends panel events to the app over WebSocket, and sends light states back. Owner: agent C.

Package `fretcase_bridge`. Messages follow `shared/schema/panel-events.schema.json`; the bridge validates every message it sends and every message it receives against it.

## Run

```
cd device
uv sync --extra midi           # --extra midi needs libasound2-dev (python-rtmidi builds against ALSA)
uv run fretcase-bridge --list-ports
uv run fretcase-bridge --url wss://<pi>:8443/ws/panel --cafile /path/to/rootCA.pem
```

Options: `--midi-port NAME` (part of the controller's port name; default tries `FretCase`, `Teensy`, `Pico`), `--mapping FILE`, `--insecure`. The URL can also come from `FRETCASE_PANEL_URL`. The schema is found at `../shared/schema/` relative to the repository; set `FRETCASE_PANEL_SCHEMA` when the package is installed elsewhere.

## Behaviour

- Connects as role `panel`, name `bridge`; sends `hello` (seq 0) then `snapshot`. A new `snapshot` follows every `peer.status` where the app goes from absent to present. `seq` restarts at 0 on every connection.
- Platter and knob detents are summed and sent at most every 20 ms (split if more than 64 or 32). Faders are sent when they moved by at least 0.01 from the last value sent (the ends 0 and 1 always), at most every 20 ms. Key down and up are sent at once, with the time they happened in `t`.
- Events that happen while the link is down are dropped, not replayed; held keys and fader positions are in the next `snapshot`.
- `ping` every 2 s; if nothing at all is heard for 5 s the link is closed and reopened (back-off 0.5, 1, 2, 5 s). Incoming `ping` is answered with `pong`.
- `ring.set` and `key.light` become SysEx for the controller. They are cached and sent again when the controller reappears (USB unplugged and plugged in). On every (re)connect of the controller a SysEx asks it to send its fader positions.
- The controller port is found by name and re-opened when it comes back.

## MIDI mapping

`fretcase_bridge/mapping.default.json` is the single description of the mapping; the firmware's `protocol.h` repeats it and must be kept in step. All on channel 1.

| Control | MIDI |
| --- | --- |
| Platter | CC 16, relative, two's complement (1 to 63 forward, 127 down to 65 back) |
| Knobs 明暗, 简繁, 疏密, 速度 | CC 17, 18, 19, 20, relative, two's complement |
| Faders vocal, melody, guitar, bass, drums, ambience | CC 21 to 26, absolute 0 to 127 |
| Keys capture, play, undo, another | note 36, 37, 38, 39 (note on = down, note off or velocity 0 = up) |
| Track keys vocal to ambience | note 40 to 45 |

Lights, bridge to controller, SysEx `F0 7D 46 43 <cmd> ... F7` (7D is the non-commercial manufacturer ID, 46 43 is "FC"; all data bytes 0 to 127, colours are 7 bit per channel):

| cmd | Meaning | Data |
| --- | --- | --- |
| 01 | Ring | brightness (0 to 127), then 16 times r g b (off is 0 0 0) |
| 02 | Key light | key note, mode (0 off, 1 on, 2 blink, 3 pulse), has-colour (0 or 1), r g b |
| 03 | Dump request | none; the controller answers with all six fader CCs |
| 04 | Version (controller to bridge) | major minor patch; sent after a dump request |

## Tests

```
cd device && uv run pytest bridge
```

Uses a fake MIDI port and a fake WebSocket server; no hardware and no network.
