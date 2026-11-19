"""Font lookup. Cards use a CJK serif for titles and a CJK sans for the rest.

No font is stored in the repository. ``FRETCASE_CARD_FONT`` (a font file) overrides both faces.
When no CJK font can be found, ``OSError`` is raised with a message that says what to install:
printing boxes instead of Chinese would waste a film.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_ENV = "FRETCASE_CARD_FONT"

_DIRS = [
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/noto-cjk",
    "/usr/share/fonts/google-noto-cjk",
]
_SERIF = [f"{d}/NotoSerifCJK-{w}.ttc" for w in ("Bold", "SemiBold", "Regular") for d in _DIRS]
_SANS = [f"{d}/NotoSansCJK-{w}.ttc" for w in ("Medium", "Regular", "Bold") for d in _DIRS]
_OTHER = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
_CANDIDATES = {"serif": _SERIF + _SANS + _OTHER, "sans": _SANS + _SERIF + _OTHER}


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


def font_path(kind: str = "sans") -> str:
    """Path of the font file for ``kind`` ("serif" or "sans"). Raises OSError if none exists."""
    env = os.environ.get(FONT_ENV)
    if env:
        if Path(env).is_file():
            return env
        raise OSError(f"{FONT_ENV}={env!r} is not a file; point it at a CJK font (.ttf, .otf or .ttc)")
    for p in _CANDIDATES[kind]:
        if Path(p).is_file():
            return p
    raise OSError(
        "no CJK font found for card text: install fonts-noto-cjk (Debian, Raspberry Pi OS) "
        f"or set {FONT_ENV} to a font file"
    )


@lru_cache(maxsize=128)
def get_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    return _open(font_path(kind), size)


def serif(size: int) -> ImageFont.FreeTypeFont:
    return get_font("serif", size)


def sans(size: int) -> ImageFont.FreeTypeFont:
    return get_font("sans", size)


def clear_cache() -> None:
    get_font.cache_clear()
