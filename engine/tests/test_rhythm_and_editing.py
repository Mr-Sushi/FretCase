import copy
import struct
import xml.dom.minidom

import pytest

from fretcase_engine import editing, export
from fretcase_engine.common import bar_ticks, default_sections, is_locked
from fretcase_engine.generate import CannotApply
from fretcase_engine.rhythm import choose_preset, load_presets, realise

C_VOICING = {"frets": [-1, 3, 2, 0, 1, 0], "fingers": [0, 3, 2, 0, 1, 0], "barres": [], "baseFret": 1, "difficulty": 0.2}
FOUR_FOUR = {"numerator": 4, "denominator": 4}


def one_bar(voicing=C_VOICING):
    return [{"start": 0, "duration": 1920, "symbol": "C", "voicing": voicing}]


def preset(pid):
    return next(p for p in load_presets()["presets"] if p["id"] == pid)


def test_strumming_sounds_the_chord_on_d_and_u_steps_only():
    notes = realise(one_bar(), preset("ddudud"), FOUR_FOUR)
    onsets = sorted({n["start"] for n in notes})
    assert onsets == [0, 480, 720, 1200, 1440, 1680]  # D - D U - U D U on an eighth grid of 240
    assert {n["pitch"] for n in notes if n["start"] == 0} == {48, 52, 55, 60, 64}  # x32010
    # the downstroke at the start is louder than an upstroke
    assert max(n["velocity"] for n in notes if n["start"] == 0) > max(n["velocity"] for n in notes if n["start"] == 720)


def test_strumming_triplet_grid_has_twelve_steps_per_bar():
    notes = realise(one_bar(), preset("driving_triplet_12"), FOUR_FOUR)
    assert all(n["start"] % 160 == 0 for n in notes)


def test_arpeggio_picks_real_strings_and_the_capo_raises_the_pitch():
    notes = realise(one_bar(), preset("t321t321"), FOUR_FOUR)
    assert [n["pitch"] for n in notes] == [48, 55, 60, 64, 48, 55, 60, 64]
    capo = realise(one_bar(), preset("t321t321"), FOUR_FOUR, capo_fret=2)
    assert [n["pitch"] - 2 for n in capo] == [n["pitch"] for n in notes]


@pytest.mark.parametrize("pid,meter", [("two_four_basic", (2, 4)), ("waltz_basic", (3, 4)), ("six_eight_sway", (6, 8)), ("waltz_arp_basic", (3, 4)), ("two_four_arp_basic", (2, 4))])
def test_every_meter_has_a_working_preset(pid, meter):
    m = {"numerator": meter[0], "denominator": meter[1]}
    chord = {"start": 0, "duration": bar_ticks(m) * 2, "symbol": "C", "voicing": C_VOICING}
    notes = realise([chord], preset(pid), m)
    assert notes and all(0 <= n["start"] < bar_ticks(m) * 2 for n in notes)
    assert any(n["start"] >= bar_ticks(m) for n in notes)  # the pattern repeats in the second bar


def test_choose_preset_varies_inside_a_third():
    ids = {choose_preset(FOUR_FOUR, d)["id"] for d in (0.67, 0.72, 0.8, 0.9, 0.99)}
    assert len(ids) > 1


# ----------------------------------------------------------------------------------------------- editing


def test_replace_notes_replaces_the_range_and_locks_the_sections_touched(song_cache):
    song = song_cache("G", "major")
    bt = bar_ticks(song["meter"])
    new = [{"start": 4 * bt, "duration": 480, "pitch": 72, "velocity": 80}]
    out = editing.replace_notes(song, "melody", 3 * bt + 960, 5 * bt, new)
    starts = [n["start"] for n in out["tracks"]["melody"]["notes"]]
    assert 4 * bt in starts
    assert not any(3 * bt + 960 <= n["start"] < 5 * bt and n["pitch"] != 72 for n in out["tracks"]["melody"]["notes"])
    assert {"track": "melody", "section": "s-intro"} in out["locks"] and {"track": "melody", "section": "s-verse"} in out["locks"]
    assert is_locked(out, "melody", "s-verse") and not is_locked(out, "melody", "s-chorus")
    assert editing.check_consistency(out) == []


def test_replace_notes_rules(song_cache):
    song = song_cache("G", "major")
    with pytest.raises(CannotApply):
        editing.replace_notes(song, "ambience", 0, 480, [])
    with pytest.raises(CannotApply):
        editing.replace_notes(song, "melody", 0, 480, [{"start": 960, "duration": 480, "pitch": 60}])
    with pytest.raises(CannotApply):
        editing.replace_notes(song, "melody", 0, 10**9, [])
    with pytest.raises(CannotApply):
        editing.replace_notes(song, "melody", 480, 0, [])


def test_lyrics_one_character_per_note_and_mismatch_detail(song_cache):
    song = song_cache("G", "major")
    s, e = 0, 4 * bar_ticks(song["meter"])
    count = len([n for n in song["tracks"]["vocal"]["notes"] if s <= n["start"] < e])
    text = "海" * (count - 1) + "风"
    out = editing.set_lyrics(song, "s-intro", text)
    vocal = [n for n in out["tracks"]["vocal"]["notes"] if s <= n["start"] < e]
    assert [n["lyric"] for n in vocal] == list("海" * (count - 1) + "风")
    assert vocal[-1]["lineEnd"] is True
    with pytest.raises(CannotApply) as info:
        editing.set_lyrics(song, "s-intro", "海风")
    assert info.value.detail == {"noteCount": count, "syllableCount": 2}


def test_lyrics_lines_and_english_words():
    assert editing.split_syllables("海风，吹过\n你 好") == [["海", "风"], ["吹", "过"], ["你", "好"]]
    assert editing.split_syllables("sea breeze, blow") == [["sea", "breeze"], ["blow"]]


def test_set_sections_must_be_contiguous_and_cover_every_bar(song_cache):
    song = song_cache("G", "major")
    good = [{"id": "s-first", "label": "一", "startBar": 0, "endBar": 6}, {"id": "s-second", "label": "二", "startBar": 6, "endBar": 16}]
    out = editing.set_sections(song, good)
    assert [s["id"] for s in out["sections"]] == ["s-first", "s-second"]
    bad_cases = [
        [{"id": "s-first", "label": "x", "startBar": 0, "endBar": 6}],
        [{"id": "s-first", "label": "x", "startBar": 1, "endBar": 16}],
        [{"id": "s-first", "label": "x", "startBar": 0, "endBar": 6}, {"id": "s-second", "label": "y", "startBar": 7, "endBar": 16}],
        [{"id": "s-first", "label": "x", "startBar": 0, "endBar": 8}, {"id": "s-first", "label": "y", "startBar": 8, "endBar": 16}],
        [],
    ]
    for bad in bad_cases:
        with pytest.raises(CannotApply):
            editing.set_sections(song, bad)


def test_lock_and_unlock_exactly(song_cache):
    song = song_cache("G", "major")
    s1 = editing.lock(song, "drums", None)
    s2 = editing.lock(s1, "drums", "s-verse")
    assert s2["locks"] == [{"track": "drums"}, {"track": "drums", "section": "s-verse"}]
    s3 = editing.unlock(s2, "drums", "s-verse")
    assert s3["locks"] == [{"track": "drums"}]
    for fn, args in [(editing.lock, (None, None)), (editing.lock, ("drums", "s-nope")), (editing.unlock, ("bass", None)), (editing.lock, ("kazoo", None))]:
        with pytest.raises(CannotApply):
            fn(s3, *args)


# ----------------------------------------------------------------------------------------------- export


@pytest.mark.parametrize("meter", ["2/4", "3/4", "4/4", "6/8"])
def test_exports_are_well_formed(song_cache, meter):
    song = song_cache("Bb", "major", meter)
    midi = export.to_midi(song)
    assert midi[:4] == b"MThd"
    fmt, tracks, division = struct.unpack(">HHH", midi[8:14])
    assert (fmt, tracks, division) == (1, 6, 480)  # conductor + vocal, melody, guitar, bass, drums
    assert midi.count(b"MTrk") == 6
    doc = xml.dom.minidom.parseString(export.to_musicxml(song))
    assert len(doc.getElementsByTagName("measure")) == 16
    assert len(doc.getElementsByTagName("harmony")) == 16
    assert len(doc.getElementsByTagName("frame")) == 16
    abc = export.to_abc(song)
    assert abc.startswith("X:1") and "K:Bb" in abc and "% Capo 3" in abc
    assert abc.count("|") >= 16
    assert f"M:{meter}" in abc


def test_abc_and_musicxml_carry_lyrics(song_cache):
    song = song_cache("C", "major")
    count = len([n for n in song["tracks"]["vocal"]["notes"] if n["start"] < 4 * bar_ticks(song["meter"])])
    out = editing.set_lyrics(song, "s-intro", "啦" * count)
    assert "w:" in export.to_abc(out)
    assert "<lyric>" in export.to_musicxml(out)
