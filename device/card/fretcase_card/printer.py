"""Printers: a dry run that writes PNGs, an Instax Wide Link over Bluetooth LE, or a thermal
ESC/POS printer. The kind comes from the spec or from ``FRETCASE_PRINTER``."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any

from PIL import Image

from . import instax

log = logging.getLogger("fretcase.card.printer")

PRINTER_ENV = "FRETCASE_PRINTER"
DRY_RUN_DIR_ENV = "FRETCASE_DRY_RUN_DIR"
THERMAL_WIDTH = 384  # dots across 58 mm paper at 203 dpi
FEED_LINES = 4
PRINT_SIZE = instax.IMAGE_SIZE


class PrinterError(Exception):
    """The printer is missing, out of paper or film, or the image cannot be printed."""


def thermal_image(print_png: bytes) -> Image.Image:
    """1260 x 840 card -> rotated 90 degrees (so it runs along the paper), scaled to 384 px wide,
    Floyd-Steinberg dithered to 1 bit."""
    img = _open_print_image(print_png)
    img = img.rotate(90, expand=True)  # 840 x 1260, counter-clockwise: the strip's left edge is on top
    h = round(img.height * THERMAL_WIDTH / img.width)
    img = img.convert("L").resize((THERMAL_WIDTH, h), Image.Resampling.LANCZOS)
    return img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)


def _open_print_image(print_png: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(print_png))
        img.load()
    except Exception as e:
        raise PrinterError(f"not a valid image: {e}") from e
    if img.size != PRINT_SIZE:
        raise PrinterError(f"print image must be {PRINT_SIZE[0]}x{PRINT_SIZE[1]}, got {img.width}x{img.height}")
    return img.convert("RGB")


class Printer:
    """``spec``: ``dry_run`` | ``instax`` | ``instax:<BLE address>`` | ``thermal:usb:<vid>:<pid>``
    (vendor and product id in hex, e.g. ``thermal:usb:0416:5011``). None reads ``FRETCASE_PRINTER``
    and defaults to ``dry_run``. The dry run writes ``print-0001.png``, ``print-0002.png`` ... to
    ``dry_run_dir`` (default: ``FRETCASE_DRY_RUN_DIR`` or ``./fretcase-prints``).
    """

    def __init__(self, spec: str | None = None, dry_run_dir: Path | None = None):
        if spec is None:
            spec = os.environ.get(PRINTER_ENV) or "dry_run"
        spec = spec.strip() or "dry_run"
        self.spec = spec
        self.dry_run_dir = Path(dry_run_dir) if dry_run_dir is not None else Path(
            os.environ.get(DRY_RUN_DIR_ENV) or "fretcase-prints")
        self._instax_client_factory = None  # tests inject a fake BLE client here
        self.address: str | None = None
        self.usb: tuple[int, int] | None = None
        if spec == "dry_run":
            self.kind = "dry_run"
        elif spec == "instax" or spec.startswith("instax:"):
            self.kind = "instax"
            self.address = spec[len("instax:"):] or None if ":" in spec else None
        elif spec.startswith("thermal:usb:"):
            self.kind = "thermal"
            parts = spec.split(":")
            try:
                if len(parts) != 4:
                    raise ValueError
                self.usb = (int(parts[2], 16), int(parts[3], 16))
            except ValueError:
                raise PrinterError(f"bad printer spec {spec!r}; expected thermal:usb:<vid>:<pid> in hex") from None
        else:
            raise PrinterError(
                f"unknown printer spec {spec!r}; use dry_run, instax, instax:<address> or thermal:usb:<vid>:<pid>")

    # ---- instax ----
    def _instax(self) -> instax.InstaxWide:
        return instax.InstaxWide(self.address, client_factory=self._instax_client_factory)

    # ---- thermal ----
    def _open_thermal(self) -> Any:
        try:
            from escpos import printer as ep

            backend = ep.Usb(self.usb[0], self.usb[1], timeout=5)
            backend.open()
        except Exception as e:
            raise PrinterError(f"cannot open thermal printer {self.spec!r}: {e}") from e
        try:
            backend.profile.profile_data["media"]["width"]["pixels"] = THERMAL_WIDTH
        except Exception:
            pass
        return backend

    @staticmethod
    def _close(backend: Any) -> None:
        try:
            backend.close()
        except Exception:
            pass

    # ---- public ----
    def status(self) -> dict:
        """``{"kind", "connected", "paper": "ok" | "out" | "unknown", "remaining": int | None}``.
        Never raises."""
        if self.kind == "dry_run":
            return {"kind": "dry_run", "connected": True, "paper": "ok", "remaining": None}
        if self.kind == "instax":
            try:
                left = self._instax().status()["remaining"]
            except Exception as e:  # noqa: BLE001
                log.info("instax status failed: %s", e)
                return {"kind": "instax", "connected": False, "paper": "unknown", "remaining": None}
            return {"kind": "instax", "connected": True, "paper": "ok" if left > 0 else "out", "remaining": left}
        try:
            backend = self._open_thermal()
        except PrinterError:
            return {"kind": "thermal", "connected": False, "paper": "unknown", "remaining": None}
        try:
            paper = "unknown"
            try:
                paper = {2: "ok", 1: "ok", 0: "out"}.get(backend.paper_status(), "unknown")
            except Exception:
                pass
            return {"kind": "thermal", "connected": True, "paper": paper, "remaining": None}
        finally:
            self._close(backend)

    def print_card(self, print_png: bytes) -> None:
        """Print the 1260 x 840 image made by ``render_card``. Raises PrinterError."""
        img = _open_print_image(print_png)  # every kind checks the size first
        if self.kind == "dry_run":
            self._print_dry(print_png)
        elif self.kind == "instax":
            try:
                self._instax().print_image(print_png)
            except instax.InstaxError as e:
                raise PrinterError(str(e)) from e
            except Exception as e:
                raise PrinterError(f"printing failed: {e}") from e
        else:
            self._print_thermal(img)

    def _print_dry(self, print_png: bytes) -> None:
        try:
            self.dry_run_dir.mkdir(parents=True, exist_ok=True)
            n = 1 + sum(1 for _ in self.dry_run_dir.glob("print-*.png"))
            path = self.dry_run_dir / f"print-{n:04d}.png"
            while path.exists():
                n += 1
                path = self.dry_run_dir / f"print-{n:04d}.png"
            path.write_bytes(print_png)
        except OSError as e:
            raise PrinterError(f"cannot write dry-run file: {e}") from e
        log.info("dry run: wrote %s", path)

    def _print_thermal(self, img: Image.Image) -> None:
        backend = self._open_thermal()
        try:
            try:
                if backend.paper_status() == 0:
                    raise PrinterError("out of paper")
            except PrinterError:
                raise
            except Exception:
                pass  # cannot read the status: try to print anyway
            backend.image(thermal_image_from(img), impl="bitImageRaster")
            backend.ln(FEED_LINES)
        except PrinterError:
            raise
        except Exception as e:
            raise PrinterError(f"printing failed: {e}") from e
        finally:
            self._close(backend)


def thermal_image_from(img: Image.Image) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return thermal_image(buf.getvalue())
