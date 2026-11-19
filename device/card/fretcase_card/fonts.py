"""Font lookup. Cards use a Chinese font; there is none in the repository, so find one."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_ENV = "FRETCASE_CARD_FONT"

# (path, collection index preference). For .ttc files the Simplified Chinese face is chosen by name.
_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _open(path: str, size: int) -> ImageFont.FreeTypeFont:
    if path.lower().endswith(".ttc"):
        # Prefer the Simplified Chinese face of a collection.
        for index in range(12):
            try:
                font = ImageFont.truetype(path, size, index=index)
            except OSError:
                break
            if "SC" in " ".join(font.getname()) or "Zen Hei" in font.getname()[0]:
                return font
        return ImageFont.truetype(path, size, index=0)
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=1)
def font_path() -> str | None:
    env = os.environ.get(FONT_ENV)
    if env and Path(env).is_file():
        return env
    for p in _CANDIDATES:
        if Path(p).is_file():
            return p
    return None


@lru_cache(maxsize=64)
def get_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    path = font_path()
    if path is None:
        # Pillow's built-in font has no Chinese glyphs; text will show boxes. Install
        # fonts-noto-cjk on the Pi, or set FRETCASE_CARD_FONT.
        return ImageFont.load_default(size)
    return _open(path, size)
