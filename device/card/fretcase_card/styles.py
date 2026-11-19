"""Offline stylisation of a photo: ink, comic, xieyi and original. Output is bilevel (0 or 255).

Every filter is deterministic: the same photo and size always give the same pixels.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize to fill ``size`` and crop the centre."""
    return ImageOps.fit(img, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def load_gray(path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        return cover(im, size).convert("L")


def _arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img, dtype=np.float32)


def _img(a: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "L")


def _dither(img: Image.Image) -> Image.Image:
    """Floyd-Steinberg to 1 bit, back to 0/255 'L'."""
    return img.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")


def _vignette(shape: tuple[int, int], strength: float, power: float = 2.0) -> np.ndarray:
    """0 in the middle to ``strength`` at the corners (added to the tone to fade to paper)."""
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    return strength * np.clip(r, 0, 1) ** power


def _lines(gray: Image.Image, small: float, large: float, threshold: float) -> np.ndarray:
    """Difference of Gaussians: True where there is a dark edge."""
    a = _arr(gray.filter(ImageFilter.GaussianBlur(small)))
    b = _arr(gray.filter(ImageFilter.GaussianBlur(large)))
    return (b - a) > threshold


def original(gray: Image.Image) -> Image.Image:
    g = ImageOps.autocontrast(gray, cutoff=1)
    g = _img(255 * (_arr(g) / 255) ** 1.1)
    return _dither(g)


def ink(gray: Image.Image) -> Image.Image:
    """Ink wash (水墨): soft grey washes, dark brush edges, paper white at the borders."""
    g = ImageOps.autocontrast(gray, cutoff=2)
    wash = _arr(g.filter(ImageFilter.GaussianBlur(2.0)))
    wash = 255 * (wash / 255) ** 1.5                      # most of the picture lighter than the photo
    wash = wash + _vignette(wash.shape, 140)              # fade to paper at the edges
    tone = _dither(_img(wash))
    edges = _lines(g, 1.2, 4.0, 14.0)
    out = _arr(tone)
    out[edges] = 0
    return _img(out)


def comic(gray: Image.Image) -> Image.Image:
    """Comic (漫画): three tones as a 45 degree halftone screen, with heavy outlines."""
    g = ImageOps.autocontrast(gray, cutoff=1)
    soft = g.filter(ImageFilter.GaussianBlur(1.5))
    tone = _arr(soft) / 255.0
    tone = np.floor(tone * 3.0) / 2.0                      # posterise to 4 levels: 0, .5, 1 (and 1.5 clipped)
    tone = np.clip(tone, 0, 1)
    h, w = tone.shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    cell = 7.0
    c, s = np.cos(np.pi / 4), np.sin(np.pi / 4)
    u = (x * c + y * s) / cell
    v = (-x * s + y * c) / cell
    screen = (np.cos(2 * np.pi * u) + np.cos(2 * np.pi * v)) / 4.0 + 0.5   # 0..1, one dot per cell
    dark = 1.0 - tone
    out = np.where(dark > screen * 0.95 + 0.02, 0.0, 255.0)
    out[dark < 0.06] = 255.0
    # outlines from the unposterised picture, thickened
    edges = _lines(g, 1.0, 3.0, 18.0)
    line_img = Image.fromarray(np.where(edges, 0, 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(3))
    out_img = ImageChops.darker(_img(out), line_img)
    return out_img


def xieyi(gray: Image.Image) -> Image.Image:
    """Freehand ink (写意): big soft shapes, a few strong strokes, plenty of white paper."""
    g = ImageOps.autocontrast(gray, cutoff=3)
    small = g.resize((max(1, g.width // 6), max(1, g.height // 6)), Image.Resampling.BOX)
    soft = small.resize(g.size, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(5))
    a = _arr(soft) / 255.0
    a = np.clip((a - 0.25) / 0.6, 0, 1)                      # push light areas to white
    a = a ** 1.3
    wash = 255 * a + _vignette(a.shape, 255, power=1.6)       # strong fade: the edges are blank paper
    tone = _dither(_img(np.clip(wash, 0, 255)))
    strokes = _lines(g, 2.5, 8.0, 12.0)
    stroke_img = Image.fromarray(np.where(strokes, 0, 255).astype(np.uint8), "L").filter(ImageFilter.MedianFilter(5))
    fade = _vignette(a.shape, 1.0, power=1.4)
    stroke_arr = _arr(stroke_img)
    stroke_arr[fade > 0.55] = 255                              # no strokes near the border
    return _img(np.minimum(_arr(tone), stroke_arr))


STYLES = {"ink": ink, "comic": comic, "xieyi": xieyi, "original": original}


def stylise(style: str, gray: Image.Image) -> Image.Image:
    return STYLES[style](gray)
