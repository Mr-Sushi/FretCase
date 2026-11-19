"""The Pydantic model generated from the shared schema, and the check that generated songs validate against both."""
import json
from pathlib import Path

import pytest

from conftest import METERS, SCHEMA_DIR, make_seed
from fretcase_engine.editing import check_consistency
from fretcase_engine.generate import generate_song
from fretcase_engine.song_model import Song

EXAMPLES = sorted((SCHEMA_DIR / "examples").glob("song*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_pydantic_model_accepts_the_schema_examples(path):
    song = json.loads(path.read_text(encoding="utf-8"))
    model = Song.model_validate(song)
    assert model.id == song["id"]
    assert check_consistency(song) == []


def test_pydantic_model_rejects_what_the_schema_rejects():
    song = json.loads((SCHEMA_DIR / "examples" / "song.json").read_text(encoding="utf-8"))
    song["tracks"].pop("bass")
    with pytest.raises(Exception):
        Song.model_validate(song)


@pytest.mark.parametrize("meter", METERS)
@pytest.mark.parametrize("tonic,mode", [("C", "major"), ("Bb", "major"), ("F#", "minor"), ("E", "minor")])
def test_generated_songs_validate_against_schema_and_model(song_validator, meter, tonic, mode):
    song = generate_song(make_seed(tonic, mode, meter), "song-test-0001", "2026-11-19T10:00:00Z")
    errors = [e.message for e in song_validator.iter_errors(song)]
    assert errors == []
    Song.model_validate(song)
    assert check_consistency(song) == []
