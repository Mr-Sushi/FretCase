"""Server settings, read from the environment (no secrets are stored in the repository)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

VERSION = "0.1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str) -> Optional[str]:
    return os.environ.get(name) or None


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("FRETCASE_DATA", "./data")))
    # None: QR codes use the server's own origin, taken from the request that asks for a preview
    share_base_url: Optional[str] = field(default_factory=lambda: _env("FRETCASE_SHARE_BASE"))
    # "dry_run" | "instax" | "instax:<address>" | "thermal:usb:<vid>:<pid>"; None lets the card module read FRETCASE_PRINTER
    printer_device: Optional[str] = field(default_factory=lambda: _env("FRETCASE_PRINTER"))
    http_timeout_s: float = field(default_factory=lambda: float(os.environ.get("FRETCASE_HTTP_TIMEOUT", "8")))
    max_upload_bytes: int = 40 * 1024 * 1024
    app_dist: Path = field(default_factory=lambda: Path(os.environ.get("FRETCASE_APP_DIST") or REPO_ROOT / "app" / "dist"))
    text_model_url: Optional[str] = field(default_factory=lambda: _env("FRETCASE_TEXT_MODEL_URL"))
    text_model_key: Optional[str] = field(default_factory=lambda: _env("FRETCASE_TEXT_MODEL_KEY"))
    text_model_name: Optional[str] = field(default_factory=lambda: _env("FRETCASE_TEXT_MODEL_NAME"))
    drafts_ttl_hours: float = 24.0
