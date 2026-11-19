import pytest

from fretcase_card import CardInput, Printer, PrinterError, render_card


@pytest.fixture(scope="module")
def strip() -> bytes:
    return render_card(CardInput("无题", "text", "https://fretcase.example/s/Ab3dEf9hJk2LmN", "2026.11.19", line="一句话")).strip_png


def test_dry_run_writes_numbered_pngs(tmp_path, strip):
    p = Printer(dry_run_dir=tmp_path / "prints")
    assert p.status() == {"connected": True, "paper": "ok"}
    p.print_strip(strip)
    p.print_strip(strip)
    files = sorted((tmp_path / "prints").glob("print-*.png"))
    assert [f.name for f in files] == ["print-0001.png", "print-0002.png"]
    assert files[0].read_bytes() == strip


def test_not_configured(strip, monkeypatch):
    monkeypatch.delenv("FRETCASE_PRINTER", raising=False)
    p = Printer()
    assert p.status() == {"connected": False, "paper": "unknown"}
    with pytest.raises(PrinterError):
        p.print_strip(strip)


def test_rejects_bad_images(tmp_path):
    p = Printer(dry_run_dir=tmp_path)
    with pytest.raises(PrinterError):
        p.print_strip(b"not a png")
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("1", (200, 50), 1).save(buf, format="PNG")
    with pytest.raises(PrinterError):
        p.print_strip(buf.getvalue())
    assert list(tmp_path.glob("*.png")) == []


def test_missing_device_file(strip):
    p = Printer(device="/dev/usb/lp-does-not-exist")
    assert p.status()["connected"] is False
    with pytest.raises(PrinterError):
        p.print_strip(strip)


def test_hardware_path_sends_raster_and_feed(strip, monkeypatch):
    from escpos.printer import Dummy

    class Fake(Dummy):
        paper = 2

        def paper_status(self):
            return self.paper

    fake = Fake()
    p = Printer(device="/dev/null")
    monkeypatch.setattr(p, "_open_backend", lambda: fake)
    assert p.status() == {"connected": True, "paper": "ok"}
    p.print_strip(strip)
    out = fake.output
    assert b"\x1dv0" in out  # GS v 0: raster bit image
    assert out.endswith(b"\n\n\n\n")
    fake.paper = 0
    assert p.status()["paper"] == "out"
    with pytest.raises(PrinterError, match="paper"):
        p.print_strip(strip)


def test_hardware_failure_becomes_printer_error(strip, monkeypatch):
    class Broken:
        def paper_status(self):
            raise OSError("no status")

        def image(self, *a, **k):
            raise OSError("USB write failed")

        def close(self):
            pass

    p = Printer(device="/dev/null")
    monkeypatch.setattr(p, "_open_backend", lambda: Broken())
    assert p.status() == {"connected": True, "paper": "unknown"}
    with pytest.raises(PrinterError, match="USB write failed"):
        p.print_strip(strip)
