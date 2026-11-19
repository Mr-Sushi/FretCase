"""Generation from a seed card: every meter, with and without a capo, every density level."""
import json

import pytest

from conftest import METERS, NOW, make_seed
from fretcase_engine.accompaniment import KICK
from fretcase_engine.common import bar_ticks
from fretcase_engine.generate import generate_song, default_bars
from fretcase_engine.harmony_reasoning import chord_symbol_to_tones
from fretcase_engine.rhythm import load_presets


def meter_dict(text):
    n, d = METERS[text]
    return {"numerator": n, "denominator": d}


@pytest.mark.parametrize("meter", METERS)
@pytest.mark.parametrize("tonic,mode,capo", [("C", "major", False), ("A", "minor", False), ("Bb", "major", True), ("F#", "minor", True)])
def test_every_meter_with_and_without_capo(song_cache, meter, tonic, mode, capo):
    song = song_cache(tonic, mode, meter)
    assert (song["capo"] is not None) is capo
    bt = bar_ticks(meter_dict(meter))
    assert song["bars"] == 16
    assert [e["start"] for e in song["harmony"]] == [i * bt for i in range(16)]
    assert all(e["duration"] == bt for e in song["harmony"])
    presets = {p["id"]: p for p in load_presets()["presets"]}
    assert presets[song["tracks"]["guitar"]["rhythm"]["presetId"]]["meter"] == meter
    for name in ("melody", "guitar", "bass", "drums"):
        assert song["tracks"][name]["notes"], name
    assert [n["start"] for n in song["tracks"]["vocal"]["notes"]] == [n["start"] for n in song["tracks"]["melody"]["notes"]]
    # one song-wide capo: sounding symbols are spelled for the key, shape symbols present only with a capo
    for event in song["harmony"]:
        assert ("shapeSymbol" in event) is capo


@pytest.mark.parametrize("tonic,mode", [("Bb", "major"), ("F#", "minor"), ("Eb", "major")])
def test_capo_guitar_notes_are_sounding_pitches(song_cache, tonic, mode):
    song = song_cache(tonic, mode, "4/4")
    fret = song["capo"]["fret"]
    bt = bar_ticks(song["meter"])
    for event in song["harmony"][:8]:
        tones, _, _ = chord_symbol_to_tones(event["symbol"])
        notes = [n for n in song["tracks"]["guitar"]["notes"] if event["start"] <= n["start"] < event["start"] + bt]
        assert notes
        # every guitar note is a tone of the sounding chord (the shape's frets plus the capo)
        assert {n["pitch"] % 12 for n in notes} <= tones, (event["symbol"], event.get("shapeSymbol"), fret)


@pytest.mark.parametrize("density,level", [(0.1, "start"), (0.5, "next"), (0.9, "challenge")])
def test_every_density_level_picks_a_preset_of_that_level(song_cache, density, level):
    from fretcase_engine.generate import apply_density

    song = song_cache("G", "major", "4/4")
    song["controls"]["density"] = density
    out = apply_density(song)
    presets = {p["id"]: p for p in load_presets()["presets"]}
    assert presets[out["tracks"]["guitar"]["rhythm"]["presetId"]]["level"] == level
    assert out["tracks"]["guitar"]["notes"]


@pytest.mark.parametrize("meter,density,expected", [
    ("2/4", 0.9, "start"), ("3/4", 0.5, "start"), ("6/8", 0.1, "next"), ("6/8", 0.9, "next"), ("4/4", 0.9, "challenge"),
])
def test_nearest_level_when_the_meter_has_no_preset_at_the_requested_level(meter, density, expected):
    from fretcase_engine.rhythm import choose_preset

    preset = choose_preset(meter_dict(meter), density)
    assert preset["meter"] == meter and preset["level"] == expected


def test_generation_is_deterministic(song_cache):
    a = generate_song(make_seed("D", "major"), "song-test-0002", NOW)
    b = generate_song(make_seed("D", "major"), "song-test-0002", NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_motif_is_fitted_and_repeated_to_the_section_plan(song_cache):
    motif = [{"start": 0, "duration": 480, "pitch": 67}, {"start": 480, "duration": 480, "pitch": 69}, {"start": 960, "duration": 960, "pitch": 71}]
    song = song_cache("G", "major", "4/4", bars=16, motif=motif)
    notes = song["tracks"]["melody"]["notes"]
    bt = bar_ticks(song["meter"])
    # the opening states the motif as hummed, one bar long, repeated through the section
    assert [(n["start"], n["pitch"]) for n in notes[:3]] == [(0, 67), (480, 69), (960, 71)]
    assert [n["start"] for n in notes if n["start"] < 4 * bt][::3] == [0, bt, 2 * bt, 3 * bt]
    # the development moves it up a scale step
    verse = [n for n in notes if 4 * bt <= n["start"] < 5 * bt]
    assert [n["pitch"] for n in verse] == [69, 71, 72]
    # the song ends on the tonic, held to the end
    assert notes[-1]["pitch"] % 12 == 7
    assert notes[-1]["start"] + notes[-1]["duration"] == 16 * bt


def test_without_motif_the_offline_melody_fills_every_bar(song_cache):
    song = song_cache("C", "major", "3/4")
    bt = bar_ticks(song["meter"])
    covered = {n["start"] // bt for n in song["tracks"]["melody"]["notes"]}
    assert covered == set(range(16))
    assert song["seed"].get("motif") is None


def test_short_motif_makes_an_eight_bar_song():
    short = [{"start": 0, "duration": 480, "pitch": 60}]
    assert default_bars(make_seed(motif=short), meter_dict("4/4")) == 8
    song = generate_song(make_seed(motif=short), "song-test-0003", NOW)
    assert song["bars"] == 8
    assert [s["endBar"] - s["startBar"] for s in song["sections"]] == [2, 2, 2, 2]


def test_default_sections_and_mix(song_cache):
    song = song_cache()
    assert [s["label"] for s in song["sections"]] == ["开头", "展开", "高潮", "结尾"]
    assert [(s["startBar"], s["endBar"]) for s in song["sections"]] == [(0, 4), (4, 8), (8, 12), (12, 16)]
    assert song["controls"] == {"brightness": 0.5, "complexity": 0.5, "density": 0.5}
    assert song["locks"] == []
    assert all(song["tracks"][t]["volume"] == 0.8 for t in song["tracks"])
    assert song["provenance"]["harmonySource"] == "library"


def test_first_and_last_chord_are_the_tonic(song_cache):
    for tonic, mode in [("C", "major"), ("A", "minor"), ("D", "major")]:
        song = song_cache(tonic, mode)
        assert song["harmony"][0]["symbol"].startswith(tonic)
        assert song["harmony"][-1]["symbol"].startswith(tonic)


def test_ambience_clip_comes_from_a_sound_input():
    seed = make_seed()
    seed["inputs"].append({"kind": "sound", "assetId": "a-waves-01"})
    assets = [{"id": "a-waves-01", "role": "ambience", "mime": "audio/webm", "durationSec": 10.2}]
    song = generate_song(seed, "song-test-0004", NOW, assets=assets)
    clip = song["tracks"]["ambience"]["clips"][0]
    assert clip["assetId"] == "a-waves-01" and clip["loop"] and clip["start"] == 0
    assert clip["duration"] == song["bars"] * bar_ticks(song["meter"])
    assert song["assets"] == assets


def test_bass_and_drums_follow_density(song_cache):
    from fretcase_engine.accompaniment import bass_notes, drum_notes

    song = song_cache()
    low = drum_notes(0, 4, song["meter"], 0.1)
    high = drum_notes(0, 4, song["meter"], 0.9)
    assert len(high) > len(low)
    assert all(n["pitch"] in (36, 38, 42, 46) for n in high)
    assert sum(1 for n in low if n["pitch"] == KICK) == 8
    assert len(bass_notes(song["harmony"], song["meter"], 0.9)) > len(bass_notes(song["harmony"], song["meter"], 0.1))
    assert all(36 <= n["pitch"] <= 60 for n in bass_notes(song["harmony"], song["meter"], 0.9))
