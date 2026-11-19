"""Test stub that follows the ``fretcase_card`` interface, version 2 (docs/milestone-2.md; the real module is built elsewhere).

Deterministic RGB PNGs drawn with Pillow (1260 x 840 print image, 630 x 420 preview); the printer records what it was
given. ``render_card`` raises ValueError for bad input and OSError for an unreadable cover, like the real module."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from PIL import Image, ImageDraw

Style = Literal["ink", "comic", "xieyi", "original", "text"]


@dataclass
class CardInput:
    title: str
    style: Style
    share_url: str
    date_text: str
    line: Optional[str] = None
    city: Optional[str] = None
    cover_path: Optional[Path] = None


@dataclass
class CardImages:
    print_png: bytes
    preview_png: bytes


class PrinterError(Exception):
    pass


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def render_card(card: CardInput) -> CardImages:
    if card.style not in ("ink", "comic", "xieyi", "original", "text"):
        raise ValueError(f"unknown style {card.style!r}")
    if card.style != "text" and card.cover_path is None:
        raise ValueError("a cover is required unless the style is text")
    img = Image.new("RGB", (1260, 840), (247, 241, 228))
    draw = ImageDraw.Draw(img)
    if card.cover_path is not None:
        try:
            with Image.open(card.cover_path) as cover:
                img.paste(cover.convert("RGB").resize((1260, 610)), (0, 0))
        except Exception as exc:  # noqa: BLE001
            raise OSError(f"cannot read the cover: {exc}") from exc
    draw.text((20, 620), f"{card.style}:{card.title}", fill=(0, 0, 0))
    draw.text((20, 660), card.line or "", fill=(0, 0, 0))
    draw.text((20, 700), f"{card.city + ' ' if card.city is not None else ''}{card.date_text}", fill=(0, 0, 0))
    draw.text((20, 740), card.share_url, fill=(0, 0, 0))
    return CardImages(_png(img), _png(img.resize((630, 420))))


class Printer:
    instances: list = []
    fail_with: Optional[str] = None

    def __init__(self, spec: Optional[str] = None, dry_run_dir: Optional[Path] = None):
        self.spec, self.dry_run_dir = spec or "dry_run", dry_run_dir
        self.printed: list = []
        Printer.instances.append(self)

    def status(self) -> dict:
        kind = self.spec.split(":")[0]
        return {"kind": kind, "connected": True, "paper": "ok", "remaining": 7 if kind == "instax" else None}

    def print_card(self, print_png: bytes) -> None:
        if Printer.fail_with:
            raise PrinterError(Printer.fail_with)
        self.printed.append(print_png)
        if self.dry_run_dir:
            Path(self.dry_run_dir).mkdir(parents=True, exist_ok=True)
            (Path(self.dry_run_dir) / f"print-{len(list(Path(self.dry_run_dir).iterdir())) + 1}.png").write_bytes(print_png)
