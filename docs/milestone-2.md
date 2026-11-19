# Milestone 2

Goal: the new flow from the approved screen designs (`docs/ui/`) runs end to end, offline, on one machine:

capture (up to 9 photos, hum, sound, text) → three candidates → pick one → shape it (sections, players, feel) → adjust tracks and lyrics → card preview with a cover photo → print (dry run) → scan the QR code → the song page plays on a phone.

The contract is `shared/schema/song.schema.json` (schema 2.0) and `docs/api.md` (look for **M2**). If you need something the contract does not give you, stop and say so; do not invent fields.

Rules from milestone 1 still hold: read `AGENTS.md`; work only in your directories; every network call has a timeout and an offline path; ported tests keep passing; commit on your own branch in your own worktree; do not push or merge. Report test numbers and anything in the shared interfaces you found missing or ambiguous.

## Agent A: `engine/` and `server/`  (branch `m2-engine-server`)

1. **Schema 2.0.** Regenerate the Pydantic models (`engine/gen_song_model.sh`). Songs on disk from milestone 1 may be dropped; no migration needed.
2. **Regions.** Every track has one region per section. Generation reads them: `play: false` gives no notes; `complexity` and `intensity` drive note count, ornaments, fills and velocity (map them like GarageBand Drummer's XY pad: right adds notes and fills, up raises velocity); `style` picks the pattern (catalogue in `docs/api.md`; guitar styles map to rhythm families and presets as described there, choosing the preset level from complexity with the nearest-level rule). The density knob sets the complexity of every unlocked guitar, bass and drums region.
3. **Edit ops** `setRegion`, `copyRegion`, `setLead`, `shiftRegister`, `revertMelody`, `setMaster`, and the changed `setCard` and `setLyrics` (line-by-line matching), exactly as `docs/api.md` describes, each undoable.
4. **Candidates.** `POST /api/candidates` and `POST /api/songs/{id}/choose`. The three must sound clearly different: vary instruments, styles, harmony colour (lane) and lead, and use `timeOfDay`. Fill `candidate.name`, `tags`, `why` and `parts` by rules offline (short Chinese, no jargon: say 温暖, 轻快, 安静, 木吉他扫弦, not "D major" or "arpeggio"). Drafts are hidden from `GET /api/songs` and expire after 24 h.
5. **Lyrics.** New songs offline get 啦 on every vocal note. Implement `POST …/lyrics`, `POST …/lyrics/alternatives` and `GET …/lyrics/themes` through the model adapter layer: one adapter for a text model, configured by environment variables (`FRETCASE_TEXT_MODEL_URL`, `FRETCASE_TEXT_MODEL_KEY`, `FRETCASE_TEXT_MODEL_NAME`; Anthropic Messages API format), 20 s timeout, `503 offline_unavailable` when it is not configured or fails. The server, not the model, guarantees that every returned line has exactly the right number of syllables: validate and retry once, then fail with 503. Tests use a fake adapter; make no real network calls in tests.
6. **Cards.** Use the card module interface below (version 2). Preview stores the print image as an asset with role `card_print` and sets `card.frontAssetId`. Add `GET /api/printer`. Default card style: `xieyi` with photos, `text` without; default cover: the first photo; `photoAssetIds` defaults to every photo input.
7. **Song page.** `GET /api/share/{shareId}/page`, `GET /api/share/{shareId}/assets/{assetId}` (only the assets the page lists), and `GET /s/{shareId}` serving `song.html` from the app build directory (`FRETCASE_APP_DIST`, default `app/dist`; answer 404 with a short text if it is missing). QR URLs use `FRETCASE_SHARE_BASE`.
8. **Tests.** Every new op, candidates (three valid songs, different `parts`), choose, region regeneration (play off, style change, locks), lead, register limits, revert without motif, line-by-line lyrics errors, lyrics endpoints with a fake model and with none (503), the page endpoint's privacy rules (no city when `showCity` is false, no photos when `showPhoto` is false, no `seed`), photos limit. The schema examples must still validate against your Pydantic model.

## Agent B: `app/`  (branch `m2-app`)

Rebuild the screens to match `docs/ui/` (read `docs/ui/README.md` first). Keep what works from milestone 1 (API client, panel client, player, scanning), and replace the old views. Regenerate types from the schemas.

1. **采集** (`Main.dc.html`): rear camera with a photo strip (up to 9; the tenth is refused with a short message), hold-to-record hum and sound, text (and hold-to-speak if the browser supports speech recognition; skip quietly if not). Each captured item shows in the "今天收集到的" list with a remove action. "做成歌" uploads assets, calls `POST /api/seed`, then `POST /api/candidates`.
2. **选一首** (`Pick.dc.html`): three cards from `candidate` (name, tags, `parts` bars, `why`), each with a 15-second preview that starts at the chorus (the section with `lead: vocal`, else the middle). 白天 / 黄昏 / 夜晚 calls candidates again with `timeOfDay`; "都不像，再来三首" sends `previousGroupId`. "就要这首" calls `choose`.
3. **打磨** (`Shape.dc.html`): section tiles with lyrics as whole lines (never one character per note), a plain sentence for what plays there (built from regions, e.g. 只有吉他和海浪), 换一段 (`another`) and 保留 (`lock`); the players list (sound, 主角 → `setLead` for the selected section, volume, mute); the four feel dials.
4. **音轨** (`Detail.dc.html`): whole-song row with sections, master volume and 空间感 (`setMaster`); six track rows with mute and solo (solo is app-side only), one cell per region; the region editor with a 3 × 3 pad (complexity × intensity), style chips, sound chips, 再演一次 (`another` with track), 每一段都这样 (`copyRegion`), 低一点 / 高一点 (`shiftRegister`, hidden for drums and ambience), 用回我哼的 (`revertMelody`, vocal and melody only, hidden without a motif), 这一段不演奏 (`setRegion play false`).
5. **歌词** (`Lyrics.dc.html`): every section's lines from vocal notes (`lineEnd`), with "n 字 / m 个音" and the rhyme of the last syllable (use a small pinyin final table in the app; offline is fine), keep toggles held in app state, 换个说法 (`lyrics/alternatives`), themes (`lyrics/themes`), tone and rhyme, "按这些重写没保留的句子" (`lyrics` with `keep`). When those calls answer 503, show that rewriting needs the network and leave typing available.
6. **做卡** (`Card.dc.html`): cover picker from `photoAssetIds`, style, title, line, message, toggles, preview image from `frontAssetId`, film count from `GET /api/printer`, print. Link to the song page.
7. **Song page**: a second Vite entry `song.html` (phone layout from `SongPage.dc.html`): photo with a row of thumbnails, title, city and date, player with section bar, lyrics with the current line highlighted, message, card image, save (download a recording made in the browser with `Tone.Offline` or the MediaRecorder API) and share (Web Share API, else copy the link). It loads `/api/share/{shareId}/page` and plays the song with the same player code as the app. It must build to `dist/song.html`.
8. **Player**: per-track instruments from the catalogue ids (sampled where you have free samples bundled, synthesised otherwise), master volume, reverb by `master.space`, the vocal guide tone using the vocal instrument.
9. **Panel**, per screen: 采集: red key short press = photo, hold = hum. 选一首: platter moves focus between the three cards (4 detents each), play key plays the focused one, another key = 再来三首. 打磨: as milestone 1. 音轨: platter moves the selected region's section, track keys select the row, the complexity knob sets the selected region's complexity and the density knob its intensity (`setRegion`, debounced 400 ms); brightness and tempo keep their global meaning. 做卡: platter cycles styles.
10. **Mock mode** keeps working with the new endpoints (three candidates built from the example song), so the app runs alone.
11. **Tests** (Vitest): photo limit, candidate flow, region editor ops, lyrics line counting and rhyme labels, song page loading and privacy (it shows only what the page JSON gives), panel mapping per screen. `npm run build` produces `index.html` and `song.html`.

## Agent C: `device/`  (branch `m2-device`)

1. **Card module version 2** (`device/card/`), interface below. Layout as in `docs/ui/card-print-example.jpg`: picture 1260 × 610 on top, paper strip (`#F7F1E4`) 230 px below with the title (serif, about 64 px), line (about 28 px), city · date (about 24 px) and a 178 px QR code (error correction H) with a note mark in its centre; nothing over the picture. Style `text`: the picture area is paper with the line (or the title) set large. Offline filters for `ink`, `comic`, `xieyi`, `original` (the OpenCV ideas in `docs/ui/mock.py` are a starting point; improve `comic`). Deterministic output. The QR code must decode (test it with OpenCV's QR detector or `pyzbar`).
2. **Printers.** `Printer` with three kinds chosen by `FRETCASE_PRINTER`: `dry_run` (default; writes PNGs to a directory), `instax` or `instax:<BLE address>` (Instax Wide Link over Bluetooth LE with `bleak`, following the open protocol notes of javl/InstaxBLE; check that library's licence before copying any code and say what you did), and `thermal:usb:<vid>:<pid>` (the milestone 1 escpos path: rotate the print image 90°, dither to 384 px wide). The instax backend cannot be tested on hardware here: test the packet framing and image encoding against the protocol notes with a fake BLE client, and say clearly that it is untested on a device.
3. **Simulator**: add the screen names to its log and keep it working with the unchanged panel protocol. No other changes needed.
4. **Tests**: every style with and without a cover, a long title and line (they must fit or shrink, never overflow), CJK font missing (clear error), QR decoding, each printer kind's dry path.

## Card module, version 2

Package `fretcase_card` in `device/card/`. Agent A's server imports it; agent C implements it. This replaces the milestone 1 interface.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

Style = Literal["ink", "comic", "xieyi", "original", "text"]

@dataclass
class CardInput:
    title: str
    style: Style
    share_url: str                    # encoded in the QR code
    date_text: str                    # e.g. "2026.11.19"
    line: Optional[str] = None        # under the title in the strip; large on the picture area for style "text"
    city: Optional[str] = None        # printed before the date only when not None
    cover_path: Optional[Path] = None # required unless style == "text"

@dataclass
class CardImages:
    print_png: bytes    # 1260 x 840 RGB: the Instax Wide image area
    preview_png: bytes  # the same image at 630 x 420, for the screen

def render_card(card: CardInput) -> CardImages: ...   # ValueError for bad input, OSError for an unreadable cover or a missing CJK font

class PrinterError(Exception): ...

class Printer:
    def __init__(self, spec: str | None = None, dry_run_dir: Path | None = None): ...
        # spec: "dry_run" | "instax" | "instax:<address>" | "thermal:usb:<vid>:<pid>"; None reads FRETCASE_PRINTER, default "dry_run"
    def status(self) -> dict: ...
        # {"kind": "instax" | "thermal" | "dry_run", "connected": bool, "paper": "ok" | "out" | "unknown", "remaining": int | None}
    def print_card(self, print_png: bytes) -> None: ...   # raises PrinterError
```

`render_card` must be deterministic for the same input so that the preview and the print match.
