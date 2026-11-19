"""Server settings, read from the environment (no secrets are stored in the repository)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

VERSION = "0.1.0"


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("FRETCASE_DATA", "./data")))
    share_base_url: str = field(default_factory=lambda: os.environ.get("FRETCASE_SHARE_BASE", "https://fretcase.example"))
    printer_device: Optional[str] = field(default_factory=lambda: os.environ.get("FRETCASE_PRINTER") or None)
    http_timeout_s: float = field(default_factory=lambda: float(os.environ.get("FRETCASE_HTTP_TIMEOUT", "8")))
    max_upload_bytes: int = 40 * 1024 * 1024
