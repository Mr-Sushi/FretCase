# API

The server runs on the Raspberry Pi at `https://<pi>:8443`. The app is served from the same origin. All bodies are JSON unless noted. Types refer to `shared/schema/song.schema.json` (`Song`, `SeedCard`, `Asset`, …) and `shared/schema/panel-events.schema.json`.

This is the version 1 contract. Endpoints marked **v2** are specified now so that shapes do not change later, but may return `501 not_implemented` until the second release.

## Conventions

### Songs change only through the server

The app never builds or patches a `Song` itself. Every change goes through an endpoint below, and every such endpoint returns the whole new `Song`. The app replaces its copy with the response.

### Revisions

Every change increases `Song.revision` by one. Requests that change a song carry `baseRevision`, the revision the app last received. If the song has moved on, the server answers `409 revision_conflict` with the current song in `error.song`; the app replaces its copy and lets the user retry.

### Locks

Regeneration (the knobs, "another take", re-humming) never changes locked content. A lock covers a whole track, a whole section, or one track in one section (`Song.locks`). Editing notes by hand on any track adds a lock for that track and the sections touched.

### Errors

```json
{ "error": { "code": "revision_conflict", "message": "Song is at revision 12", "song": { } } }
```

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Body does not match the schema |
| 404 | `not_found` | Unknown song, asset, share or job |
| 409 | `revision_conflict` | `baseRevision` is stale; `error.song` holds the current song |
| 422 | `cannot_apply` | Valid request that cannot be applied, e.g. a lock on a section that does not exist |
| 501 | `not_implemented` | v2 endpoint not built yet |
| 503 | `offline_unavailable` | Needs the network and there is none, and no offline path exists |

### Online and offline

Every call to an outside service has a timeout (default 8 s) and falls back to the offline path where one exists. A response produced offline still succeeds; the song's `provenance` and the seed card's `source` say which path ran. Only operations with no offline path (lyrics generation, vocal synthesis, stylisation by model, upload) answer `503 offline_unavailable`, and the app shows that state without retrying in a loop.

### Long operations

Operations that may take longer than about 2 s (vocal synthesis, whole-song rendering, upload) return `202` with a job. Everything else answers synchronously.

```json
{ "job": { "id": "job-7f3a2c", "state": "running" } }
```

`GET /api/jobs/{id}` returns `{ "job": { "id", "state": "running" | "done" | "failed", "result"?, "error"? } }`. Poll every second.

## Status and catalogue

### `GET /health`

```json
{ "ok": true, "online": true, "version": "0.1.0", "panel": true }
```

`online`: whether the server reached the internet in the last 30 s. `panel`: whether a panel is connected to `/ws/panel`.

### `GET /api/catalog`

What the controls and screens can choose from.

```json
{
  "instruments": { "vocal": ["synth-female", "synth-male"], "melody": ["piano", "nylon-lead"], "guitar": ["nylon", "steel"], "bass": ["finger-bass"], "drums": ["brush-kit", "pop-kit"], "ambience": ["recording"] },
  "rhythmPresets": "the contents of shared/data/rhythm-presets.json",
  "cardStyles": ["ink", "comic", "xieyi", "original", "text"]
}
```

## Assets

### `POST /api/assets`

Multipart form: `file` (the recording or image) and `role` (`hum`, `ambience`, `photo`, `vocal_take`). Returns `{ "asset": Asset }`. Audio is stored as received; the server reads its duration.

### `GET /api/assets/{id}`

The file, with its MIME type.

## Seed card

### `POST /api/seed`

Analyse the captured inputs and propose a seed card. Hum recordings are transcribed to `motif`; photos, text and sounds set key, tempo, mood and instruments, with a reason for each.

Request:

```json
{ "inputs": [ { "kind": "hum", "assetId": "a-hum-01" }, { "kind": "photo", "assetId": "a-photo-01" } ] }
```

Response: `{ "seed": SeedCard }`.

Offline: transcription runs locally; photo and text use colour statistics and keywords; `seed.source` is `offline`.

## Songs

### `POST /api/songs`

Generate a song from a seed card the user has confirmed (and possibly edited).

Request: `{ "seed": SeedCard, "bars": 16 }`. `bars` is optional (default 16; 8 when the motif is shorter than 4 bars).

Response: `201 { "song": Song }`. The new song has default sections (开头, 展开, 高潮, 结尾 for 16 bars), all faders at 0.8, no locks, and controls at 0.5.

### `GET /api/songs`

Songs on this device, newest first: `{ "songs": [ { "id", "title", "updatedAt", "card"? } ] }`.

### `GET /api/songs/{id}`

`{ "song": Song }`.

### `POST /api/songs/{id}/edits`

Apply one or more edits in order, as one revision.

```json
{ "baseRevision": 12, "ops": [ { "op": "setTrackVolume", "track": "drums", "volume": 0.45 } ] }
```

Response: `{ "song": Song }`.

| `op` | Fields | Effect |
| --- | --- | --- |
| `setControl` | `control`: `brightness` \| `complexity` \| `density`; `value` 0–1 | Stores the value and regenerates the unlocked parts it affects: brightness and complexity re-harmonise (and re-voice guitar, regenerate bass); density changes the guitar rhythm preset and drums |
| `setTempo` | `tempo` | Changes tempo only. The tempo knob moves 1 BPM per detent, debounced like the feel knobs, clamped to 40–220 |
| `setTrackVolume` | `track`, `volume` 0–1 | Fader |
| `setTrackMute` | `track`, `muted` | Long press on a track key |
| `setInstrument` | `track`, `instrument` | Instrument id from the catalogue |
| `replaceNotes` | `track`, `from` tick, `to` tick, `notes` | Replaces every note starting in [from, to) on that track. Adds a lock for that track in the sections touched. Not allowed on `ambience`. On `vocal`, notes use the vocal note shape and may carry `lyric` and `lineEnd`, so lyrics survive a pitch edit |
| `setLyrics` | `section`, `text` | Assigns the text syllable by syllable to vocal notes in that section, one character per note for Chinese. Answers `422 cannot_apply` with `error.detail.noteCount` and `error.detail.syllableCount` when they differ |
| `setRhythm` | `family`, `presetId` | Guitar rhythm by hand; overrides density until density is turned again |
| `lock` | `track`?, `section`? | Adds a lock (at least one field) |
| `unlock` | `track`?, `section`? | Removes exactly that lock |
| `setSections` | `sections` | Replaces the section list; must be contiguous and cover every bar |
| `setTitle` | `title` | |
| `setCard` | any of `style`, `line`, `message`, `photoAssetId`, `showPhoto`, `city`, `showCity` | Card fields shown on the preview. Changing any of them clears `frontAssetId` and `backAssetId`, so a new preview is needed before printing |
| `setVocalTake` (v2) | `assetId` | Uses the user's own recording as the vocal track: `source = "recording"`, `renderAssetId = assetId` |

Mapping of the feel knobs. The app sends absolute values; the panel's encoder deltas are turned into values by the app (one detent = 0.02).

| Control | 0 – 0.33 | 0.33 – 0.67 | 0.67 – 1 |
| --- | --- | --- | --- |
| complexity | lane `basic` | lane `explore` | lane `colour` |
| density | rhythm level `start` | `next` | `challenge` |
| brightness | darker: prefer minor colour, relative minor at ≤ 0.1 | neutral | brighter: prefer major colour, relative major at ≥ 0.9 |

If the song's meter has no preset at the requested rhythm level (in `rhythm-presets.json` 2/4 and 3/4 have only `start`, 6/8 only `next`), the server uses the nearest level that exists.

### `POST /api/songs/{id}/another`

"Another take". Regenerates the unlocked content of one section.

Request: `{ "baseRevision": 12, "section": "s-verse", "track": "guitar" }`. `track` is optional: without it, every unlocked track in the section is regenerated; with it, only that track. The app sends `track` when a track key is selected.

Response: `{ "song": Song }`. Successive calls on the same section and revision chain do not repeat a take until the candidates run out; the server keeps the candidate list from FretStudio's harmony pipeline for this.

### `POST /api/songs/{id}/rehum`

Replace the melody of one section with a new hum.

Request: `{ "baseRevision": 12, "section": "s-verse", "assetId": "a-hum-02" }`.

Response: `{ "song": Song }`. The new melody is transposed into the song's key and fitted to the section's length; harmony in that section is regenerated unless locked; the vocal track follows the melody unless the vocal track is locked.

### `POST /api/songs/{id}/undo`

Request: `{ "baseRevision": 12 }`. Takes back the most recent action that has not been undone yet and stores the result as a new revision (13). Pressing undo again takes back the action before that, up to 50 actions. Undo itself is not an action, so it cannot be undone (there is no redo key). Response: `{ "song": Song }`. `422 cannot_apply` when there is nothing left to undo.

### `GET /api/songs/{id}/history`

`{ "history": [ { "revision", "at", "action" } ] }`, newest first, for the study log and debugging. `action` is the op or endpoint name.

### `POST /api/songs/{id}/lyrics` (v2)

Write lyrics for a section from the song's mood and the user's text input, one syllable per vocal note. Request: `{ "baseRevision", "section", "hint"? }`. Response: `{ "song": Song }`. Offline: `503`.

### Vocal playback before synthesis

While `tracks.vocal.source` is `none`, the app plays the vocal notes as a plain guide tone, so the line can be heard and edited. When `renderAssetId` is set, the app plays that audio instead of the notes.

### `POST /api/songs/{id}/vocal` (v2)

Synthesise the vocal track from notes and lyrics. Request: `{ "baseRevision" }`. Response: `202` job; its result is `{ "song": Song }` with `tracks.vocal.source = "synth"` and `renderAssetId` set. Offline: `503`. A user's own take is uploaded as an asset with role `vocal_take` and attached with the `setVocalTake` edit.

### `GET /api/songs/{id}/export?format=midi|musicxml|abc`

The song as a file. MIDI carries all six tracks; MusicXML and ABC carry melody, lyrics and chord symbols with guitar diagrams.

## Cards

### `POST /api/songs/{id}/card/preview`

Render the card images for the current card fields. Request: `{ "baseRevision" }`. Response: `{ "song": Song }` with `card.frontAssetId` and `card.backAssetId` set (the back image carries the QR code), and a reserved `card.share` (`state: "reserved"`) so the QR code is final before printing. Stylisation by model is v2; in v1 and offline, `ink`, `comic` and `xieyi` use local filters.

### `POST /api/songs/{id}/card/print`

Print the previewed card. Request: `{ "baseRevision" }`. Refused with `422 cannot_apply` unless a preview exists for the current card fields, so nothing is printed without a preview. Response: `{ "song": Song }` with `card.printedAt` set. Printer errors (no paper, not connected) answer `422` with `error.detail.printer`.

### `POST /api/songs/{id}/share` (v2)

Upload the song page (audio, real photo if `showPhoto`, city if `showCity`, message, lyrics). Response: `202` job. Offline: the share moves to `queued` and uploads when the network returns; the response is then `200 { "song": Song }`.

### `GET /api/share/{shareId}`

Resolve a scanned card. Response: `{ "songId": "…" }` when the song is on this device. For a song made on another FretCase (v2), the server fetches it from the song page; offline it answers `503`.

QR codes encode the song page URL, `https://<song-page-host>/s/{shareId}`. The app recognises that pattern when scanning and calls this endpoint.

## Location

### `GET /api/location`

`{ "city": "Newcastle upon Tyne", "source": "gps" | "manual" | "none" }`. GPS coordinates are turned into a city name online; offline the server keeps the coordinates and fills in the city later. The server never returns coordinates to the app. `city` is `null` when no place is known (no GPS fix and nothing typed or said), with `source: "none"`.

### `PUT /api/location`

`{ "city": "Lisbon" }`, from the user saying or typing a place. Overrides GPS until the next song.

## System

### `POST /api/system/shutdown`

Called by the power switch service before power is cut, and by the app's shutdown button. Flushes the study log and stops the server. Response: `202`.

### `POST /api/study/log`

`{ "events": [ { "at", "type", "detail" } ] }`. `detail` is optional and may be any JSON value. The app logs panel and screen actions here (as FretStudio's study log does) for later analysis.

## Panel WebSocket

### `wss://<pi>:8443/ws/panel`

Messages are defined in `shared/schema/panel-events.schema.json`. One panel and one app may be connected at a time; a second connection with a taken role gets `error` with `role_taken` and is closed.

Division of work:

- The **panel** (hardware bridge or on-screen simulator) sends only raw actions: `platter.turn`, `knob.turn`, `fader.move`, `key` down/up, and a `snapshot` of absolute positions after connecting.
- The **app** turns them into meaning and calls the HTTP API: long press (≥ 600 ms) on `capture` records, short press takes a photo; long press on a track key mutes, short press selects; platter detents move the play position (default 4 detents per bar) and the section under it becomes the target of `another`; a fader movement becomes `setTrackVolume` (debounced to one call per 150 ms per fader); a feel knob becomes `setControl` (debounced to one call 400 ms after the last detent).
- The app sends `ring.set` and `key.light` back. Suggested ring: one pixel per bar group, the current position in the accent colour, locked sections dimmed. The ring shows colours only; blinking and pulsing are available on key lights, not on the ring.
- `seq` restarts at 0 on each new connection. Any frame received counts as proof that the link is alive.
- Events that happen while the link is down are dropped; held keys and fader positions arrive in the next `snapshot`.
