# Screen designs (milestone 2)

These are the approved designs from the design canvas "FretCase iPad 界面流程". Each `.dc.html` file is one screen written as markup with inline styles plus a small script that holds the demo state. They are a reference for layout, wording and behaviour, not code to copy: images point to the canvas's own storage and will not load here, and the files need the canvas runtime to render.

| File | Screen | Size |
| --- | --- | --- |
| `Main.dc.html` | ① 采集: photo (up to 9), hum, sound, text | iPad landscape 1194 × 834 |
| `Pick.dc.html` | ② 选一首: three candidates | same |
| `Shape.dc.html` | ③ 打磨: sections, players, feel knobs | same |
| `Detail.dc.html` | ③+ 音轨: whole song, six tracks, one region at a time | same |
| `Lyrics.dc.html` | ③+ 歌词: all lines, counts, rhymes, rewrites | same |
| `Card.dc.html` | ④ 做卡: cover photo, style, text, print | same |
| `SongPage.dc.html` | ⑤ song page opened by the QR code | phone, fluid, max 480 px wide |

`card-print-example.jpg` is the print layout (1260 × 840): photo on top, paper strip below with title, line, city · date and the QR code with a note mark in its centre. `card3.py` and `mock.py` are the throwaway scripts that drew it (OpenCV filters for the styles); the card module may reuse their ideas.

Visual language: espresso background `#1C1410`, surfaces `#241A14` / `#2A1F18`, lines `#3A2C22` / `#4A3A2D`, text `#F3E9DA`, muted `#BFAE98`, brass accent `#D4AE6A`, record red `#D64533`. Track colours: vocal `#E2725B`, melody `#E3A44A`, guitar `#4FB3A6`, bass `#6C93D6`, drums `#A98BD8`, ambience `#86B068`. Noto Serif SC for headings, Noto Sans SC for text. Touch targets at least 44 px. No music jargon on screen (no key names, chord symbols, meters or "BPM" outside the tempo value).
