"""``render_card``: the one entry point the server uses to make a card's images (version 2)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

import cv2
from PIL import Image

from . import layout, styles

Style = Literal["ink", "comic", "xieyi", "original", "text"]
STYLE_NAMES = get_args(Style)


@dataclass
class CardInput:
    title: str
    style: Style
    share_url: str  # encoded in the QR code
    date_text: str  # e.g. "2026.11.19"
    line: str | None = None  # under the title in the strip; large on the picture for "text"
    city: str | None = None  # printed before the date only when not None
    cover_path: Path | None = None  # required unless style == "text"


@dataclass
class CardImages:
    print_png: bytes  # 1260 x 840 RGB: the Instax Wide image area
    preview_png: bytes  # the same image at 630 x 420, for the screen


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def _validate(card: CardInput) -> None:
    if card.style not in STYLE_NAMES:
        raise ValueError(f"unknown style {card.style!r}; expected one of {STYLE_NAMES}")
    if not card.title or not card.title.strip():
        raise ValueError("title must not be empty")
    if not card.share_url:
        raise ValueError("share_url must not be empty")
    if not card.date_text or not card.date_text.strip():
        raise ValueError("date_text must not be empty")
    if card.style != "text" and card.cover_path is None:
        raise ValueError(f"style {card.style!r} needs a cover photo (cover_path)")


def _picture(card: CardInput) -> Image.Image:
    if card.style == "text":
        return layout.text_picture(card.title, card.line)
    try:
        photo = styles.load_cover(card.cover_path, (layout.W, layout.PICTURE_H))
    except OSError:
        raise
    except Exception as e:  # PIL raises other types for broken files
        raise OSError(f"cannot read cover photo {card.cover_path}: {e}") from e
    out = styles.stylise(card.style, photo)
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def render_card(card: CardInput) -> CardImages:
    """Render the 1260 x 840 print image and its 630 x 420 preview.

    Deterministic: the same input (same cover file, font and library versions) gives the same bytes.
    Raises ``ValueError`` for bad input and ``OSError`` for an unreadable cover or a missing CJK font.
    """
    _validate(card)
    line = card.line if card.style != "text" or not (card.line or "").strip() else None
    # With style "text" the line is already large on the picture, so the strip does not repeat it.
    img = layout.compose(_picture(card), card.title, line, card.city, card.date_text, card.share_url)
    assert img.size == (layout.W, layout.H)
    preview = img.resize((layout.W // 2, layout.H // 2), Image.Resampling.LANCZOS)
    return CardImages(print_png=_png(img), preview_png=_png(preview))
