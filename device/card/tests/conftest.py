from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter


@pytest.fixture(scope="session")
def photo(tmp_path_factory) -> Path:
    """A synthetic seaside photo: sky gradient, sun, mountains, water, some noise."""
    w, h = 1600, 1200
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        c = (int(250 - 90 * t), int(170 + 40 * t), int(110 + 120 * t)) if y < h * 0.62 else (
            int(30 + 20 * t), int(70 + 40 * t), int(110 + 40 * t))
        d.line([(0, y), (w, y)], fill=c)
    d.ellipse([1000, 330, 1200, 530], fill=(255, 240, 200))
    d.polygon([(0, 744), (300, 500), (520, 650), (800, 430), (1100, 700), (1300, 600), (1600, 760), (1600, 744)],
              fill=(40, 50, 70))
    for i in range(14):
        y = 760 + i * 28
        d.line([(100 + i * 20, y), (1500 - i * 30, y + 4)], fill=(220, 230, 240), width=3)
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 8, (h, w, 3))
    arr = np.clip(np.asarray(im, dtype=np.float32) + noise, 0, 255).astype(np.uint8)
    im = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(1.2))
    p = tmp_path_factory.mktemp("photo") / "sea.jpg"
    im.save(p, quality=90)
    return p
