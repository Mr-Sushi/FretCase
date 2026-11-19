# Milestone 1

Goal: the whole first-version flow runs offline on one machine, with the on-screen simulator standing in for the hardware. Hum or type, get a seed card, generate a six-track song, play it, change it with the panel and the screen, preview and "print" a card (to a PNG), scan it back.

Online paths (model calls, vocal synthesis, stylisation by model, upload) and GPS are milestone 2. Build the adapter seams for them, but no outside calls.

Each agent works in its own git worktree on its own branch and commits there. Do not push; the lead merges. Read `AGENTS.md` first.

FretStudio's source, data and tests are available read-only at `/home/claude/work/fretstudio-src/` (a copy of the working tree, which is newer than FretStudio's `main`).

## Agent A: `engine/` and `server/`  (branch `m1-engine-server`)

1. **Port the engine.** Create the Python package `engine/fretcase_engine/` with the modules listed in `docs/porting-from-fretstudio.md` ("搬进 engine/"), their data files, and their tests. Where a ported module imports a FretStudio module that is not on the list (for example `learner_model.normalize_chord_symbol`, `expert_runtime`, `key_tempo_validator`, `playability_critic`, `music_representation`), copy that module unchanged too and note it in `engine/PORTED.md`. Change only imports. All ported tests must pass; report the number.
2. **Song model in Python.** Generate Pydantic v2 models from `shared/schema/song.schema.json` (for example with `datamodel-code-generator`) and add a check that the server's example output validates against the schema.
3. **Generation, offline.** From a confirmed seed card: melody from the motif (fitted and repeated to the section plan) or, without a motif, from `offline_melody`; harmony from the library and rule candidate sources ranked by HRE, voiced by ACS, with the capo rule; guitar notes realised from the rhythm preset chosen by density (see `docs/api.md` for the level mapping and nearest-level rule; take the realisation logic from FretStudio's `client/src/lib/rhythmRealization.ts`); bass and drums by simple rules from harmony and density.
4. **HTTP API.** Everything in `docs/api.md` that is not marked v2, except card stylisation and printing internals (see below). Store songs, history and assets as files under a data directory set by `FRETCASE_DATA`. Hum transcription with Basic Pitch; if it cannot be installed in your environment, say so and keep the endpoint returning a seed card without a motif.
5. **Cards.** Implement `/card/preview` and `/card/print` against the Python interface in the section "Card module" below. Agent C builds that module in parallel, so test against a stub that follows the interface; the lead wires the real one after merging.
6. **Panel relay.** `/ws/panel` as described in `docs/api.md` and the panel schema, with validation and `peer.status`.
7. **Tests.** pytest for the engine, generation (every meter, with and without capo, every density level), each endpoint, revision conflicts, locks surviving regeneration, undo, and the panel relay.

## Agent B: `app/`  (branch `m1-app`)

1. Vite, React, TypeScript. Generate TypeScript types from the two schemas.
2. API client for `docs/api.md`, plus a mock mode (no server) that serves `shared/schema/examples/song.json` and applies edits in memory, so the app runs on its own.
3. Four views for an iPad in landscape (1180 × 820 CSS px): capture and seed card (rear camera, hold-to-record microphone, text), whole song (six coloured track lanes, sections, chords, play position), single-track edit (drag note blocks, snapping to the key; lyrics for the vocal track), card preview (style, line, message, city, show photo or city, then print).
4. Playback with Tone.js: one instrument and one gain per track, faders driving gain, ambience clips, loop of the section under the play position while editing.
5. Panel client: connect to `/ws/panel` as `app`, interpret panel messages exactly as `docs/api.md` describes (long press, debounce, detents per bar), and send `ring.set` and `key.light`.
6. Scan a card's QR code with the front camera (BarcodeDetector, falling back to jsQR) and load the song.
7. Tests with Vitest for the panel interpretation, edit flows in mock mode and playback scheduling; `npm run build` must pass.

## Agent C: `device/`  (branch `m1-device`)

1. **Bridge** (`device/bridge/`): asyncio service that reads the controller over MIDI (mido and python-rtmidi), turns MIDI into panel messages using a mapping file, connects to `/ws/panel` as `panel` with reconnect and ping, sends a `snapshot` after connecting, and turns `ring.set` and `key.light` back into MIDI for the controller's lights. Validate every outgoing message against the panel schema. Tests with a fake MIDI port and a fake WebSocket server.
2. **Firmware** (`device/firmware/`): Control Surface sketch for Teensy 4.1 (Pico as an alternative build), with one header for pins: platter encoder, four knob encoders, six faders, ten keys, a 16-pixel ring and key LEDs. It sends the MIDI the bridge's default mapping expects. If `arduino-cli` is not available, say that it is uncompiled.
3. **Simulator** (`device/simulator/`): a standalone web page that draws the panel in 2D (platter, four knobs, six coloured track keys with faders, four round keys, the ring), connects to `/ws/panel` as `panel`, sends the same messages as the hardware, and shows the lights the app sends. It must also run without a server, logging the messages it would send.
4. **Card module** (`device/card/`): the Python package described below, with Pillow and `qrcode`, offline stylisation filters for ink, comic and xieyi, and a printer class using python-escpos with a dry-run mode that writes PNG files. Tests render sample cards for each style and for a card with no photo.

## Card module

Package `fretcase_card` in `device/card/`. Agent A's server imports it; agent C implements it.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

Style = Literal["ink", "comic", "xieyi", "original", "text"]

@dataclass
class CardInput:
    title: str
    style: Style
    share_url: str                 # encoded in the QR code
    date_text: str                 # e.g. "2026.11.18"
    line: Optional[str] = None     # printed on the front when there is no photo
    city: Optional[str] = None     # printed on the back only when not None
    photo_path: Optional[Path] = None

@dataclass
class CardImages:
    front_png: bytes   # 384 px wide, 1-bit, for a 58 mm printer at 203 dpi
    back_png: bytes    # same width
    strip_png: bytes   # front, fold mark, back: what is printed

def render_card(card: CardInput) -> CardImages: ...

class PrinterError(Exception): ...

class Printer:
    def __init__(self, device: str | None = None, dry_run_dir: Path | None = None): ...
    def status(self) -> dict: ...        # {"connected": bool, "paper": "ok" | "out" | "unknown"}
    def print_strip(self, strip_png: bytes) -> None: ...   # raises PrinterError
```

`render_card` must be deterministic for the same input so that a preview and a print match.
