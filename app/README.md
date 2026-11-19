# app

Web app for the iPad (React, TypeScript, Vite): seed card, whole song, single track and card preview views; six-track playback with Tone.js; panel client; QR scanning. Owner: agent B.

Target: iPad Safari, landscape 1180 x 820 CSS px, touch first. UI text is Simplified Chinese.

## Commands

```
npm install
npm run gen          # TypeScript types from shared/schema, plus the example data for mock mode (src/generated/)
npm test             # Vitest
npm run build        # gen + typecheck + vite build  ->  dist/
npm run dev          # dev server on :5173, proxies /api /health /ws to $FRETCASE_SERVER (default https://localhost:8443)
npm run dev:mock     # dev server in mock mode, no server needed
npm run build:mock   # production build in mock mode
```

`src/generated/` is committed so that the app builds without `shared/` being present; `npm run gen` refreshes it.

## Mock mode

Build or run with `VITE_MOCK=1`, or open any build with `?mock=1`. The app then uses `src/api/mock.ts` instead of the server:
it serves `shared/schema/examples/song.json` (listed under "本机的歌" on the capture view), generates a song from a seed card by
copying and transposing that song, applies edits in memory (revisions, locks, undo, lyric counts, card preview before print),
and runs without a panel. Musical regeneration (knobs, "another take") is faked: the knobs store values, density switches the
guitar rhythm preset, "another" shifts pitches inside the scale. To try the panel in mock mode open `?mock=1&panel=ws://host:8443/ws/panel`.

## Layout

```
src/api/        Api interface, HTTP client (8 s timeouts), mock
src/app/        store, controller (edit queue, capture, cards, scan, panel intents), context
src/audio/      schedule.ts (pure), engine.ts (Tone.js, synth voices, one gain per track)
src/panel/      interpreter.ts (panel messages to intents), client.ts (WebSocket), lights.ts (ring and key lights)
src/views/      capture + seed card, song, track edit, card, scan overlay
```
