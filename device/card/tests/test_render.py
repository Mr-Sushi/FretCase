import io

import numpy as np
import pytest
from PIL import Image

from fretcase_card import CardInput, render_card
from fretcase_card.layout import FACE_HEIGHT, FOLD_HEIGHT

URL = "https://fretcase.example/s/Ab3dEf9hJk2LmN"
STYLES = ["ink", "comic", "xieyi", "original", "text"]


def card(style="ink", **kw):
    base = dict(title="海边的傍晚", style=style, share_url=URL, date_text="2026.11.19",
                line="潮声把今天慢慢收起来", city="Newcastle upon Tyne")  # fmt: skip
    base.update(kw)
    return CardInput(**base)


def img(b: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(b))
    im.load()
    return im


def black_ratio(im: Image.Image) -> float:
    return float((np.asarray(im.convert("L")) < 128).mean())


@pytest.mark.parametrize("style", STYLES)
def test_sizes_and_mode_with_photo(style, photo):
    r = render_card(card(style, photo_path=photo))
    for png, h in ((r.front_png, FACE_HEIGHT), (r.back_png, FACE_HEIGHT), (r.strip_png, FACE_HEIGHT * 2 + FOLD_HEIGHT)):
        im = img(png)
        assert im.format == "PNG" and im.mode == "1"
        assert im.size == (384, h)


@pytest.mark.parametrize("style", STYLES)
def test_deterministic(style, photo):
    a = render_card(card(style, photo_path=photo))
    b = render_card(card(style, photo_path=photo))
    assert a == b


@pytest.mark.parametrize("style", ["ink", "comic", "xieyi", "original"])
def test_photo_styles_are_not_blank_and_differ(style, photo):
    front = img(render_card(card(style, photo_path=photo)).front_png)
    assert 0.05 < black_ratio(front) < 0.9
    text_front = img(render_card(card("text", photo_path=photo)).front_png)
    assert front.tobytes() != text_front.tobytes()


def test_styles_look_different(photo):
    fronts = {s: render_card(card(s, photo_path=photo)).front_png for s in ["ink", "comic", "xieyi", "original"]}
    assert len(set(fronts.values())) == 4


@pytest.mark.parametrize("style", STYLES)
def test_card_without_photo(style):
    r = render_card(card(style, photo_path=None))
    front = img(r.front_png)
    assert front.size == (384, FACE_HEIGHT)
    assert 0.02 < black_ratio(front) < 0.5
    # the front shows the line; a different line gives a different front
    other = img(render_card(card(style, line="另一句话")).front_png)
    assert other.tobytes() != front.tobytes()


def test_front_without_photo_or_line_uses_title():
    a = img(render_card(card("text", line=None, title="Seaside")).front_png)
    b = img(render_card(card("text", line=None, title="Mountain")).front_png)
    assert a.tobytes() != b.tobytes()
    assert black_ratio(a) > 0.02


def test_city_only_when_not_none():
    with_city = img(render_card(card(city="Lisbon")).back_png)
    none = img(render_card(card(city=None)).back_png)
    empty = img(render_card(card(city="")).back_png)
    assert with_city.tobytes() != none.tobytes()
    assert none.tobytes() == empty.tobytes()


def test_long_text_stays_inside_the_frame():
    long = "很长很长的歌名" * 10 + " And a very long English title that keeps going " * 3
    r = render_card(card(title=long, line=long, city="A" * 80))
    for png in (r.front_png, r.back_png):
        a = np.asarray(img(png).convert("L"))
        assert (a[:, :5] == 255).all() and (a[:, -5:] == 255).all()
        assert (a[:5, :] == 255).all() and (a[-5:, :] == 255).all()


def test_strip_is_front_fold_back(photo):
    r = render_card(card("ink", photo_path=photo))
    strip = np.asarray(img(r.strip_png).convert("L"))
    front = np.asarray(img(r.front_png).convert("L"))
    back = np.asarray(img(r.back_png).convert("L"))
    assert (strip[:FACE_HEIGHT] == front).mean() > 0.999
    lower = strip[FACE_HEIGHT + FOLD_HEIGHT :]
    # the back is printed turned by 180 degrees so that it reads upright once folded
    assert (lower == back[::-1, ::-1]).mean() > 0.999
    fold = strip[FACE_HEIGHT : FACE_HEIGHT + FOLD_HEIGHT]
    assert (fold < 128).any()


def test_qr_code_decodes():
    cv2 = pytest.importorskip("cv2")
    r = render_card(card())
    for png, rotate in ((r.back_png, False), (r.strip_png, True)):
        a = np.asarray(img(png).convert("L"))
        if rotate:
            a = a[FACE_HEIGHT + FOLD_HEIGHT :][::-1, ::-1]
        a = np.ascontiguousarray(a)
        text, points, _ = cv2.QRCodeDetector().detectAndDecode(a)
        assert text == URL


def test_long_url_still_decodes():
    cv2 = pytest.importorskip("cv2")
    url = "https://fretcase.example/s/" + "x" * 30 + "?utm=" + "y" * 40
    a = np.ascontiguousarray(np.asarray(img(render_card(card(share_url=url)).back_png).convert("L")))
    assert cv2.QRCodeDetector().detectAndDecode(a)[0] == url


def test_bad_input(tmp_path):
    with pytest.raises(ValueError):
        render_card(card(style="oil"))
    with pytest.raises(ValueError):
        render_card(card(title="  "))
    with pytest.raises(ValueError):
        render_card(card(share_url=""))
    with pytest.raises(OSError):
        render_card(card(photo_path=tmp_path / "missing.jpg"))


def test_portrait_and_exif_free_small_photo(tmp_path):
    p = tmp_path / "small.png"
    Image.new("RGB", (40, 90), (120, 80, 200)).save(p)
    for s in ["ink", "comic", "xieyi", "original"]:
        assert img(render_card(card(s, photo_path=p)).front_png).size == (384, FACE_HEIGHT)
