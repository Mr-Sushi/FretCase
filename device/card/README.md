# device/card

Python package `fretcase_card`: card layout, offline stylisation (ink, comic, xieyi) and thermal printing. Called by `server/`. Interface in ../../docs/milestone-1.md (`CardInput`, `CardImages`, `render_card`, `Printer`, `PrinterError`, all importable from `fretcase_card`). Owner: agent C.

## Geometry

58 mm thermal paper is 384 dots wide at 203 dpi. A card is 54 x 86 mm, so one face is 384 x 688 dots. The strip is 384 x 1390: front (688), a 14-dot fold line, back (688). The back half is turned 180 degrees in the strip so it reads upright after the strip is folded over the card's bottom edge and the card is turned over like a page (`STRIP_BACK_ROTATION` in `render.py`; set it to 0 for a fold over the top edge). `back_png` is always upright.

## Faces

- **Front with a photo** (styles `ink`, `comic`, `xieyi`, `original`): centre-cropped photo, stylised, inside a frame.
  - `ink` (水墨): grey washes dithered, dark brush edges, fades to paper at the border.
  - `comic` (漫画): four tones as a 45 degree halftone screen, thick outlines.
  - `xieyi` (写意): big soft shapes, a few strong strokes, mostly white paper.
  - `original`: contrast-stretched, Floyd-Steinberg dither.
- **Front without a photo**, or style `text`: the `line` (or the title when there is no line), large, under a small waveform that is derived from the title so each card differs.
- **Back**: title, QR code of `share_url` (error correction M, 4-module quiet zone, as large as fits in 300 dots), the city only when it is not None and not empty, the date.

Everything is bilevel and deterministic: the same input gives the same bytes. Text is thresholded, photos are dithered.

## Fonts

No font is stored in the repository. `fonts.py` looks for Noto Serif/Sans CJK (`fonts-noto-cjk` on Debian and Raspberry Pi OS), then WenQuanYi, then DejaVu. Set `FRETCASE_CARD_FONT` to use another file. Without a Chinese font, Chinese text prints as boxes. Preview and print match only when both use the same font and Pillow version.

## Printer

`Printer(device=None, dry_run_dir=None)`. `device` is `usb:0x0416:0x5011` (vendor and product id), `serial:/dev/ttyUSB0[:baud]` or a device file such as `/dev/usb/lp0`; if None, `FRETCASE_PRINTER` is used. With `dry_run_dir` each `print_strip` writes `print-0001.png`, `print-0002.png`, ... (the strip bytes unchanged) and `status()` is `{"connected": true, "paper": "ok"}`. Errors raise `PrinterError`. `status()` never raises; paper is `"unknown"` when the printer cannot report it. Real hardware has not been tested; only the python-escpos output (raster command and feed) is checked with a dummy printer.

## Tests

```
cd device && uv run pytest card
```

Renders each style from a synthetic photo, a card with no photo, checks determinism, sizes, layout limits, the strip layout, decodes the QR code with OpenCV (dev dependency, skipped if missing), and the printer in dry-run and with a dummy backend.
