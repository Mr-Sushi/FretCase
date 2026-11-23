"""Three clearly different candidates for one seed."""
import pytest

from conftest import NOW
from fretcase_engine import candidates as C
from fretcase_engine.editing import check_consistency
from fretcase_engine.song_model import Song

IDS = ["song-cand-0001", "song-cand-0002", "song-cand-0003"]


def make(seed, tod=None, avoid=()):
    return C.make_candidates(seed, IDS, "grp-test-0001", NOW, time_of_day=tod, avoid=avoid)


def test_three_valid_drafts_with_different_parts(seed_factory):
    results = make(seed_factory(), "dusk")
    songs = [s for s, _ in results]
    assert len(songs) == 3
    for index, song in enumerate(songs):
        Song.model_validate(song)
        assert check_consistency(song) == []
        c = song["candidate"]
        assert c["groupId"] == "grp-test-0001" and c["index"] == index and c["timeOfDay"] == "dusk" and c["chosen"] is False
        assert 0 < len(c["name"]) <= 24 and len(c["tags"]) <= 4 and all(len(t) <= 16 for t in c["tags"]) and 0 < len(c["why"]) <= 160
        assert set(c["parts"]) == {"vocal", "melody", "guitar", "bass", "drums", "ambience"}
        assert all(len(p["sound"]) <= 40 and 0 <= p["level"] <= 1 for p in c["parts"].values())
    sounds = [tuple(p["sound"] for p in s["candidate"]["parts"].values()) for s in songs]
    assert len(set(sounds)) == 3
    assert len({s["tracks"]["guitar"]["instrument"] for s in songs}) == 3
    assert len({s["controls"]["complexity"] for s in songs}) == 3  # harmony colour differs
    assert len({tuple(r["style"] for r in s["tracks"]["guitar"]["regions"]) + tuple(r["style"] for r in s["tracks"]["drums"]["regions"]) for s in songs}) == 3
    assert len({tuple(sec.get("lead") for sec in s["sections"]) for s in songs}) >= 2
    assert len({tuple(r["play"] for r in s["tracks"]["drums"]["regions"]) for s in songs}) >= 2


def test_no_jargon_in_the_texts(seed_factory):
    for song, _ in make(seed_factory()):
        text = " ".join([song["candidate"]["name"], song["candidate"]["why"], *song["candidate"]["tags"], *(p["sound"] for p in song["candidate"]["parts"].values())])
        for word in ("major", "minor", "arpeggio", "BPM", "chord", "key"):
            assert word not in text


def test_the_melody_is_shared(seed_factory):
    motif = [{"start": i * 480, "duration": 480, "pitch": p, "velocity": 90} for i, p in enumerate([67, 69, 71, 72])]
    songs = [s for s, _ in make(seed_factory(motif=motif))]
    chorus = lambda s: [(n["start"], n["pitch"]) for n in s["tracks"]["vocal"]["notes"] if s["sections"][2]["startBar"] * 1920 <= n["start"] < s["sections"][2]["endBar"] * 1920]  # noqa: E731
    assert chorus(songs[0]) == chorus(songs[1]) == chorus(songs[2]) != []


def test_time_of_day_changes_tempo_and_brightness(seed_factory):
    seed = seed_factory(tempo=90)
    day = [s for s, _ in make(seed, "day")]
    night = [s for s, _ in make(seed, "night")]
    assert min(s["tempo"] for s in day) > max(s["tempo"] for s in night)
    assert day[0]["controls"]["brightness"] > night[0]["controls"]["brightness"]
    assert {s["candidate"]["timeOfDay"] for s in day} == {"day"}
    assert "timeOfDay" not in make(seed)[0][0]["candidate"]


def test_a_new_round_avoids_the_previous_combinations(seed_factory):
    first = [s for s, _ in make(seed_factory(), "dusk")]
    second = [s for s, _ in make(seed_factory(), "dusk", avoid=[C.song_signature(s) for s in first])]
    assert not {C.song_signature(s) for s in first} & {C.song_signature(s) for s in second}
    assert len({C.song_signature(s) for s in second}) == 3


def test_deterministic(seed_factory):
    assert make(seed_factory(), "day")[0][0] == make(seed_factory(), "day")[0][0]


def test_lead_state_restores_with_set_lead(seed_factory):
    from fretcase_engine.editing import set_lead

    song, state = make(seed_factory())[0]
    chorus = song["sections"][2]
    assert chorus["lead"] in ("vocal", "melody", "guitar") and chorus["id"] in state
    restored, _ = set_lead(song, chorus["id"], None, state)
    assert "lead" not in restored["sections"][2]
