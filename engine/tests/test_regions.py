"""Regions (schema 2.0): generation reads them, and the region edit operations."""
import copy

import pytest

from conftest import NOW, make_seed
from fretcase_engine import editing
from fretcase_engine import regions as R
from fretcase_engine.common import CannotApply, bar_ticks, is_locked, section_window
from fretcase_engine.editing import check_consistency
from fretcase_engine.generate import apply_density, generate_song, reharmonise, another_take
from fretcase_engine.song_model import Song


def window(song, section_id):
    return section_window(song, next(s for s in song["sections"] if s["id"] == section_id))


def notes_in(song, track, section_id):
    s, e = window(song, section_id)
    return [n for n in song["tracks"][track]["notes"] if s <= n["start"] < e]


def valid(song):
    Song.model_validate(song)
    assert check_consistency(song) == []
    return song


def test_every_track_has_one_region_per_section(song_cache):
    song = valid(song_cache())
    for track in song["tracks"].values():
        assert [r["section"] for r in track["regions"]] == [s["id"] for s in song["sections"]]
        assert all(0 <= r["complexity"] <= 1 and 0 <= r["intensity"] <= 1 for r in track["regions"])
    assert song["master"] == {"volume": 0.8, "space": "room"}
    # nothing to play (no sound input) means play false on the ambience track
    assert not any(r["play"] for r in song["tracks"]["ambience"]["regions"])


def test_play_false_gives_no_notes_and_play_true_brings_them_back(song_cache):
    song = song_cache()
    off = valid(editing.set_region(song, "guitar", "s-verse", play=False))
    assert notes_in(off, "guitar", "s-verse") == [] and notes_in(off, "guitar", "s-chorus")
    assert {"track": "guitar", "section": "s-verse"} in off["locks"]
    on = valid(editing.set_region(off, "guitar", "s-verse", play=True))
    assert notes_in(on, "guitar", "s-verse")
    # the sung line survives the vocal being off and on again
    quiet = editing.set_region(song, "vocal", "s-chorus", play=False)
    assert notes_in(quiet, "vocal", "s-chorus") == []
    back = valid(editing.set_region(quiet, "vocal", "s-chorus", play=True))
    assert [(n["start"], n["pitch"]) for n in notes_in(back, "vocal", "s-chorus")] == [(n["start"], n["pitch"]) for n in notes_in(song, "vocal", "s-chorus")]


def test_complexity_adds_notes_and_intensity_raises_velocity(song_cache):
    song = song_cache()
    for track in ("guitar", "bass", "drums"):
        low = editing.set_region(song, track, "s-verse", complexity=0.05)
        high = editing.set_region(song, track, "s-verse", complexity=0.95)
        assert len(notes_in(high, track, "s-verse")) > len(notes_in(low, track, "s-verse")), track
    soft = editing.set_region(song, "guitar", "s-verse", intensity=0.0)
    loud = editing.set_region(song, "guitar", "s-verse", intensity=1.0)
    mean = lambda s: sum(n["velocity"] for n in notes_in(s, "guitar", "s-verse")) / len(notes_in(s, "guitar", "s-verse"))  # noqa: E731
    assert mean(loud) > mean(soft) * 1.5
    quiet, bold = (editing.set_region(song, "drums", "s-verse", intensity=v) for v in (0.0, 1.0))
    assert max(n["velocity"] for n in notes_in(bold, "drums", "s-verse")) > max(n["velocity"] for n in notes_in(quiet, "drums", "s-verse"))
    ornate = editing.set_region(song, "melody", "s-verse", complexity=0.95)
    assert len(notes_in(ornate, "melody", "s-verse")) > len(notes_in(song, "melody", "s-verse"))
    plain = editing.set_region(ornate, "melody", "s-verse", complexity=0.3)
    assert [(n["start"], n["pitch"]) for n in notes_in(plain, "melody", "s-verse")] == [(n["start"], n["pitch"]) for n in notes_in(song, "melody", "s-verse")]


def test_guitar_styles_map_to_rhythm_families(song_cache):
    song = song_cache()
    arp = valid(editing.set_region(song, "guitar", "s-verse", style="arpeggio", complexity=0.5))
    assert arp["tracks"]["guitar"]["rhythm"]["family"] in ("arpeggio", "strumming")
    firsts = lambda s: [n for n in notes_in(s, "guitar", "s-verse") if n["start"] == window(s, "s-verse")[0]]  # noqa: E731
    strum = editing.set_region(song, "guitar", "s-verse", style="strum")
    assert len(firsts(strum)) >= 4 > len(firsts(arp))  # a strum sounds the strings together, an arpeggio one by one
    sustain = editing.set_region(song, "guitar", "s-verse", style="sustain")
    chords = [c for c in song["harmony"] if window(song, "s-verse")[0] <= c["start"] < window(song, "s-verse")[1]]
    assert {n["start"] for n in notes_in(sustain, "guitar", "s-verse")} == {c["start"] for c in chords}
    muted = editing.set_region(song, "guitar", "s-verse", style="muted")
    assert max(n["duration"] for n in notes_in(muted, "guitar", "s-verse")) <= 120


def test_preset_level_comes_from_complexity_with_the_nearest_level_rule():
    from fretcase_engine.rhythm import presets_by_id

    waltz = generate_song(make_seed(meter="3/4"), "song-test-0007", NOW)
    for complexity in (0.1, 0.5, 0.9):  # 3/4 has only the start level
        out = editing.set_region(waltz, "guitar", "s-verse", complexity=complexity, style="strum")
        assert presets_by_id()[out["tracks"]["guitar"]["rhythm"]["presetId"]]["level"] == "start"
    four = generate_song(make_seed(), "song-test-0008", NOW)
    hard = editing.set_region(four, "guitar", "s-intro", complexity=0.95, style="strum")
    assert presets_by_id()[hard["tracks"]["guitar"]["rhythm"]["presetId"]]["level"] == "challenge"


def test_bass_and_drum_styles(song_cache):
    song = song_cache()
    walking = editing.set_region(song, "bass", "s-verse", style="walking")
    sustain = editing.set_region(song, "bass", "s-verse", style="sustain")
    assert len(notes_in(walking, "bass", "s-verse")) > len(notes_in(sustain, "bass", "s-verse")) == 4
    assert all(28 <= n["pitch"] <= 55 for out in (walking, sustain) for n in notes_in(out, "bass", "s-verse"))
    hand = editing.set_region(song, "drums", "s-verse", style="hand")
    assert {n["pitch"] for n in notes_in(hand, "drums", "s-verse")} <= {62, 63, 64}
    brush = editing.set_region(song, "drums", "s-verse", style="brush")
    assert max(n["velocity"] for n in notes_in(brush, "drums", "s-verse")) < max(n["velocity"] for n in notes_in(song, "drums", "s-verse"))


def test_melody_answer_style_comes_in_where_the_vocal_rests(song_cache):
    song = song_cache()
    answer = valid(editing.set_region(song, "melody", "s-verse", style="answer"))
    assert notes_in(answer, "melody", "s-verse") != notes_in(song, "melody", "s-verse")
    vocal_off = editing.set_region(answer, "vocal", "s-verse", play=False)  # with no vocal the melody plays the whole line
    assert [(n["start"], n["pitch"]) for n in notes_in(vocal_off, "melody", "s-verse")] == [(n["start"], n["pitch"]) for n in notes_in(song, "melody", "s-verse")]


def test_set_region_regenerates_even_when_locked_then_locks_that_region(song_cache):
    song = song_cache()
    song["locks"].append({"track": "guitar"})
    out = editing.set_region(song, "guitar", "s-chorus", complexity=0.9)
    assert notes_in(out, "guitar", "s-chorus") != notes_in(song, "guitar", "s-chorus")
    assert notes_in(out, "guitar", "s-verse") == notes_in(song, "guitar", "s-verse")
    assert is_locked(out, "guitar", "s-chorus")
    # a later knob turn keeps the user's choice in that region
    song2 = song_cache()
    edited = editing.set_region(song2, "drums", "s-chorus", complexity=0.95)
    song2["controls"]["density"] = 0.05
    edited["controls"]["density"] = 0.05
    turned = apply_density(edited)
    assert notes_in(turned, "drums", "s-chorus") == notes_in(edited, "drums", "s-chorus")
    assert notes_in(turned, "drums", "s-verse") != notes_in(edited, "drums", "s-verse")


def test_errors_for_unknown_track_section_and_style(song_cache):
    song = song_cache()
    for kwargs in ({"track": "drums", "section_id": "s-nope", "play": False}, {"track": "guitar", "section_id": "s-verse", "style": "walking"}, {"track": "guitar", "section_id": "s-verse"}):
        with pytest.raises(CannotApply):
            editing.set_region(song, **kwargs)


def test_density_sets_the_complexity_of_unlocked_guitar_bass_drums_regions(song_cache):
    song = song_cache()
    song["locks"].append({"track": "bass", "section": "s-verse"})
    song["controls"]["density"] = 0.9
    out = valid(apply_density(song))
    for track in ("guitar", "bass", "drums"):
        values = {r["section"]: r["complexity"] for r in out["tracks"][track]["regions"]}
        assert values["s-chorus"] == 0.9
    assert out["tracks"]["bass"]["regions"][1]["complexity"] == 0.5  # locked
    assert all(r["complexity"] == 0.5 for r in out["tracks"]["melody"]["regions"])


def test_copy_region_copies_complexity_intensity_style_but_not_play(song_cache):
    song = editing.set_region(song_cache(), "guitar", "s-outro", play=False)
    edited = editing.set_region(song, "guitar", "s-verse", complexity=0.9, intensity=0.8, style="arpeggio")
    out = valid(editing.copy_region(edited, "guitar", "s-verse"))
    regions = out["tracks"]["guitar"]["regions"]
    assert all((r["complexity"], r["intensity"], r["style"]) == (0.9, 0.8, "arpeggio") for r in regions)
    assert [r["play"] for r in regions] == [True, True, True, False]
    assert notes_in(out, "guitar", "s-outro") == []
    assert {"track": "guitar"} in out["locks"]


def test_set_lead_moves_presence_and_null_restores(song_cache):
    song = song_cache()
    before = copy.deepcopy(song["tracks"])
    led, state = editing.set_lead(song, "s-verse", "vocal", {})
    valid(led)
    verse = lambda s, t: next(r for r in s["tracks"][t]["regions"] if r["section"] == "s-verse")  # noqa: E731
    assert led["sections"][1]["lead"] == "vocal"
    assert verse(led, "vocal")["intensity"] == pytest.approx(verse(song, "vocal")["intensity"] + 0.15, abs=0.002)
    assert verse(led, "guitar")["intensity"] == pytest.approx(verse(song, "guitar")["intensity"] - 0.1, abs=0.002)
    assert verse(led, "melody")["style"] == "answer"  # the vocal leads: the melody answers
    again, state = editing.set_lead(led, "s-verse", "guitar", state)  # another lead first restores the old values
    assert verse(again, "melody")["style"] == "follow"
    assert verse(again, "guitar")["intensity"] == pytest.approx(verse(song, "guitar")["intensity"] + 0.15, abs=0.002)
    none, state = editing.set_lead(again, "s-verse", None, state)
    assert "lead" not in none["sections"][1] and none["tracks"] == before


def test_set_lead_leaves_locked_regions_alone(song_cache):
    song = song_cache()
    song["locks"].append({"track": "guitar", "section": "s-verse"})
    led, _ = editing.set_lead(song, "s-verse", "vocal", {})
    assert led["tracks"]["guitar"]["regions"][1] == song["tracks"]["guitar"]["regions"][1]
    with pytest.raises(CannotApply):
        editing.set_lead(song, "s-verse", "bass", {})


def test_shift_register_vocal_melody_guitar_bass(song_cache):
    song = song_cache()
    up = valid(editing.shift_register(song, "melody", "s-verse", "up"))
    old, new = notes_in(song, "melody", "s-verse"), notes_in(up, "melody", "s-verse")
    assert all(0 < b["pitch"] - a["pitch"] <= 2 for a, b in zip(old, new))
    assert notes_in(up, "melody", "s-chorus") == notes_in(song, "melody", "s-chorus")
    assert is_locked(up, "melody", "s-verse")
    down = editing.shift_register(song, "vocal", "s-verse", "down")
    assert all(0 < a["pitch"] - b["pitch"] <= 2 for a, b in zip(notes_in(song, "vocal", "s-verse"), notes_in(down, "vocal", "s-verse")))
    assert [n.get("lyric") for n in notes_in(down, "vocal", "s-verse")] == [n.get("lyric") for n in notes_in(song, "vocal", "s-verse")]
    low_bass = copy.deepcopy(song)
    for n in notes_in(low_bass, "bass", "s-chorus"):
        n["pitch"] = 40 if n["pitch"] % 2 else 43
    bass = editing.shift_register(low_bass, "bass", "s-chorus", "up")
    assert [b["pitch"] - a["pitch"] for a, b in zip(notes_in(low_bass, "bass", "s-chorus"), notes_in(bass, "bass", "s-chorus"))] == [12] * len(notes_in(low_bass, "bass", "s-chorus"))
    guitar = valid(editing.shift_register(song, "guitar", "s-verse", "up"))
    assert notes_in(guitar, "guitar", "s-verse") != notes_in(song, "guitar", "s-verse")
    assert [c["symbol"] for c in guitar["harmony"]] == [c["symbol"] for c in song["harmony"]]


def test_shift_register_refuses_drums_ambience_and_the_edge_of_the_range(song_cache):
    song = song_cache()
    for track in ("drums", "ambience"):
        with pytest.raises(CannotApply):
            editing.shift_register(song, track, "s-verse", "up")
    # keep pushing a section down until it runs out of range
    out = song
    with pytest.raises(CannotApply):
        for _ in range(40):
            out = editing.shift_register(out, "melody", "s-verse", "down")
    assert min(n["pitch"] for n in notes_in(out, "melody", "s-verse")) >= R.VOICED_RANGE[0]
    bass = song
    with pytest.raises(CannotApply):
        for _ in range(5):
            bass = editing.shift_register(bass, "bass", "s-verse", "up")
    assert max(n["pitch"] for n in notes_in(bass, "bass", "s-verse")) <= R.BASS_RANGE[1]
    off = editing.set_region(song, "melody", "s-verse", play=False)
    with pytest.raises(CannotApply):
        editing.shift_register(off, "melody", "s-verse", "up")


def test_revert_melody_without_a_motif_is_refused(song_cache):
    with pytest.raises(CannotApply) as caught:
        editing.revert_melody(song_cache(), "s-verse")
    assert caught.value.detail["reason"] == "no_motif"


def test_revert_melody_restores_the_hum_and_keeps_lyrics(seed_factory):
    motif = [{"start": i * 480, "duration": 480, "pitch": p, "velocity": 90} for i, p in enumerate([67, 69, 71, 72])]
    song = generate_song(seed_factory(motif=motif), "song-test-0009", NOW)
    song = editing.set_lyrics(song, "s-verse", "\n".join("海" * len(l) for l in editing.lyric_lines(editing.vocal_notes_in(song, song["sections"][1]))))
    shifted = editing.shift_register(editing.shift_register(song, "melody", "s-verse", "up"), "vocal", "s-verse", "up")
    assert notes_in(shifted, "melody", "s-verse") != notes_in(song, "melody", "s-verse")
    back = valid(editing.revert_melody(shifted, "s-verse"))
    assert [n["pitch"] for n in notes_in(back, "melody", "s-verse")] == [n["pitch"] for n in notes_in(song, "melody", "s-verse")]
    assert [n["pitch"] for n in notes_in(back, "vocal", "s-verse")] == [n["pitch"] for n in notes_in(song, "vocal", "s-verse")]
    assert {n["lyric"] for n in notes_in(back, "vocal", "s-verse")} == {"海"}


def test_set_master(song_cache):
    out = editing.set_master(song_cache(), volume=0.3, space="hall")
    assert out["master"] == {"volume": 0.3, "space": "hall"}
    with pytest.raises(CannotApply):
        editing.set_master(song_cache(), space="cathedral")
    with pytest.raises(CannotApply):
        editing.set_master(song_cache())


def test_set_sections_keeps_one_region_per_section(song_cache):
    out = editing.set_sections(song_cache(), [{"id": "s-first", "label": "一", "startBar": 0, "endBar": 6}, {"id": "s-second", "label": "二", "startBar": 6, "endBar": 16}])
    assert check_consistency(out) == []
    assert [r["section"] for r in out["tracks"]["guitar"]["regions"]] == ["s-first", "s-second"]


def test_another_take_and_reharmonise_keep_regions(song_cache):
    song = editing.set_region(song_cache(), "guitar", "s-verse", style="sustain")
    song["locks"].clear()
    out, _ = another_take(song, "s-verse", None, {})
    assert out["tracks"]["guitar"]["regions"] == song["tracks"]["guitar"]["regions"]
    assert valid(out)
    song["controls"]["complexity"] = 0.95
    assert valid(reharmonise(song))["tracks"]["guitar"]["regions"][1]["style"] == "sustain"
