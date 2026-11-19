# app

Web app for the iPad (React, TypeScript, Vite): the milestone 2 screens from `docs/ui/` (采集, 选一首, 打磨, 音轨, 歌词, 做卡); six-track playback with Tone.js; panel client; QR scanning. A second entry, `song.html`, is the phone song page opened by a card's QR code (served by the server at `/s/{shareId}`). Owner: agent B.

Target: iPad Safari, landscape 1180 x 820 CSS px, touch first. UI text is Simplified Chinese.

## Commands

```
npm install
npm run gen          # TypeScript types from shared/schema, plus the example data for mock mode (src/generated/)
npm test             # Vitest
npm run build        # gen + typecheck + vite build  ->  dist/index.html and dist/song.html
npm run dev          # dev server on :5173, proxies /api /health /ws to $FRETCASE_SERVER (default https://localhost:8443)
npm run dev:mock     # dev server in mock mode, no server needed
npm run build:mock   # production build in mock mode
```

`src/generated/` is committed so that the app builds without `shared/` being present; `npm run gen` refreshes it.

## Mock mode

Build or run with `VITE_MOCK=1`, or open any build with `?mock=1`. The app then uses `src/api/mock.ts` instead of the server: three
candidates built from `shared/schema/examples/song.json`, edits applied in memory (revisions, locks, undo, regions, lyric counts,
card preview before print), and no panel. Musical regeneration is faked. Lyrics rewriting answers 503 like the offline server
unless `?lyrics=online` is set. `?view=<screen>` (capture, pick, shape, detail, lyrics, card) opens the demo song on that screen;
the demo song page is `song.html?mock=1` with share id `k3Hq9xV2mPzT`. To try the panel in mock mode open
`?mock=1&panel=ws://host:8443/ws/panel`.

## Layout

```
src/api/        Api interface, HTTP client (8 s timeouts), mock
src/app/        store, controller (edit queue, capture, cards, scan, panel intents), context
src/audio/      schedule.ts (pure), engine.ts (Tone.js, synth voices, one gain per track)
src/panel/      interpreter.ts (panel messages to intents), client.ts (WebSocket), lights.ts (ring and key lights)
src/views/      CaptureView, PickView, ShapeView, DetailView (音轨), LyricsView, CardView, ScanOverlay
src/song/       the song page entry (song.html)
```
