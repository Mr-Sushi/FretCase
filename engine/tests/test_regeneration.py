"""Knobs, another take and re-hum: unlocked parts change, locked parts never do."""
import copy

import pytest

from fretcase_engine.common import bar_ticks, section_window
from fretcase_engine.editing import check_consistency
from fretcase_engine.generate import CannotApply, another_take, apply_density, rehum, reharmonise, set_rhythm


def window(song, section_id):
    section = next(s for s in song["sections"] if s["id"] == section_id)
    return section_window(song, section)


def notes_in(song, track, section_id):
    s, e = window(song, section_id)
    return [n for n in song["tracks"][track]["notes"] if s <= n["start"] < e]


def chords_in(song, section_id):
    s, e = window(song, section_id)
    return [c for c in song["harmony"] if s <= c["start"] < e]


@pytest.mark.parametrize("lock", [
    {"section": "s-verse", "track": "guitar"},
    {"section": "s-verse", "track": "bass"},
    {"section": "s-verse"},
])
def test_locked_content_survives_reharmonising(song_cache, lock):
    song = song_cache("E", "major")
    song["locks"].append(lock)
    song["controls"]["complexity"] = 0.95
    out = reharmonise(song)
    assert check_consistency(out) == []
    assert chords_in(out, "s-verse") == chords_in(song, "s-verse")
    assert notes_in(out, "guitar", "s-verse") == notes_in(song, "guitar", "s-verse")
    assert notes_in(out, "bass", "s-verse") == notes_in(song, "bass", "s-verse")
    # the unlocked sections did change
    assert [c["symbol"] for c in out["harmony"]] != [c["symbol"] for c in song["harmony"]]
    assert out["tracks"]["melody"]["notes"] == song["tracks"]["melody"]["notes"]


def test_a_locked_track_is_not_touched_anywhere(song_cache):
    song = song_cache("G", "major")
    song["locks"].append({"track": "guitar"})
    song["controls"]["complexity"] = 0.95
    out = reharmonise(song)
    assert out["tracks"]["guitar"]["notes"] == song["tracks"]["guitar"]["notes"]
    assert out["harmony"] == song["harmony"]  # the guitar is realised from the chords, so they stay too
    assert out["tracks"]["bass"]["notes"] == song["tracks"]["bass"]["notes"]


def test_density_keeps_locked_drums_and_changes_the_rest(song_cache):
    song = song_cache("G", "major")
    song["locks"].append({"track": "drums", "section": "s-chorus"})
    song["controls"]["density"] = 0.95
    out = apply_density(song)
    assert notes_in(out, "drums", "s-chorus") == notes_in(song, "drums", "s-chorus")
    assert notes_in(out, "drums", "s-intro") != notes_in(song, "drums", "s-intro")
    assert out["harmony"] == song["harmony"]


def test_complexity_thirds_change_the_lane(song_cache):
    song = song_cache("C", "major")
    basic, colour = copy.deepcopy(song), copy.deepcopy(song)
    basic["controls"]["complexity"], colour["controls"]["complexity"] = 0.1, 0.95
    plain = {c["symbol"] for c in reharmonise(basic)["harmony"]}
    rich = {c["symbol"] for c in reharmonise(colour)["harmony"]}
    assert all(sym in {"C", "Dm", "Em", "F", "G", "Am"} for sym in plain)
    assert any("7" in sym for sym in rich)


def test_brightness_extremes_move_to_the_relative_key_and_back(song_cache):
    song = song_cache("C", "major")
    dark = copy.deepcopy(song)
    dark["controls"]["brightness"] = 0.05
    out = reharmonise(dark)
    assert out["key"] == {"tonic": "A", "mode": "minor"}
    assert out["harmony"][0]["symbol"].startswith("Am")
    back = copy.deepcopy(out)
    back["controls"]["brightness"] = 0.5
    assert reharmonise(back)["key"] == {"tonic": "C", "mode": "major"}
    # a bright setting on a major song does not change the key
    bright = copy.deepcopy(song)
    bright["controls"]["brightness"] = 0.95
    assert reharmonise(bright)["key"] == {"tonic": "C", "mode": "major"}
    minor = song_cache("A", "minor")
    minor["controls"]["brightness"] = 0.95
    assert reharmonise(minor)["key"] == {"tonic": "C", "mode": "major"}


def test_brightness_bias_prefers_minor_or_major_colour(song_cache):
    song = song_cache("C", "major")
    shares = []
    for b in (0.2, 0.8):
        s = copy.deepcopy(song)
        s["controls"]["brightness"] = b
        out = reharmonise(s)
        shares.append(sum(1 for c in out["harmony"] if c["symbol"].replace("Cm", "").startswith(("Dm", "Em", "Am"))) / 16)
    assert shares[0] >= shares[1]


def test_another_take_does_not_repeat_until_candidates_run_out(song_cache):
    song = song_cache("G", "major")
    seen, state, current = [], {}, song
    for _ in range(3):
        current, state = another_take(current, "s-verse", None, state)
        seen.append(tuple(c["symbol"] for c in chords_in(current, "s-verse")))
    assert len(set(seen)) == 3
    assert check_consistency(current) == []
    # sections that were not asked for are untouched
    for sid in ("s-intro", "s-chorus", "s-outro"):
        assert chords_in(current, sid) == chords_in(song, sid)
        assert notes_in(current, "melody", sid) == notes_in(song, sid and "melody", sid)


def test_another_take_for_one_track_changes_only_that_track(song_cache):
    song = song_cache("G", "major")
    out, _ = another_take(song, "s-verse", "drums", {})
    assert notes_in(out, "drums", "s-verse") != notes_in(song, "drums", "s-verse")
    assert out["harmony"] == song["harmony"]
    assert out["tracks"]["guitar"]["notes"] == song["tracks"]["guitar"]["notes"]
    assert out["tracks"]["bass"]["notes"] == song["tracks"]["bass"]["notes"]
    bass, _ = another_take(song, "s-verse", "bass", {})
    assert notes_in(bass, "bass", "s-verse") != notes_in(song, "bass", "s-verse")
    guitar, _ = another_take(song, "s-verse", "guitar", {})
    assert [c["symbol"] for c in guitar["harmony"]] == [c["symbol"] for c in song["harmony"]]
    assert [c["voicing"] for c in guitar["harmony"]] != [c["voicing"] for c in song["harmony"]]


def test_another_take_skips_locked_tracks(song_cache):
    song = song_cache("G", "major")
    song["locks"].append({"track": "guitar", "section": "s-verse"})
    out, _ = another_take(song, "s-verse", None, {})
    assert chords_in(out, "s-verse") == chords_in(song, "s-verse")
    assert notes_in(out, "guitar", "s-verse") == notes_in(song, "guitar", "s-verse")
    assert notes_in(out, "drums", "s-verse") != notes_in(song, "drums", "s-verse")
    with pytest.raises(CannotApply):
        another_take(song, "s-verse", "guitar", {})
    with pytest.raises(CannotApply):
        another_take(song, "s-verse", "ambience", {})
    with pytest.raises(CannotApply):
        another_take(song, "s-nowhere", None, {})


def test_another_take_replaces_a_generated_melody_but_not_a_hummed_one(song_cache):
    song = song_cache("G", "major")
    out, _ = another_take(song, "s-verse", "melody", {})
    assert notes_in(out, "melody", "s-verse") != notes_in(song, "melody", "s-verse")
    assert notes_in(out, "melody", "s-intro") == notes_in(song, "melody", "s-intro")
    assert [n["start"] for n in notes_in(out, "vocal", "s-verse")] == [n["start"] for n in notes_in(out, "melody", "s-verse")]
    hummed = song_cache("G", "major", bars=16, motif=[{"start": 0, "duration": 480, "pitch": 67}, {"start": 480, "duration": 480, "pitch": 69}])
    with pytest.raises(CannotApply):
        another_take(hummed, "s-verse", "melody", {})


def test_another_take_works_with_a_capo_and_in_every_meter(song_cache):
    for tonic, mode, meter in [("Bb", "major", "4/4"), ("F#", "minor", "3/4"), ("C", "major", "2/4"), ("D", "major", "6/8")]:
        song = song_cache(tonic, mode, meter)
        out, _ = another_take(song, "s-chorus", None, {})
        assert check_consistency(out) == []
        assert out["capo"] == song["capo"]


def test_rehum_replaces_one_section_in_the_songs_key(song_cache):
    song = song_cache("D", "major")
    hum = [{"start": 0, "duration": 480, "pitch": 60}, {"start": 480, "duration": 480, "pitch": 62}, {"start": 960, "duration": 960, "pitch": 64}]
    out = rehum(song, "s-verse", hum)
    assert check_consistency(out) == []
    verse = notes_in(out, "melody", "s-verse")
    assert verse and {n["pitch"] % 12 for n in verse} <= {2, 4, 6, 7, 9, 11, 1}  # D major
    assert notes_in(out, "melody", "s-intro") == notes_in(song, "melody", "s-intro")
    bt = bar_ticks(song["meter"])
    assert max(n["start"] + n["duration"] for n in verse) <= 8 * bt
    assert [n["start"] for n in notes_in(out, "vocal", "s-verse")] == [n["start"] for n in verse]
    assert chords_in(out, "s-intro") == chords_in(song, "s-intro")


def test_rehum_respects_locks(song_cache):
    song = song_cache("D", "major")
    hum = [{"start": 0, "duration": 480, "pitch": 60}]
    locked_melody = copy.deepcopy(song)
    locked_melody["locks"].append({"track": "melody", "section": "s-verse"})
    with pytest.raises(CannotApply):
        rehum(locked_melody, "s-verse", hum)
    locked_vocal = copy.deepcopy(song)
    locked_vocal["locks"].append({"track": "vocal"})
    out = rehum(locked_vocal, "s-verse", hum)
    assert out["tracks"]["vocal"]["notes"] == song["tracks"]["vocal"]["notes"]
    locked_guitar = copy.deepcopy(song)
    locked_guitar["locks"].append({"track": "guitar", "section": "s-verse"})
    out = rehum(locked_guitar, "s-verse", hum)
    assert chords_in(out, "s-verse") == chords_in(song, "s-verse")


def test_set_rhythm_validates_family_and_meter(song_cache):
    song = song_cache("G", "major", "4/4")
    out = set_rhythm(song, "arpeggio", "t321t321")
    assert out["tracks"]["guitar"]["rhythm"] == {"family": "arpeggio", "presetId": "t321t321"}
    assert out["tracks"]["guitar"]["notes"] != song["tracks"]["guitar"]["notes"]
    for bad in [("strumming", "t321t321"), ("strumming", "waltz_basic"), ("arpeggio", "nope")]:
        with pytest.raises(CannotApply):
            set_rhythm(song, *bad)
