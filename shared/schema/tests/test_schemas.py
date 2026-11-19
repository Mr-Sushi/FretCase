"""Checks that the shared interfaces are valid and that the examples follow them.

Run from the repository root:  uv run --with jsonschema --with pytest pytest shared/schema/tests
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR = Path(__file__).resolve().parents[1]
EXAMPLES = SCHEMA_DIR / "examples"
PRESETS = SCHEMA_DIR.parent / "data" / "rhythm-presets.json"
TICKS_PER_QUARTER = 480


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    schema = load(SCHEMA_DIR / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


SONG = validator("song.schema.json")
PANEL = validator("panel-events.schema.json")
SONG_EXAMPLES = sorted(EXAMPLES.glob("song*.json"))


def bar_ticks(song: dict) -> int:
    meter = song["meter"]
    return meter["numerator"] * TICKS_PER_QUARTER * 4 // meter["denominator"]


def errors(v: Draft202012Validator, instance) -> list[str]:
    return [f"{list(e.absolute_path)}: {e.message}" for e in v.iter_errors(instance)]


@pytest.mark.parametrize("path", SONG_EXAMPLES, ids=lambda p: p.name)
def test_song_example_matches_schema(path):
    assert errors(SONG, load(path)) == []


@pytest.mark.parametrize("path", SONG_EXAMPLES, ids=lambda p: p.name)
def test_song_example_is_consistent(path):
    """Rules the schema cannot express. The server must keep these true too."""
    song = load(path)
    length = song["bars"] * bar_ticks(song)

    sections = song["sections"]
    assert sections[0]["startBar"] == 0
    assert sections[-1]["endBar"] == song["bars"]
    for a, b in zip(sections, sections[1:]):
        assert a["endBar"] == b["startBar"], "sections must be contiguous"
    section_ids = {s["id"] for s in sections}

    position = 0
    for chord in song["harmony"]:
        assert chord["start"] >= position, "chords must not overlap"
        position = chord["start"] + chord["duration"]
    assert position <= length

    for track_id, track in song["tracks"].items():
        for note in track.get("notes", []):
            assert note["start"] + note["duration"] <= length, f"{track_id} note past the end"
        for clip in track.get("clips", []):
            assert clip["start"] + clip["duration"] <= length

    for lock in song["locks"]:
        if "section" in lock:
            assert lock["section"] in section_ids

    asset_ids = {a["id"] for a in song["assets"]}
    for clip in song["tracks"]["ambience"]["clips"]:
        assert clip["assetId"] in asset_ids

    # Regions: one per section, in section order; a silent region has no notes or clips there.
    bar = bar_ticks(song)
    for track_id, track in song["tracks"].items():
        assert [r["section"] for r in track["regions"]] == [s["id"] for s in sections], track_id
        for region, section in zip(track["regions"], sections):
            if region["play"]:
                continue
            start, end = section["startBar"] * bar, section["endBar"] * bar
            assert not [n for n in track.get("notes", []) if start <= n["start"] < end], f"{track_id} plays in a silent region"
            assert not [c for c in track.get("clips", []) if c["start"] < end and c["start"] + c["duration"] > start]

    photo_ids = {a["id"] for a in song["assets"] if a["role"] == "photo"}
    card = song.get("card")
    if card:
        assert set(card.get("photoAssetIds", [])) <= photo_ids
        if card["style"] == "text":
            assert "coverAssetId" not in card
        else:
            assert card["coverAssetId"] in card["photoAssetIds"]

    presets = {p["id"]: p for p in load(PRESETS)["presets"]}
    rhythm = song["tracks"]["guitar"]["rhythm"]
    preset = presets[rhythm["presetId"]]
    assert preset["family"] == rhythm["family"]
    meter = f'{song["meter"]["numerator"]}/{song["meter"]["denominator"]}'
    assert preset["meter"] == meter


@pytest.mark.parametrize(
    "why, change",
    [
        ("missing track", lambda s: s["tracks"].pop("bass")),
        ("empty lock", lambda s: s["locks"].append({})),
        ("text input without text", lambda s: s["seed"]["inputs"].append({"kind": "text"})),
        ("unsupported meter", lambda s: s.update(meter={"numerator": 5, "denominator": 4})),
        ("six strings exactly", lambda s: s["harmony"][0]["voicing"]["frets"].pop()),
        ("unknown top-level field", lambda s: s.update(colour="red")),
        ("unknown note field", lambda s: s["tracks"]["melody"]["notes"][0].update(lyric="x")),
        ("volume above 1", lambda s: s["tracks"]["drums"].update(volume=1.2)),
        ("ten photos", lambda s: s["seed"]["inputs"].extend({"kind": "photo", "assetId": f"a-photo-x{i}"} for i in range(8))),
        ("ten photos on the card", lambda s: s["card"].update(photoAssetIds=[f"a-photo-x{i}" for i in range(10)])),
        ("track without regions", lambda s: s["tracks"]["guitar"].pop("regions")),
        ("region intensity above 1", lambda s: s["tracks"]["drums"]["regions"][0].update(intensity=1.5)),
        ("bass cannot lead", lambda s: s["sections"][0].update(lead="bass")),
        ("unknown master space", lambda s: s["master"].update(space="cave")),
        ("old single photo field", lambda s: s["card"].update(photoAssetId="a-photo-01")),
        ("candidate index above 2", lambda s: s["candidate"].update(index=3)),
    ],
)
def test_song_schema_rejects(why, change):
    song = load(EXAMPLES / "song.json")
    change(song)
    assert errors(SONG, song), why


def test_panel_examples_match_schema():
    for message in load(EXAMPLES / "panel-messages.json"):
        assert errors(PANEL, message) == [], message["type"]


@pytest.mark.parametrize("case", load(EXAMPLES / "panel-messages-invalid.json"), ids=lambda c: c["why"])
def test_panel_schema_rejects(case):
    assert errors(PANEL, case["msg"]), case["why"]


def test_every_meter_has_a_rhythm_preset():
    presets = load(PRESETS)["presets"]
    meters = {p["meter"] for p in presets}
    assert {"2/4", "3/4", "4/4", "6/8"} <= meters
    for preset in presets:
        assert preset["level"] in {"start", "next", "challenge"}
        assert ("steps" in preset) == (preset["family"] == "strumming")
        assert ("picking" in preset) == (preset["family"] == "arpeggio")
