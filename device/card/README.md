# device/card

Python package `fretcase_card`, version 2: renders the Instax Wide card and prints it. Interface in `../../docs/milestone-2.md` ("Card module, version 2"): `CardInput`, `CardImages`, `render_card`, `Printer`, `PrinterError`, all importable from `fretcase_card`. Owner: agent C.

## Layout (1260 x 840)

Picture 1260 x 610 on top, paper strip (`#F7F1E4`) 230 px below: title (serif, 64 px, shrinks to 34), line (sans, 28 px, shrinks to 18), `city · date` (24 px), and a 178 px QR code (error correction H, modules 4 or 5 px, note mark in the centre). Nothing is drawn over the picture. Long text shrinks, then ends with an ellipsis; it never reaches the QR code.

Styles (OpenCV and NumPy only, deterministic): `original` (warm film look), `xieyi` (watercolour, pale borders), `ink` (grey-black wash on paper, brush edges), `comic` (flat colour areas from seeded k-means, halftone dots in the shadows, black outlines), `text` (paper with the line, or the title, set large and balanced; the strip then does not repeat the line).

## Fonts

No font is stored in the repository: Noto Serif/Sans CJK (`fonts-noto-cjk`), then WenQuanYi. `FRETCASE_CARD_FONT` (a font file) overrides both faces. With no CJK font `render_card` raises `OSError` naming the package to install.

## Printers (`FRETCASE_PRINTER`, default `dry_run`)

- `dry_run`: `print-0001.png`, ... in `FRETCASE_DRY_RUN_DIR` (default `./fretcase-prints`) or the `dry_run_dir` argument.
- `instax` / `instax:<BLE address>`: Instax Wide Link over Bluetooth LE with `bleak` (`instax.py`). **Untested on a device.** Framing, JPEG encoding (1260 x 840, at most 105 KB) and the print sequence are tested against a fake BLE client only. The data chunk size (900) is an assumption; override with `FRETCASE_INSTAX_CHUNK`. The protocol follows the notes of javl/InstaxBLE (MIT); the code is a reimplementation, nothing was copied.
- `thermal:usb:<vid>:<pid>` (hex): ESC/POS; the card is turned 90 degrees, scaled to 384 px wide and dithered.

`status()` never raises. `print_card` raises `PrinterError`.

## Tests

```
cd device && uv run pytest card
```
