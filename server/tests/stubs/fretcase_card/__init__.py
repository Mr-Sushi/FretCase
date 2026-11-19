"""Test stub that follows the ``fretcase_card`` interface of docs/milestone-1.md (the real module is built elsewhere).

Deterministic 384 px wide 1-bit PNGs drawn with Pillow; the printer records what it was given."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

WIDTH = 384


@dataclass
class CardInput:
    title: str
    style: str
    share_url: str
    date_text: str
    line: Optional[str] = None
    city: Optional[str] = None
    photo_path: Optional[Path] = None


@dataclass
class CardImages:
    front_png: bytes
    back_png: bytes
    strip_png: bytes


class PrinterError(Exception):
    pass


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("1").save(out, format="PNG")
    return out.getvalue()


def render_card(card: CardInput) -> CardImages:
    front = Image.new("L", (WIDTH, 300), 255)
    draw = ImageDraw.Draw(front)
    draw.text((10, 10), f"{card.style}:{card.title}", fill=0)
    if card.photo_path:
        draw.text((10, 40), "photo", fill=0)
    elif card.line:
        draw.text((10, 40), card.line, fill=0)
    back = Image.new("L", (WIDTH, 300), 255)
    draw = ImageDraw.Draw(back)
    draw.text((10, 10), card.share_url, fill=0)
    draw.text((10, 30), card.date_text, fill=0)
    if card.city is not None:
        draw.text((10, 50), card.city, fill=0)
    strip = Image.new("L", (WIDTH, 620), 255)
    strip.paste(front, (0, 0))
    strip.paste(back, (0, 320))
    return CardImages(_png(front), _png(back), _png(strip))


class Printer:
    instances: list = []
    fail_with: Optional[str] = None

    def __init__(self, device: Optional[str] = None, dry_run_dir: Optional[Path] = None):
        self.device, self.dry_run_dir = device, dry_run_dir
        self.printed: list = []
        Printer.instances.append(self)

    def status(self) -> dict:
        return {"connected": True, "paper": "ok"}

    def print_strip(self, strip_png: bytes) -> None:
        if Printer.fail_with:
            raise PrinterError(Printer.fail_with)
        self.printed.append(strip_png)
        if self.dry_run_dir:
            Path(self.dry_run_dir).mkdir(parents=True, exist_ok=True)
            (Path(self.dry_run_dir) / f"print-{len(list(Path(self.dry_run_dir).iterdir())) + 1}.png").write_bytes(strip_png)
