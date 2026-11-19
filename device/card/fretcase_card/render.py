"""``render_card``: the one entry point the server uses to make a card's images."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, get_args

from PIL import Image

from . import layout, styles

Style = Literal["ink", "comic", "xieyi", "original", "text"]
STYLE_NAMES = get_args(Style)

# The strip is folded over the bottom edge of the card, so the back half is printed turned by
# 180 degrees: after folding it reads upright when the card is turned over like a page.
# Set to 0 if the strip is folded over the top edge instead.
STRIP_BACK_ROTATION = 180


@dataclass
class CardInput:
    title: str
    style: Style
    share_url: str  # encoded in the QR code
    date_text: str  # e.g. "2026.11.18"
    line: Optional[str] = None  # printed on the front when there is no photo
    city: Optional[str] = None  # printed on the back only when not None
    photo_path: Optional[Path] = None


@dataclass
class CardImages:
    front_png: bytes  # 384 px wide, 1-bit, for a 58 mm printer at 203 dpi
    back_png: bytes  # same width
    strip_png: bytes  # front, fold mark, back: what is printed


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def _validate(card: CardInput) -> None:
    if card.style not in STYLE_NAMES:
        raise ValueError(f"unknown style {card.style!r}; expected one of {STYLE_NAMES}")
    if not card.title or not card.title.strip():
        raise ValueError("title must not be empty")
    if not card.share_url:
        raise ValueError("share_url must not be empty")


def _front(card: CardInput) -> Image.Image:
    """The front face as an 'L' image: a stylised photo, or the line or title when there is none."""
    if card.photo_path is None or card.style == "text":
        return layout.text_front(card.title, card.line)
    box = layout.photo_box()
    size = (box[2] - box[0], box[3] - box[1])
    gray = styles.load_gray(card.photo_path, size)
    picture = styles.stylise(card.style, gray)
    img = layout.new_canvas()
    img.paste(picture, (box[0], box[1]))
    layout.draw_frame(img)
    return img


def render_card(card: CardInput) -> CardImages:
    """Render front, back and the printable strip.

    Deterministic: the same input (and the same photo file and font) gives the same bytes, so
    a preview and the print match. A style other than ``text`` with no photo falls back to the
    text front. Raises ``ValueError`` for bad input and ``OSError`` if the photo cannot be read.
    """
    _validate(card)
    front = _front(card)
    back = layout.back_face(card.title, card.share_url, card.date_text, card.city)
    strip = layout.make_strip(front, back, STRIP_BACK_ROTATION)
    return CardImages(
        front_png=_png(layout.to_bilevel(front)),
        back_png=_png(layout.to_bilevel(back)),
        strip_png=_png(layout.to_bilevel(strip)),
    )
