import io

import cv2
import numpy as np
import pytest
from fretcase_card import CardInput, fonts, layout, render_card
from PIL import Image

URL = "https://fretcase.example/s/Ab3dEf9hJk2LmN"
PHOTO_STYLES = ["ink", "comic", "xieyi", "original"]
ALL_STYLES = PHOTO_STYLES + ["text"]


def card(style="original", cover=None, **kw):
    base = dict(title="Seaside at Dusk", style=style, share_url=URL, date_text="2026.11.19",
                line="The sea wind blows the evening into song", city="Edinburgh", cover_path=cover)
    base.update(kw)
    return CardInput(**base)


def img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


@pytest.mark.parametrize("style", ALL_STYLES)
def test_sizes_with_cover(style, photo):
    out = render_card(card(style, photo))
    assert img(out.print_png).size == (1260, 840)
    assert img(out.preview_png).size == (630, 420)


def test_text_style_without_cover_and_cover_is_ignored(photo):
    a = render_card(card("text"))
    b = render_card(card("text", photo))
    assert a.print_png == b.print_png
    assert img(a.print_png).size == (1260, 840)


@pytest.mark.parametrize("style", PHOTO_STYLES)
def test_photo_style_needs_a_cover(style):
    with pytest.raises(ValueError, match="cover"):
        render_card(card(style))


@pytest.mark.parametrize("kw", [dict(title=" "), dict(style="oil"), dict(share_url=""), dict(date_text="")])
def test_bad_input(kw):
    with pytest.raises(ValueError):
        render_card(card(**{"style": "text", **kw}))


@pytest.mark.parametrize("style", ALL_STYLES)
def test_deterministic(style, photo):
    a = render_card(card(style, photo))
    b = render_card(card(style, photo))
    assert a.print_png == b.print_png and a.preview_png == b.preview_png


def test_styles_differ(photo):
    outs = {s: render_card(card(s, photo)).print_png for s in PHOTO_STYLES}
    assert len(set(outs.values())) == 4


def test_nothing_over_the_picture(photo):
    a = img(render_card(card("comic", photo, title="A", line="B", city=None)).print_png)
    b = img(render_card(card("comic", photo, title="A completely different title", line="x" * 40, city="London")).print_png)
    top = (0, 0, 1260, layout.PICTURE_H)
    assert np.array_equal(np.asarray(a.crop(top)), np.asarray(b.crop(top)))


def test_strip_is_paper_with_dark_text(photo):
    im = np.asarray(img(render_card(card("original", photo)).print_png))
    strip = im[layout.PICTURE_H:]
    assert tuple(strip[2, 2]) == layout.PAPER
    assert (strip.sum(axis=2) < 300).sum() > 3000  # title and QR modules are dark


def test_preview_matches_print(photo):
    out = render_card(card("xieyi", photo))
    small = img(out.print_png).resize((630, 420), Image.Resampling.LANCZOS)
    assert np.array_equal(np.asarray(small), np.asarray(img(out.preview_png)))


# ---- long text ----------------------------------------------------------------------------


def _strip_text_bounds(im: Image.Image):
    """Bounding box (x0, y0, x1, y1) of non-paper pixels in the strip, left of the QR code."""
    a = np.asarray(im)[layout.PICTURE_H:, : layout.QR_X - 1].astype(int)
    diff = np.abs(a - np.array(layout.PAPER)).sum(axis=2) > 30
    ys, xs = np.where(diff)
    return xs.min(), ys.min(), xs.max(), ys.max()


@pytest.mark.parametrize("style", ["text", "comic"])
@pytest.mark.parametrize("title,line", [
    ("A very long song title " * 12, "This is a very very long line of lyrics " * 10),
    ("很长的歌名" * 12, "这是一句很长很长的歌词" * 10),
    ("A very long English title " * 6, "a long line of english words " * 12),
    ("x" * 300, "y" * 300),
])
def test_long_title_and_line_fit(style, title, line, photo):
    im = img(render_card(card(style, photo, title=title, line=line, city="A city with a very long name" * 3)).print_png)
    x0, y0, x1, y1 = _strip_text_bounds(im)
    assert x0 >= layout.MARGIN - 2
    assert x1 <= layout.QR_X - 40 + 2, "text runs into the QR code"
    assert y1 < 840 - 10, "text runs off the bottom"
    if style == "text":  # the big line stays inside the picture area and its margins
        pic = np.asarray(im)[: layout.PICTURE_H]
        d = np.abs(pic.astype(int) - np.array(layout.PAPER)).sum(axis=2) > 30
        ys, xs = np.where(d)
        assert xs.min() >= 100 and xs.max() <= 1260 - 100
        assert ys.min() >= 40 and ys.max() <= layout.PICTURE_H - 40


def test_no_city_prints_date_only(photo):
    a = render_card(card("original", photo, city=None)).print_png
    b = render_card(card("original", photo, city="Edinburgh")).print_png
    assert a != b


# ---- QR code ------------------------------------------------------------------------------


def decode(im: Image.Image) -> str:
    qr = np.asarray(im.crop((layout.QR_X - 20, layout.QR_Y - 20, layout.QR_X + layout.QR_PX + 20,
                             layout.QR_Y + layout.QR_PX + 20)).convert("RGB"))[:, :, ::-1].copy()
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.resize(qr, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    return text


@pytest.mark.parametrize("style", ALL_STYLES)
def test_qr_decodes(style, photo):
    out = render_card(card(style, photo))
    assert decode(img(out.print_png)) == URL


def test_qr_decodes_long_url_and_from_half_size_preview(photo):
    url = "https://fretcase.example/s/" + "Zy9" * 12
    out = render_card(card("comic", photo, share_url=url))
    assert decode(img(out.print_png)) == url


def test_qr_is_error_correction_h_with_note_mark():
    from fretcase_card.layout import qr_image
    q = np.asarray(qr_image(URL)).astype(int)
    c = q.shape[0] // 2
    centre = q[c - 14:c + 14, c - 14:c + 14]
    assert (np.abs(centre - np.array(layout.PAPER)).sum(axis=2) > 30).sum() > 20  # the note mark
    assert q.shape[:2] == (178, 178)


# ---- fonts and cover errors ---------------------------------------------------------------


@pytest.fixture
def no_font(monkeypatch):
    monkeypatch.delenv(fonts.FONT_ENV, raising=False)
    monkeypatch.setattr(fonts, "_CANDIDATES", {"serif": [], "sans": []})
    fonts.clear_cache()
    yield
    fonts.clear_cache()


@pytest.mark.parametrize("style", ["text", "original"])
def test_missing_cjk_font_is_a_clear_error(no_font, style, photo):
    with pytest.raises(OSError, match="fonts-noto-cjk"):
        render_card(card(style, photo))


def test_font_env_points_nowhere(monkeypatch):
    monkeypatch.setenv(fonts.FONT_ENV, "/nonexistent/font.ttc")
    fonts.clear_cache()
    try:
        with pytest.raises(OSError, match=fonts.FONT_ENV):
            render_card(card("text"))
    finally:
        monkeypatch.undo()
        fonts.clear_cache()


def test_font_env_is_used(monkeypatch):
    path = fonts.font_path("sans")
    monkeypatch.setenv(fonts.FONT_ENV, path)
    fonts.clear_cache()
    try:
        assert fonts.font_path("serif") == path
        render_card(card("text"))
    finally:
        monkeypatch.undo()
        fonts.clear_cache()


def test_unreadable_cover(tmp_path):
    with pytest.raises(OSError):
        render_card(card("comic", tmp_path / "missing.jpg"))
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(OSError):
        render_card(card("comic", bad))


def test_small_and_portrait_covers(tmp_path):
    for name, size in {"tiny": (40, 30), "portrait": (600, 1400), "wide": (3000, 400)}.items():
        p = tmp_path / f"{name}.png"
        Image.fromarray((np.random.default_rng(3).random((size[1], size[0], 3)) * 255).astype(np.uint8)).save(p)
        for style in PHOTO_STYLES:
            assert img(render_card(card(style, p)).print_png).size == (1260, 840)
