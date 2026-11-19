"""Card preview and print through the ``fretcase_card`` interface (docs/milestone-1.md, "Card module").

The module is built by another agent; the server only imports it lazily so the rest of the API works without it.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fretcase_server.errors import ApiError


def load_card_module() -> Any:
    try:
        return importlib.import_module("fretcase_card")
    except ImportError as exc:
        raise ApiError(501, "not_implemented", "The card module (fretcase_card) is not installed on this server") from exc


def date_text(song: Dict[str, Any]) -> str:
    card = song.get("card") or {}
    stamp = card.get("capturedAt") or song["createdAt"]
    return f"{stamp[0:4]}.{stamp[5:7]}.{stamp[8:10]}"


def card_fingerprint(song: Dict[str, Any]) -> str:
    """Everything the printed card shows. Preview and print must agree on it."""
    card = song.get("card") or {}
    parts = {
        "title": song["title"],
        "style": card.get("style"),
        "line": card.get("line"),
        "photo": card.get("photoAssetId") if card.get("style") != "text" else None,
        "city": card.get("city") if card.get("showCity") else None,
        "date": date_text(song),
        "share": (card.get("share") or {}).get("url"),
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def card_input(module: Any, song: Dict[str, Any], photo_path: Optional[Path]) -> Any:
    card = song["card"]
    return module.CardInput(
        title=song["title"],
        style=card["style"],
        share_url=card["share"]["url"],
        date_text=date_text(song),
        line=card.get("line"),
        city=card.get("city") if card.get("showCity") else None,
        photo_path=photo_path if card["style"] != "text" else None,
    )
