import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "shared" / "schema"
NOW = "2026-11-19T10:00:00Z"
METERS = {"2/4": (2, 4), "3/4": (3, 4), "4/4": (4, 4), "6/8": (6, 8)}


@pytest.fixture(scope="session")
def song_validator():
    schema = json.loads((SCHEMA_DIR / "song.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def make_seed(tonic="C", mode="minor" if False else "major", meter="4/4", motif=None, tempo=90, text="海边的傍晚"):
    n, d = METERS[meter]
    seed = {
        "inputs": [{"kind": "text", "text": text}],
        "key": {"tonic": tonic, "mode": mode},
        "tempo": tempo,
        "meter": {"numerator": n, "denominator": d},
        "mood": "平静偏暖",
        "reasons": [{"field": "key", "text": "test"}],
        "source": "offline",
    }
    if motif is not None:
        seed["motif"] = motif
    return seed


@pytest.fixture
def seed_factory():
    return make_seed


@pytest.fixture(scope="session")
def song_cache():
    from fretcase_engine.generate import generate_song

    cache = {}

    def get(tonic="C", mode="major", meter="4/4", bars=None, motif=None):
        key = (tonic, mode, meter, bars, json.dumps(motif))
        if key not in cache:
            cache[key] = generate_song(make_seed(tonic, mode, meter, motif), "song-test-0001", NOW, bars=bars)
        return copy.deepcopy(cache[key])

    return get
