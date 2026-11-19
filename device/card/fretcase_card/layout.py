"""Card faces: geometry, text layout and the QR code. Everything is drawn bilevel."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_M

from .fonts import get_font

# 58 mm thermal paper prints 384 dots across at 203 dpi (48 mm). A card is 54 x 86 mm: one
# face is 384 x 688 dots (48 x 86 mm), so the strip wraps the card's width with a 3 mm margin
# each side and covers its full length.
WIDTH = 384
FACE_HEIGHT = 688
FOLD_HEIGHT = 14
FRAME_INSET = 6
FRAME_LINE = 3
PHOTO_INSET = 14
QR_MAX = 300  # px, including the quiet zone

BLACK = 0
WHITE = 255

_WORD = re.compile(r"[A-Za-z0-9_\-'.,;:!?/@#%&()\[\]+=*<>\"]+|\s+|.", re.S)


def new_canvas() -> Image.Image:
    return Image.new("L", (WIDTH, FACE_HEIGHT), WHITE)


def draw_frame(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    for k in range(FRAME_LINE):
        o = FRAME_INSET + k
        d.rectangle([o, o, WIDTH - 1 - o, FACE_HEIGHT - 1 - o], outline=BLACK)


def photo_box() -> tuple[int, int, int, int]:
    """Where the stylised picture goes on the front: inside the frame, with some paper around."""
    m = PHOTO_INSET
    return (m, m, WIDTH - m, FACE_HEIGHT - m)


def to_bilevel(img: Image.Image) -> Image.Image:
    """Threshold an 'L' image to 1 bit. Photo regions are already 0/255, so only text edges change."""
    return img.point(lambda p: 255 if p >= 128 else 0).convert("1", dither=Image.Dither.NONE)


# ---- text ---------------------------------------------------------------------------------


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
            # a single token wider than the line (a long word): split by character
            piece = ""
            for ch in cur or tok:
                if font.getlength(piece + ch) <= max_width or not piece:
                    piece += ch
                else:
                    lines.append(piece)
                    piece = ch
            cur = piece
        lines.append(cur.rstrip())
    return [ln for ln in lines if ln != ""] or [""]


@dataclass
class FittedText:
    lines: list[str]
    size: int
    line_height: int


def fit_text(
    text: str, max_width: int, max_height: int, max_size: int, min_size: int, max_lines: int
) -> FittedText:
    """Largest font size at which the text fits. Falls back to the smallest, truncating."""
    size = max_size
    while True:
        font = get_font(size)
        lines = wrap_text(text, font, max_width)
        lh = int(size * 1.3)
        if (len(lines) <= max_lines and lh * len(lines) <= max_height) or size <= min_size:
            if len(lines) > max_lines or lh * len(lines) > max_height:
                keep = max(1, min(max_lines, max_height // lh))
                lines = lines[:keep]
                if len(lines[-1]) > 1:
                    lines[-1] = lines[-1][:-1] + "…"
            return FittedText(lines, size, lh)
        size -= 2


def draw_lines(img: Image.Image, fitted: FittedText, cx: int, top: int) -> int:
    """Draw centred lines starting at ``top``; returns the y below the last line."""
    d = ImageDraw.Draw(img)
    font = get_font(fitted.size)
    y = top
    for line in fitted.lines:
        d.text((cx, y), line, font=font, fill=BLACK, anchor="ma")
        y += fitted.line_height
    return y


def text_height(fitted: FittedText) -> int:
    return fitted.line_height * len(fitted.lines)


# ---- decoration for faces without a picture ------------------------------------------------


def waveform(img: Image.Image, seed: str, top: int, height: int, left: int = 40, right: int = WIDTH - 40) -> None:
    """A row of vertical bars whose heights come from a hash of ``seed``: a small picture of 'a song'."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    n = 24
    step = (right - left) / n
    d = ImageDraw.Draw(img)
    mid = top + height // 2
    for i in range(n):
        v = digest[i % len(digest)] / 255
        envelope = 0.35 + 0.65 * np.sin(np.pi * (i + 0.5) / n)
        h = max(6, int(height * (0.15 + 0.85 * v) * envelope))
        x0 = int(left + i * step)
        d.rectangle([x0, mid - h // 2, x0 + max(3, int(step) - 4), mid + h // 2], fill=BLACK)


# ---- front without a picture ---------------------------------------------------------------


def text_front(title: str, line: Optional[str]) -> Image.Image:
    img = new_canvas()
    draw_frame(img)
    main = (line or "").strip() or title.strip()
    inner = WIDTH - 2 * (FRAME_INSET + PHOTO_INSET + 10)
    fitted = fit_text(main, inner, 330, 54, 26, 8)
    wave_h = 80
    gap = 40
    block = wave_h + gap + text_height(fitted)
    top = (FACE_HEIGHT - block) // 2
    waveform(img, title + "\x00" + (line or ""), top, wave_h)
    draw_lines(img, fitted, WIDTH // 2, top + wave_h + gap)
    return img


# ---- back ---------------------------------------------------------------------------------


def qr_image(url: str, max_px: int = QR_MAX) -> Image.Image:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    m = np.array(qr.get_matrix(), dtype=bool)
    n = m.shape[0]
    quiet = 4
    box = max(2, max_px // (n + 2 * quiet))
    side = (n + 2 * quiet) * box
    arr = np.full((side, side), WHITE, dtype=np.uint8)
    big = np.kron(m, np.ones((box, box), dtype=bool))
    arr[quiet * box : quiet * box + n * box, quiet * box : quiet * box + n * box][big] = BLACK
    return Image.fromarray(arr, "L")


def back_face(title: str, share_url: str, date_text: str, city: Optional[str]) -> Image.Image:
    img = new_canvas()
    draw_frame(img)
    d = ImageDraw.Draw(img)
    inner = WIDTH - 2 * (FRAME_INSET + PHOTO_INSET + 10)

    fitted = fit_text(title.strip(), inner, 150, 44, 24, 3)
    y = 52
    y = draw_lines(img, fitted, WIDTH // 2, y)
    y += 12
    d.line([(WIDTH // 2 - 40, y), (WIDTH // 2 + 40, y)], fill=BLACK, width=3)

    qr = qr_image(share_url)
    qx = (WIDTH - qr.width) // 2
    qy = max(y + 20, 235)
    img.paste(qr, (qx, qy))
    y = qy + qr.height + 26

    small = get_font(26)
    if city is not None and city.strip():
        c = fit_text(city.strip(), inner, 40, 30, 20, 1)
        y = draw_lines(img, c, WIDTH // 2, y)
    d.text((WIDTH // 2, y + 4), date_text, font=small, fill=BLACK, anchor="ma")
    return img


# ---- strip --------------------------------------------------------------------------------


def make_strip(front: Image.Image, back: Image.Image, back_rotation: int) -> Image.Image:
    """Front, a dashed fold line, then the back. The back is turned so that it reads upright
    once the strip is folded over the bottom edge of the card (see ``STRIP_BACK_ROTATION``)."""
    strip = Image.new("L", (WIDTH, FACE_HEIGHT * 2 + FOLD_HEIGHT), WHITE)
    strip.paste(front, (0, 0))
    strip.paste(back.rotate(back_rotation) if back_rotation else back, (0, FACE_HEIGHT + FOLD_HEIGHT))
    d = ImageDraw.Draw(strip)
    y = FACE_HEIGHT + FOLD_HEIGHT // 2
    x = 0
    while x < WIDTH:
        d.line([(x, y), (min(x + 8, WIDTH - 1), y)], fill=BLACK, width=2)
        x += 14
    return strip
