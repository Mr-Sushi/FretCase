"""Preview and print through the real card module in device/card, not the stub.

The other server tests use the stub in tests/stubs. This one loads the real package under
a separate module name, so both can live in one test session.
"""
import importlib.util
import io
import sys
from pathlib import Path

import pytest

from conftest import Api, png_bytes

CARD_PACKAGE = Path(__file__).resolve().parents[2] / "device" / "card" / "fretcase_card"


def load_real_card_module():
    name = "fretcase_card_real"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, CARD_PACKAGE / "__init__.py", submodule_search_locations=[str(CARD_PACKAGE)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def real_api(make_client):
    pytest.importorskip("qrcode")
    module = load_real_card_module()
    if "print_png" not in getattr(getattr(module, "CardImages", None), "__dataclass_fields__", {}):
        pytest.skip("device/card is not at card module version 2 yet")
    try:
        module.render_card(module.CardInput(title="试", style="text", share_url="https://x.example/s/a", date_text="2026.11.19"))
    except OSError as exc:  # no CJK font on this machine
        pytest.skip(f"card module cannot render here: {exc}")
    return Api(make_client(card_module_loader=lambda: module))


@pytest.mark.parametrize("style", ["text", "ink", "comic", "xieyi", "original"])
def test_preview_and_print_with_the_real_card_module(real_api, style):
    from PIL import Image

    song = real_api.song()
    if style != "text":
        photo = real_api.upload(png_bytes(size=(320, 240)), "photo", name="p.png", mime="image/png")
        song = real_api.edit(song, {"op": "setCard", "style": style, "photoAssetIds": [photo["id"]], "showPhoto": True})
    else:
        song = real_api.edit(song, {"op": "setCard", "style": "text", "line": "海风把傍晚吹进歌里"})
    previewed = real_api.post(song, "card/preview")
    r = real_api.c.get(f"/api/assets/{previewed['card']['frontAssetId']}")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert Image.open(io.BytesIO(r.content)).size == (1260, 840)
    printed = real_api.post(previewed, "card/print")
    assert printed["card"]["printedAt"]
