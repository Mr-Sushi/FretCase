"""Offline photo styles for the picture area: ink, comic, xieyi and original.

All filters take and return a BGR uint8 array of the same size, use only OpenCV and NumPy, and
are deterministic (any randomness is seeded), so a preview and a print match.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageOps

PAPER_BGR = (228, 241, 247)  # #F7F1E4


def load_cover(path, size: tuple[int, int]) -> np.ndarray:
    """Read a photo (EXIF rotation applied), fill ``size`` by scaling and centre-cropping. BGR."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def _vignette(shape, strength: float, power: float = 2.0) -> np.ndarray:
    h, w = shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    return strength * np.clip(r, 0, 1) ** power


def _grain(shape, amount: float, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    g = rng.normal(0, amount, shape[:2]).astype(np.float32)
    return cv2.GaussianBlur(g, (0, 0), 0.8)[..., None]


def original(b: np.ndarray) -> np.ndarray:
    """Warm, slightly faded film look."""
    f = b.astype(np.float32) / 255
    f = 0.05 + 0.92 * f
    f[..., 2] *= 1.05
    f[..., 0] *= 0.94
    f = f * (1 - _vignette(b.shape, 0.22)[..., None])
    return np.clip(f * 255 + _grain(b.shape, 2.5), 0, 255).astype(np.uint8)


def xieyi(b: np.ndarray) -> np.ndarray:
    """Watercolour (xieyi): flat washes, soft edges, light paper showing through, pale borders."""
    s = cv2.stylization(b, sigma_s=80, sigma_r=0.45)
    paper = np.empty_like(s)
    paper[:] = PAPER_BGR
    out = cv2.addWeighted(s, 0.82, paper, 0.18, 0).astype(np.float32)
    fade = np.clip(_vignette(b.shape, 0.55, 2.6), 0, 1)[..., None]
    out = out * (1 - fade) + np.array(PAPER_BGR, np.float32) * fade
    out += _grain(b.shape, 3.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def ink(b: np.ndarray) -> np.ndarray:
    """Ink wash: grey-black washes on warm paper, dark brush edges, fading at the border."""
    g8 = cv2.cvtColor(cv2.edgePreservingFilter(b, flags=1, sigma_s=60, sigma_r=0.4), cv2.COLOR_BGR2GRAY)
    g8 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 3)).apply(g8)  # even out dark or bright photos
    g = cv2.normalize(g8, None, 0, 255, cv2.NORM_MINMAX).astype(np.float32) / 255
    wash = np.clip(0.08 + 0.92 * g ** 1.9, 0, 1)
    wash = np.clip(wash + _vignette(b.shape, 0.7, 2.4), 0, 1)
    blur_a = cv2.GaussianBlur(g, (0, 0), 1.2)
    blur_b = cv2.GaussianBlur(g, (0, 0), 4.0)
    edge = np.clip((blur_b - blur_a - 0.015) * 9.0, 0, 1)
    edge *= 1 - np.clip(_vignette(b.shape, 1.0, 1.6) * 1.4, 0, 1)
    tone = np.clip(wash - 0.85 * edge, 0, 1)
    dark = np.array([42, 38, 34], np.float32)  # warm black
    paper = np.array(PAPER_BGR, np.float32)
    out = dark[None, None, :] + (paper - dark)[None, None, :] * tone[..., None]
    out += _grain(b.shape, 2.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def _halftone(shape, cell: float, coverage: np.ndarray) -> np.ndarray:
    """Dots on a 45 degree grid; ``coverage`` in 0..1 sets the dot size. True where inked."""
    h, w = shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    c = s = np.float32(np.sqrt(0.5))
    u = (x * c + y * s) / cell
    v = (-x * s + y * c) / cell
    d = np.sqrt((u - np.round(u)) ** 2 + (v - np.round(v)) ** 2)  # 0 at the dot centre, up to ~0.7
    radius = np.sqrt(np.clip(coverage, 0, 1) / np.pi) * 1.05
    return d < radius


def comic(b: np.ndarray) -> np.ndarray:
    """Comic: flat saturated colour areas, halftone dots in the shadows, bold black outlines."""
    h, w = b.shape[:2]
    smooth = b
    for _ in range(2):
        smooth = cv2.bilateralFilter(smooth, 9, 70, 9)
    smooth = cv2.pyrMeanShiftFiltering(smooth, 10, 26)

    # Flat colour: k-means in Lab (seeded), then a median to clear speckles.
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB)
    small = cv2.resize(lab, (w // 4, h // 4), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
    cv2.setRNGSeed(1234)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, _, centres = cv2.kmeans(small, 7, None, crit, 1, cv2.KMEANS_PP_CENTERS)
    flat_lab = lab.reshape(-1, 1, 3).astype(np.float32)
    d = ((flat_lab - centres[None, :, :]) ** 2).sum(axis=2)
    labels = d.argmin(axis=1).reshape(h, w).astype(np.uint8)
    labels = cv2.medianBlur(labels, 7)
    flat = centres[labels].astype(np.uint8)
    flat = cv2.cvtColor(flat, cv2.COLOR_LAB2BGR)
    hsv = cv2.cvtColor(flat, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.3, 0, 255)
    hsv[..., 2] = np.clip((hsv[..., 2] - 128) * 1.12 + 134, 0, 255)
    flat = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # Halftone dots in the shadows: darker areas get bigger dots of a deep tone.
    gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    shade = np.clip((0.5 - gray) / 0.4, 0, 1)
    dots = _halftone(b.shape, 9.0, shade * 0.9)
    deep = (flat.astype(np.float32) * 0.45).astype(np.uint8)
    out = np.where(dots[..., None], deep, flat)

    # Outlines: from the lightly smoothed photo, thickened, with tiny specks removed.
    g = cv2.cvtColor(cv2.bilateralFilter(b, 7, 50, 7), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (0, 0), 1.6)
    edges = cv2.Canny(g, 40, 110)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    n, lab_cc, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 90
    edges = (keep[lab_cc] * 255).astype(np.uint8)
    out[edges > 0] = (22, 18, 20)
    return out


STYLES = {"original": original, "xieyi": xieyi, "ink": ink, "comic": comic}


def stylise(style: str, picture: np.ndarray) -> np.ndarray:
    return STYLES[style](picture)
