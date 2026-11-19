"""Card layout, 1260 x 840: picture (1260 x 610) on top, paper strip (230 px) below.

The strip holds the title, the line, "city · date" and a QR code with a note mark in its centre.
Nothing is drawn over the picture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H

from . import fonts

W, H, STRIP = 1260, 840, 230
PICTURE_H = H - STRIP  # 610
PAPER = (247, 241, 228)  # #F7F1E4
INK = (58, 40, 28)
MUTED = (128, 104, 84)

MARGIN = 48
QR_PX = 178
QR_X = W - MARGIN - QR_PX
QR_Y = PICTURE_H + 26
TEXT_W = QR_X - 40 - MARGIN  # width available to the strip's text

_NO_LINE_START = "，。！？、；：）」』”’,.!?;:)…"  # never start a line with these
_WORD = re.compile(r"[A-Za-z0-9_\-'.,;:!?/@#%&()\[\]+=*<>\"]+|\s+|.", re.DOTALL)


# ---- text fitting ----------------------------------------------------------------------------


def wrap_text(text: str, font, max_width: int) -> list[str]:
    """Greedy wrap: Chinese breaks between any two characters, Latin between words."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for tok in _WORD.findall(para):
            if tok.isspace() and not cur:
                continue
            trial = cur + tok
            if font.getlength(trial.rstrip()) <= max_width:
                cur = trial
                continue
            if cur.strip():
                lines.append(cur.rstrip())
                cur = "" if tok.isspace() else tok
                if font.getlength(cur) <= max_width:
                    continue
            piece = ""  # one token wider than the line: split by character
            for ch in cur or tok:
                if font.getlength(piece + ch) <= max_width or not piece or ch in _NO_LINE_START:
                    piece += ch
                else:
                    lines.append(piece)
                    piece = ch
            cur = piece
        lines.append(cur.rstrip())
    return [ln for ln in lines if ln != ""] or [""]


def balance(text: str, font, max_width: int) -> list[str]:
    """Wrap to the same number of lines as ``wrap_text`` but with the lines about equally long
    (no single character left alone on the last line)."""
    lines = wrap_text(text, font, max_width)
    n = len(lines)
    if n < 2:
        return lines
    lo, hi = 1, max_width
    while lo < hi:
        mid = (lo + hi) // 2
        if len(wrap_text(text, font, mid)) <= n:
            hi = mid
        else:
            lo = mid + 1
    return wrap_text(text, font, hi)


def _ellipsize(text: str, font, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    while len(text) > 1 and font.getlength(text + "…") > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


@dataclass
class Fitted:
    lines: list[str]
    size: int
    line_height: int


def fit_text(text, kind, max_width, max_height, max_size, min_size, max_lines, leading=1.3,
             balanced=False) -> Fitted:
    """Largest size (stepping down by 2) at which the text fits the box. At the minimum size the
    text is cut to what fits and ends with an ellipsis, so it never overflows."""
    size = max_size
    while True:
        font = fonts.get_font(kind, size)
        lines = (balance if balanced else wrap_text)(text, font, max_width)
        lh = int(size * leading)
        fits = len(lines) <= max_lines and lh * len(lines) <= max_height
        if fits or size <= min_size:
            if not fits:
                keep = max(1, min(max_lines, max_height // lh))
                truncated = len(lines) > keep
                lines = lines[:keep]
                if truncated:
                    lines[-1] = _ellipsize(lines[-1] + "…", font, max_width)
            return Fitted(lines, size, lh)
        size -= 2


# ---- QR code ---------------------------------------------------------------------------------


def note_icon(size: int, color) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size / 100
    d.ellipse([18 * s, 62 * s, 48 * s, 86 * s], fill=color)
    d.rectangle([42 * s, 14 * s, 49 * s, 74 * s], fill=color)
    d.polygon([(49 * s, 14 * s), (80 * s, 28 * s), (80 * s, 42 * s), (49 * s, 30 * s)], fill=color)
    return im


def qr_image(url: str, px: int = QR_PX) -> Image.Image:
    """QR code (error correction H) in ``px`` x ``px``, modules at a whole number of pixels, with
    the paper-coloured square and a note mark in the centre (about 6 % of the area)."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, border=0, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    m = np.array(qr.get_matrix(), dtype=bool)
    n = m.shape[0]
    if px // n < 3:
        raise ValueError(f"share_url is too long for a {px} px QR code ({n} modules)")
    # Nearest-neighbour scaling to exactly px: modules are 4 or 5 px wide, all edges stay sharp.
    arr = np.empty((px, px, 3), np.uint8)
    idx = (np.arange(px) * n) // px
    mod = m[np.ix_(idx, idx)]
    arr[:] = PAPER
    arr[mod] = INK
    side = px
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    hole = int(side * 0.24)
    c = (px - hole) // 2
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([c, c, c + hole - 1, c + hole - 1], radius=hole // 5, fill=PAPER + (255,))
    icon = note_icon(int(hole * 0.86), INK + (255,))
    img.alpha_composite(icon, (c + (hole - icon.width) // 2, c + (hole - icon.height) // 2))
    return img.convert("RGB")


# ---- compose ---------------------------------------------------------------------------------


def text_picture(title: str, line: str | None) -> Image.Image:
    """Picture area for style ``text``: paper with the line (or the title) set large."""
    img = Image.new("RGB", (W, PICTURE_H), PAPER)
    d = ImageDraw.Draw(img)
    main = (line or "").strip() or title.strip()
    box_w, box_h = W - 2 * 130, PICTURE_H - 2 * 110
    f = fit_text(main, "serif", box_w, box_h, 120, 40, 5, leading=1.4, balanced=True)
    block = f.line_height * len(f.lines)
    y = (PICTURE_H - block) // 2
    font = fonts.get_font("serif", f.size)
    for ln in f.lines:
        d.text((W // 2, y + f.line_height // 2), ln, font=font, fill=INK, anchor="mm")
        y += f.line_height
    # two short rules above and below the text
    for yy in (62, PICTURE_H - 62):
        d.line([(W // 2 - 40, yy), (W // 2 + 40, yy)], fill=MUTED, width=3)
    return img


def compose(picture: Image.Image, title: str, line: str | None, city: str | None,
            date_text: str, share_url: str) -> Image.Image:
    out = Image.new("RGB", (W, H), PAPER)
    out.paste(picture, (0, 0))
    d = ImageDraw.Draw(out)

    t = fit_text(title.strip(), "serif", TEXT_W, 80, 64, 34, 1, leading=1.2)
    d.text((MARGIN, PICTURE_H + 34), t.lines[0], font=fonts.get_font("serif", t.size), fill=INK)

    if line and line.strip():
        ln = fit_text(" ".join(line.split()), "sans", TEXT_W, 40, 28, 18, 1, leading=1.2)
        d.text((MARGIN + 2, PICTURE_H + 120), ln.lines[0], font=fonts.get_font("sans", ln.size), fill=MUTED)

    place = f"{city.strip()} · {date_text}" if city is not None and city.strip() else date_text
    p = fit_text(place, "sans", TEXT_W, 36, 24, 16, 1, leading=1.2)
    d.text((MARGIN + 2, PICTURE_H + 168), p.lines[0], font=fonts.get_font("sans", p.size), fill=MUTED)

    out.paste(qr_image(share_url), (QR_X, QR_Y))
    return out
