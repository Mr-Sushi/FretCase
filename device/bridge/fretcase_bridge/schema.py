"""Validation of panel messages against shared/schema/panel-events.schema.json."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_ENV = "FRETCASE_PANEL_SCHEMA"
SCHEMA_RELATIVE = Path("shared") / "schema" / "panel-events.schema.json"


def find_schema_path() -> Path:
    """Locate the panel schema.

    The environment variable wins; otherwise look for the repository's
    ``shared/schema`` directory above this file.
    """
    env = os.environ.get(SCHEMA_ENV)
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / SCHEMA_RELATIVE
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"panel schema not found; set {SCHEMA_ENV} to the path of panel-events.schema.json"
    )


@lru_cache(maxsize=4)
def _validator(path: str) -> Draft202012Validator:
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def get_validator(path: Path | None = None) -> Draft202012Validator:
    return _validator(str(path or find_schema_path()))


def errors_for(message: object, validator: Draft202012Validator | None = None) -> list[str]:
    """Return human-readable schema errors for ``message`` (empty when valid)."""
    v = validator or get_validator()
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(v.iter_errors(message), key=lambda e: list(e.absolute_path))
    ]
