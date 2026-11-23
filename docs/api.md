# API

The server runs on the Raspberry Pi at `https://<pi>:8443`. The app is served from the same origin. All bodies are JSON unless noted. Types refer to `shared/schema/song.schema.json` (`Song`, `SeedCard`, `Asset`, …) and `shared/schema/panel-events.schema.json`.

This is the milestone 2 contract (song schema 2.0). Endpoints marked **v2** are specified now so that shapes do not change later, but may return `501 not_implemented` until they are built. Endpoints marked **M2** are new in milestone 2.

## Conventions

### Songs change only through the server

The app never builds or patches a `Song` itself. Every change goes through an endpoint below, and every such endpoint returns the whole new `Song`. The app replaces its copy with the response.

### Revisions

Every change increases `Song.revision` by one. Requests that change a song carry `baseRevision`, the revision the app last received. If the song has moved on, the server answers `409 revision_conflict` with the current song in `error.song`; the app replaces its copy and lets the user retry.

### Locks

Regeneration (the knobs, "another take", re-humming, `setLead`) never changes locked content. A lock covers a whole track, a whole section, or one track in one section (`Song.locks`). Editing notes by hand on any track adds a lock for that track and the sections touched. Changing a region by hand (`setRegion`, `copyRegion`, `shiftRegister`) regenerates that track in that section even when it is locked, and then adds the lock for that track in that section, so a later knob turn keeps the user's choice.

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
{ "ok": true, "online": true, "version": "0.1.0", "panel": true, "lyrics": true }
```

`online`: whether the server reached the internet in the last 30 s (a model call worked, or a quick connection to the model host did; checked at most every 30 s). `panel`: whether a panel is connected to `/ws/panel`. `lyrics`: whether a text model is configured for writing lyrics (`FRETCASE_TEXT_MODEL_KEY` is set); it says nothing about whether the network is up.

### `GET /api/catalog`

What the controls and screens can choose from.

```json
{
  "instruments": {
    "vocal": [ { "id": "synth-male", "label": "Male voice" }, { "id": "synth-female", "label": "Female voice" }, { "id": "synth-soft", "label": "Soft voice" } ],
    "melody": [ { "id": "harmonica", "label": "Harmonica" }, { "id": "piano", "label": "Piano" }, { "id": "whistle", "label": "Whistle" }, { "id": "flute", "label": "Flute" } ],
    "guitar": [ { "id": "steel", "label": "Steel-string guitar" }, { "id": "nylon", "label": "Nylon guitar" }, { "id": "electric-clean", "label": "Electric guitar (clean)" }, { "id": "ukulele", "label": "Ukulele" } ],
    "bass": [ { "id": "finger-bass", "label": "Finger bass" }, { "id": "upright-bass", "label": "Upright bass" }, { "id": "synth-bass", "label": "Synth bass" } ],
    "drums": [ { "id": "jazz-kit", "label": "Jazz kit" }, { "id": "pop-kit", "label": "Pop kit" }, { "id": "hand-drum", "label": "Hand drum" } ],
    "ambience": [ { "id": "recording", "label": "As recorded" } ]
  },
  "styles": {
    "vocal": [ { "id": "plain", "label": "Melody only" }, { "id": "harmony", "label": "Add a harmony" } ],
    "melody": [ { "id": "follow", "label": "Follow the voice" }, { "id": "answer", "label": "Answer when the voice rests" } ],
    "guitar": [ { "id": "strum", "label": "Strum" }, { "id": "arpeggio", "label": "Picked chords" }, { "id": "muted", "label": "Muted strum" }, { "id": "sustain", "label": "Long notes only" } ],
    "bass": [ { "id": "sustain", "label": "Long notes" }, { "id": "groove", "label": "With the drums" }, { "id": "walking", "label": "Walking" } ],
    "drums": [ { "id": "brush", "label": "Brushes" }, { "id": "sticks", "label": "Sticks" }, { "id": "hand", "label": "Hand drum only" } ],
    "ambience": [ { "id": "recording", "label": "As recorded" }, { "id": "soft", "label": "Softer" } ]
  },
  "spaces": [ { "id": "dry", "label": "Dry" }, { "id": "room", "label": "Room" }, { "id": "hall", "label": "Hall" } ],
  "rhythmPresets": "the contents of shared/data/rhythm-presets.json",
  "cardStyles": ["ink", "comic", "xieyi", "original", "text"]
}
```

`instruments` are sounds (`mix.instrument`); `styles` are playing styles (`region.style`). The app shows `label`, never `id`. Guitar styles map to rhythm families: `strum` and `muted` use strumming presets, `arpeggio` arpeggio presets, `sustain` one chord stroke per chord.

## Assets

### `POST /api/assets`

Multipart form: `file` (the recording or image) and `role` (`hum`, `ambience`, `photo`, `vocal_take`). Returns `{ "asset": Asset }`. Audio is stored as received; the server reads its duration. Photos are stored as received and their width and height read; a photo larger than 4096 px on its long side is scaled down on upload.

### `GET /api/assets/{id}`

The file, with its MIME type.

## Seed card

### `POST /api/seed`

Analyse the captured inputs and propose a seed card. Hum recordings are transcribed to `motif`; photos, text and sounds set key, tempo, mood and instruments, with a reason for each. Up to 9 photos are allowed (more answers `400 invalid_request`); several photos are read together. With no photo, the inputs should include text, but the server accepts any non-empty mix.

In the milestone 2 flow the seed card is not shown as a separate screen: the app sends the inputs here and passes the returned seed straight to `POST /api/candidates`.

Request:

```json
{ "inputs": [ { "kind": "hum", "assetId": "a-hum-01" }, { "kind": "photo", "assetId": "a-photo-01" } ] }
```

Response: `{ "seed": SeedCard }`.

Offline: transcription runs locally; photo and text use colour statistics and keywords; `seed.source` is `offline`.

## Songs

### `POST /api/candidates` (M2)

Make three different arrangements of the same seed for the pick screen.

Request: `{ "seed": SeedCard, "bars": 16, "timeOfDay": "dusk", "previousGroupId": "grp-…" }`. `bars`, `timeOfDay` (`day` | `dusk` | `night`) and `previousGroupId` are optional. `timeOfDay` nudges brightness, tempo and instruments (day brighter and faster, night darker, slower and sparser). With `previousGroupId` ("None of these, three more") the server avoids repeating the instrument and style combinations of that group.

Response: `201 { "candidates": [Song, Song, Song] }`. Each song is a draft with `candidate` set (`groupId`, `index` 0–2, `name`, `tags`, `why`, `parts`, `timeOfDay`). The three share the melody from the motif when there is one and differ in harmony colour, instruments, styles and lead. Drafts are not listed by `GET /api/songs` and are deleted 24 hours after creation unless chosen. Offline: names, tags and `why` come from rules; with a model they are written by the model.

### `POST /api/songs/{id}/choose` (M2)

Keep this draft. Request: `{}`. Sets `candidate.chosen = true`, deletes the other drafts of its group, and returns `{ "song": Song }` at once. The song then behaves like any other song (listed, editable, printable). Choosing never waits for a model: when `/health` reports `lyrics: true`, the app calls `POST …/lyrics` right after choosing, in the background, and applies the result only if the song has not changed meanwhile.

### `POST /api/songs`

Generate one song from a seed card. Kept for tools and tests; the app uses `/api/candidates`.

Request: `{ "seed": SeedCard, "bars": 16 }`. `bars` is optional (default 16; 8 when the motif is shorter than 4 bars).

Response: `201 { "song": Song }`. The new song has default sections (Intro, Verse, Chorus, Outro for 16 bars), all faders at 0.8, `master` at volume 0.8 and space `room`, no locks, and controls at 0.5. Every track has one region per section; a region whose track has nothing to play there has `play: false`.

Lyrics on a new song: every vocal note gets the syllable "la" so the line can be sung as a guide tone, and the user can type lyrics. `POST /api/songs` (tools) also tries the model once when one is configured; drafts from `/api/candidates` never call the model.

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
| `setLyrics` | `section`, `text` | Assigns the text syllable by syllable to vocal notes in that section, one character per note for Chinese; punctuation and spaces are ignored. When `text` contains line breaks, each line is matched to one lyric line of the section (the vocal notes up to each `lineEnd`), and `error.detail.lines` lists `{ index, noteCount, syllableCount }` for every line that does not fit. Without line breaks the whole section must fit, with `error.detail.noteCount` and `error.detail.syllableCount` on a mismatch. Both answer `422 cannot_apply` |
| `setRhythm` | `family`, `presetId` | Guitar rhythm by hand; overrides density until density is turned again. Kept for tools; the app uses `setRegion` |
| `lock` | `track`?, `section`? | Adds a lock (at least one field) |
| `unlock` | `track`?, `section`? | Removes exactly that lock |
| `setSections` | `sections` | Replaces the section list; must be contiguous and cover every bar |
| `setTitle` | `title` | |
| `setCard` | any of `style`, `line`, `message`, `photoAssetIds`, `coverAssetId`, `showPhoto`, `city`, `showCity` | Card fields shown on the preview. `coverAssetId` must be one of `photoAssetIds`; setting `style` to `text` removes `coverAssetId`, and setting a photo style without a cover picks the first photo. Changing any field clears `frontAssetId`, so a new preview is needed before printing |
| `setRegion` (M2) | `track`, `section`, any of `play`, `complexity`, `intensity`, `style` | How one track plays in one section (the XY pad and style chips). Regenerates that track in that section and locks it there. `play: false` removes its notes in that section |
| `copyRegion` (M2) | `track`, `section` | "Same in every section": copies that region's `complexity`, `intensity` and `style` to every section of the track (keeping each section's `play`), regenerates, and locks the track |
| `setLead` (M2) | `section`, `track`: `vocal` \| `melody` \| `guitar` \| `null` | Who carries the section. Raises the lead's intensity by about 0.15 and lowers the others' by about 0.1 in unlocked regions of that section; when the vocal leads, an unlocked melody region switches to `answer`. `null` removes the lead and restores the regions' previous values |
| `shiftRegister` (M2) | `track`, `section`, `direction`: `up` \| `down` | "Higher / Lower". Vocal and melody: every note in the section moves one scale step in the song's key. Guitar: the next voicing up or down the neck. Bass: one octave, within E1–G3; notes that would leave that range stay where they are. Not allowed on drums and ambience (`422`); `422` too when nothing can move without leaving the instrument's range |
| `revertMelody` (M2) | `section` | "Back to my hum": restores the melody and vocal pitches of that section from the seed motif, keeping lyrics where the note count is unchanged. `422` when the song has no motif |
| `setMaster` (M2) | any of `volume` 0–1, `space`: `dry` \| `room` \| `hall` | Whole-song volume and reverb |
| `setVocalTake` (v2) | `assetId` | Uses the user's own recording as the vocal track: `source = "recording"`, `renderAssetId = assetId` |

Mapping of the feel knobs. The app sends absolute values; the panel's encoder deltas are turned into values by the app (one detent = 0.02).

| Control | 0 – 0.33 | 0.33 – 0.67 | 0.67 – 1 |
| --- | --- | --- | --- |
| complexity | lane `basic` | lane `explore` | lane `colour` |
| density | rhythm level `start` | `next` | `challenge` |
| brightness | darker: prefer minor colour, relative minor at ≤ 0.1 | neutral | brighter: prefer major colour, relative major at ≥ 0.9 |

If the song's meter has no preset at the requested rhythm level (in `rhythm-presets.json` 2/4 and 3/4 have only `start`, 6/8 only `next`), the server uses the nearest level that exists.

### `POST /api/songs/{id}/another`

"Another take" (Play it again / Another take). Regenerates the unlocked content of one section, keeping each region's `play`, `complexity`, `intensity` and `style`.

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

### `POST /api/songs/{id}/lyrics` (M2)

Rewrite lyrics with a model, one syllable per vocal note, so the result always fits the melody.

Request: `{ "baseRevision", "sections"?: [id], "keep"?: { "<sectionId>": [lineIndex] }, "themes": ["sea", "homesick"], "tone": "plain" | "subtle" | "playful", "rhyme": true }`. Without `sections`, every section with vocal notes is rewritten. Lines listed in `keep` stay as they are ("Keep"). Response: `{ "song": Song }`. Typing lyrics with `setLyrics` always works.

The server sends the model the captured text, what the photos suggested, the mood, the place (only when `showCity`), the time of day and the title, plus the song's structure: each section with its role (verse sets the scene, chorus is the heart, outro comes back softly) and each line's exact number of characters. The model answers each line as an array of single characters. Lines with the wrong length are asked for again with the exact counts, up to three model calls in all, each limited to 20 s and all of them to 45 s together.

Failures answer `503 offline_unavailable` with `error.detail.reason`:

| `reason` | Meaning |
| --- | --- |
| `not_configured` | No `FRETCASE_TEXT_MODEL_KEY` on the server |
| `auth` | The model service refused the key |
| `rate_limited` | The model service is busy; try later |
| `unreachable` | No network, or the service answered with an error |
| `timeout` | The model did not answer in time |
| `bad_answer` | After three tries some lines still had the wrong length |

### `POST /api/songs/{id}/lyrics/alternatives` (M2)

Up to three other wordings of one lyric line, each with exactly that line's number of notes ("Other wordings"). Same limits and failure reasons as above; fewer than three come back when only some had the right length.

Request: `{ "section", "line": lineIndex, "themes"?, "tone"?, "rhyme"? }`. Response: `{ "alternatives": [ { "text": "I tell the sea I miss my home", "note": "more direct" } ] }`. The song does not change; the app applies a choice with `setLyrics`. Offline: `503`.

### `GET /api/songs/{id}/lyrics/themes` (M2)

Suggested themes for the lyrics page, with where each came from: `{ "themes": [ { "text": "sea", "source": "photo" | "text" | "sound" | "hum" } ] }`. Offline: keywords from the text input and the photos' colour labels.

### Vocal playback before synthesis

While `tracks.vocal.source` is `none`, the app plays the vocal notes as a plain guide tone, so the line can be heard and edited. When `renderAssetId` is set, the app plays that audio instead of the notes.

### `POST /api/songs/{id}/vocal` (v2)

Synthesise the vocal track from notes and lyrics. Request: `{ "baseRevision" }`. Response: `202` job; its result is `{ "song": Song }` with `tracks.vocal.source = "synth"` and `renderAssetId` set. Offline: `503`. A user's own take is uploaded as an asset with role `vocal_take` and attached with the `setVocalTake` edit.

### `GET /api/songs/{id}/export?format=midi|musicxml|abc`

The song as a file. MIDI carries all six tracks; MusicXML and ABC carry melody, lyrics and chord symbols with guitar diagrams.

## Cards

### `POST /api/songs/{id}/card/preview`

Render the print image for the current card fields. Request: `{ "baseRevision" }`. Response: `{ "song": Song }` with `card.frontAssetId` set and a reserved `card.share` (`state: "reserved"`) so the QR code is final before printing.

The print image is 1260 × 840 px, the Instax Wide image area: the cover photo (stylised by `style`) fills the top, and a paper-coloured strip at the bottom holds the title, `line`, the city and date (city only when `showCity`), and the QR code with a small note mark in its centre. Nothing is printed over the photo. With style `text` the top shows `line` (or the title) large on paper. Stylisation by model is v2; offline, `ink`, `comic` and `xieyi` use local filters.

### `POST /api/songs/{id}/card/print`

Print the previewed card. Request: `{ "baseRevision" }`. Refused with `422 cannot_apply` unless a preview exists for the current card fields, so nothing is printed without a preview. Response: `{ "song": Song }` with `card.printedAt` set. Printer errors (no film, not connected) answer `422` with `error.detail.printer`.

### `GET /api/printer` (M2)

`{ "printer": { "kind": "instax" | "thermal" | "dry_run", "connected": true, "paper": "ok" | "out" | "unknown", "remaining": 7 } }`. `remaining` is the number of film sheets left when the printer reports it, else `null`. The card screen shows it.

### `POST /api/songs/{id}/share` (v2)

Upload the song page (audio, real photo if `showPhoto`, city if `showCity`, message, lyrics). Response: `202` job. Offline: the share moves to `queued` and uploads when the network returns; the response is then `200 { "song": Song }`.

### `GET /api/share/{shareId}`

Resolve a scanned card. Response: `{ "songId": "…" }` when the song is on this device. For a song made on another FretCase (v2), the server fetches it from the song page; offline it answers `503`.

QR codes encode the song page URL, `{FRETCASE_SHARE_BASE}/s/{shareId}`. `FRETCASE_SHARE_BASE` defaults to the server's own origin (`https://<pi>:8443`) until upload (v2) gives songs a public host. The app recognises the `/s/{shareId}` pattern when scanning and calls this endpoint.

### `GET /s/{shareId}` (M2)

The song page, for whoever scans the card. An HTML page built from the app's second entry point (`app/song.html`); the server serves the same file for every `/s/*` path. It reads `shareId` from its URL and loads the endpoint below. It must work on a phone browser with no login.

### `GET /api/share/{shareId}/page` (M2)

What the song page shows, with nothing private:

```json
{
  "page": {
    "title": "Seaside at Dusk",
    "subtitle": "Dusk Folk",
    "line": "The sea wind blows the evening into song",
    "city": "Edinburgh",
    "date": "2026-11-19",
    "message": "I wrote you a song by the sea. I will sing it to you when I am back.",
    "photos": ["/api/share/k3Hq9xV2mPzT/assets/a-photo-01"],
    "card": "/api/share/k3Hq9xV2mPzT/assets/a-card-print-01",
    "lyrics": [ { "section": "Verse", "lines": ["The sea wind blows across the shore", "And one by one the lights come on"] } ]
  },
  "song": Song
}
```

`city` only when `showCity`; `photos` only when `showPhoto` (in `photoAssetIds` order, else an empty list). New songs start with `showCity` and `showPhoto` true (the city level is the agreed default); the user can turn either off on the card screen; `card` only after a print or preview. `song` is the full song for playback with `seed` and `provenance` removed and `assets` limited to those the page uses (photos, ambience clips, vocal render). `GET /api/share/{shareId}/assets/{assetId}` serves only those assets. `404` for an unknown share.

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
- The **app** turns them into meaning and calls the HTTP API: long press (≥ 600 ms) on `capture` records, short press takes a photo; where nothing is captured `capture` confirms: a short press on the pick screen chooses the song in focus, and on the card screen holding it for 1 s prints (a print uses film and cannot be undone, so a short press there only says to hold); long press on a track key mutes, short press selects; platter detents move the play position (default 4 detents per bar) while the song is stopped; while it plays, the platter plays the song like a record (speed, direction and pitch follow the platter, 13.3 detents a second being normal speed, as 24 detents a turn at 33⅓ rpm) and the song spins back up to normal speed 350 ms after the last detent and the section under it becomes the target of `another`; a fader movement becomes `setTrackVolume` (debounced to one call per 150 ms per fader); a feel knob becomes `setControl` (debounced to one call 400 ms after the last detent).
- The app sends `ring.set` and `key.light` back. Suggested ring: one pixel per bar group, the current position in the accent colour, locked sections dimmed. The ring shows colours only; blinking and pulsing are available on key lights, not on the ring.
- `seq` restarts at 0 on each new connection. Any frame received counts as proof that the link is alive.
- Events that happen while the link is down are dropped; held keys and fader positions arrive in the next `snapshot`.
