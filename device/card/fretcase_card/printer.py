"""Thermal printing with python-escpos, or a dry run that writes PNG files."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any

from PIL import Image

from .layout import WIDTH

log = logging.getLogger("fretcase.card.printer")

PRINTER_ENV = "FRETCASE_PRINTER"
FEED_LINES = 4


class PrinterError(Exception):
    """The printer is missing, out of paper, or the image cannot be printed."""


class Printer:
    """A 58 mm ESC/POS thermal printer.

    ``device`` is one of ``usb:0x0416:0x5011`` (vendor and product id), ``serial:/dev/ttyUSB0[:9600]``
    or a device file such as ``/dev/usb/lp0``. When ``device`` is None the environment variable
    ``FRETCASE_PRINTER`` is used. With ``dry_run_dir`` nothing is sent to hardware: each strip is
    written to that directory as ``print-0001.png``, ``print-0002.png`` and so on.
    """

    def __init__(self, device: str | None = None, dry_run_dir: Path | None = None):
        self.device = device if device is not None else os.environ.get(PRINTER_ENV)
        self.dry_run_dir = Path(dry_run_dir) if dry_run_dir is not None else None

    # ---- hardware ---------------------------------------------------------------------

    def _open_backend(self) -> Any:
        """Open the escpos printer object. Raises PrinterError."""
        spec = self.device
        if not spec:
            raise PrinterError("no printer configured (set FRETCASE_PRINTER or pass a device)")
        try:
            from escpos import printer as ep

            if spec.startswith("usb:"):
                parts = spec.split(":")
                backend = ep.Usb(int(parts[1], 0), int(parts[2], 0), timeout=5)
            elif spec.startswith("serial:"):
                parts = spec.split(":")
                baud = int(parts[2]) if len(parts) > 2 else 9600
                backend = ep.Serial(devfile=parts[1], baudrate=baud, timeout=5)
            else:
                backend = ep.File(devfile=spec)
            backend.open()  # python-escpos opens lazily; fail here, not halfway through a print
        except PrinterError:
            raise
        except Exception as e:
            raise PrinterError(f"cannot open printer {spec!r}: {e}") from e
        try:  # lets python-escpos know the paper width
            backend.profile.profile_data["media"]["width"]["pixels"] = WIDTH
        except Exception:
            pass
        return backend

    @staticmethod
    def _close(backend: Any) -> None:
        try:
            backend.close()
        except Exception:
            pass

    # ---- public -----------------------------------------------------------------------

    def status(self) -> dict:
        """``{"connected": bool, "paper": "ok" | "out" | "unknown"}``. Never raises."""
        if self.dry_run_dir is not None:
            return {"connected": True, "paper": "ok"}
        try:
            backend = self._open_backend()
        except PrinterError:
            return {"connected": False, "paper": "unknown"}
        try:
            paper = "unknown"
            try:
                code = backend.paper_status()  # 2 paper ok, 1 near end, 0 no paper
                paper = {2: "ok", 1: "ok", 0: "out"}.get(code, "unknown")
            except Exception:
                pass  # many cheap printers cannot report it
            return {"connected": True, "paper": paper}
        finally:
            self._close(backend)

    def print_strip(self, strip_png: bytes) -> None:
        """Print a strip made by ``render_card``. Raises PrinterError."""
        try:
            img = Image.open(io.BytesIO(strip_png))
            img.load()
        except Exception as e:
            raise PrinterError(f"not a valid image: {e}") from e
        if img.width != WIDTH:
            raise PrinterError(f"strip must be {WIDTH} px wide, got {img.width}")

        if self.dry_run_dir is not None:
            try:
                self.dry_run_dir.mkdir(parents=True, exist_ok=True)
                n = 1 + sum(1 for _ in self.dry_run_dir.glob("print-*.png"))
                path = self.dry_run_dir / f"print-{n:04d}.png"
                while path.exists():
                    n += 1
                    path = self.dry_run_dir / f"print-{n:04d}.png"
                path.write_bytes(strip_png)
            except OSError as e:
                raise PrinterError(f"cannot write dry-run file: {e}") from e
            log.info("dry run: wrote %s", path)
            return

        backend = self._open_backend()
        try:
            try:
                if backend.paper_status() == 0:
                    raise PrinterError("out of paper")
            except PrinterError:
                raise
            except Exception:
                pass  # cannot read the status: try to print anyway
            backend.image(img.convert("1"), impl="bitImageRaster")
            backend.ln(FEED_LINES)
        except PrinterError:
            raise
        except Exception as e:
            raise PrinterError(f"printing failed: {e}") from e
        finally:
            self._close(backend)
