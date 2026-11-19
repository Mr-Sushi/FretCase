import io

import pytest
from fretcase_card import CardInput, Printer, PrinterError, render_card
from fretcase_card.printer import thermal_image
from PIL import Image


@pytest.fixture(scope="module")
def png() -> bytes:
    return render_card(CardInput("无题", "text", "https://fretcase.example/s/Ab3dEf9hJk2LmN",
                                 "2026.11.19", line="一句话")).print_png


def test_default_is_dry_run(monkeypatch, tmp_path):
    monkeypatch.delenv("FRETCASE_PRINTER", raising=False)
    p = Printer(dry_run_dir=tmp_path)
    assert p.status() == {"kind": "dry_run", "connected": True, "paper": "ok", "remaining": None}


def test_env_selects_kind(monkeypatch):
    monkeypatch.setenv("FRETCASE_PRINTER", "instax:11:22:33:44:55:66")
    assert Printer().kind == "instax"
    monkeypatch.setenv("FRETCASE_PRINTER", "thermal:usb:0416:5011")
    p = Printer()
    assert p.kind == "thermal" and p.usb == (0x416, 0x5011)
    monkeypatch.setenv("FRETCASE_PRINTER", "thermal:usb:0x0416:0x5011")
    assert Printer().usb == (0x416, 0x5011)


@pytest.mark.parametrize("spec", ["laser", "thermal:usb:zz:1", "thermal:usb:0416", "thermal:/dev/usb/lp0"])
def test_bad_spec(spec):
    with pytest.raises(PrinterError):
        Printer(spec)


def test_dry_run_writes_numbered_pngs(tmp_path, png):
    p = Printer("dry_run", dry_run_dir=tmp_path / "prints")
    p.print_card(png)
    p.print_card(png)
    files = sorted((tmp_path / "prints").glob("print-*.png"))
    assert [f.name for f in files] == ["print-0001.png", "print-0002.png"]
    assert files[0].read_bytes() == png


def test_rejects_bad_images(tmp_path):
    p = Printer("dry_run", dry_run_dir=tmp_path)
    with pytest.raises(PrinterError):
        p.print_card(b"not a png")
    buf = io.BytesIO()
    Image.new("RGB", (200, 50)).save(buf, format="PNG")
    with pytest.raises(PrinterError):
        p.print_card(buf.getvalue())
    assert list(tmp_path.glob("*.png")) == []


def test_thermal_image_is_rotated_and_dithered(png):
    t = thermal_image(png)
    assert t.mode == "1" and t.size == (384, 576)  # 840x1260 after the turn, scaled to 384 wide


def test_thermal_rotation_direction():
    """A mark in the top-left corner of the card ends up in the bottom-left after a 90 degree
    counter-clockwise turn (the card's left edge becomes the paper's bottom... verified here)."""
    im = Image.new("RGB", (1260, 840), "white")
    im.paste((0, 0, 0), (0, 0, 300, 300))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    t = thermal_image(buf.getvalue()).convert("L")
    assert t.getpixel((10, 566)) == 0 and t.getpixel((10, 10)) == 255 and t.getpixel((370, 10)) == 255


def test_thermal_hardware_path(png, monkeypatch):
    from escpos.printer import Dummy

    class Fake(Dummy):
        paper = 2

        def paper_status(self):
            return self.paper

    fake = Fake()
    p = Printer("thermal:usb:0416:5011")
    monkeypatch.setattr(p, "_open_thermal", lambda: fake)
    assert p.status() == {"kind": "thermal", "connected": True, "paper": "ok", "remaining": None}
    p.print_card(png)
    assert b"\x1dv0" in fake.output and fake.output.endswith(b"\n\n\n\n")
    fake.paper = 0
    assert p.status()["paper"] == "out"
    with pytest.raises(PrinterError, match="paper"):
        p.print_card(png)


def test_thermal_missing_device(png):
    p = Printer("thermal:usb:dead:beef")
    assert p.status()["connected"] is False
    with pytest.raises(PrinterError):
        p.print_card(png)


def test_thermal_failure_becomes_printer_error(png, monkeypatch):
    class Broken:
        def paper_status(self):
            raise OSError("no status")

        def image(self, *a, **k):
            raise OSError("USB write failed")

        def close(self):
            pass

    p = Printer("thermal:usb:0416:5011")
    monkeypatch.setattr(p, "_open_thermal", lambda: Broken())
    with pytest.raises(PrinterError, match="USB write failed"):
        p.print_card(png)
