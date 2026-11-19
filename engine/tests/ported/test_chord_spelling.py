"""Key-aware chord spelling, minor-key Basic lanes and playable dominants (regressions found 2026-11-01)."""
from __future__ import annotations

import contextlib
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fretcase_engine.chord_spelling import ChordSet, enharmonic_key, parse_key, respell_symbol, spell_chord_tones, spell_pc  # noqa: E402
from fretcase_engine.harmony_reasoning import build_candidate_bank  # noqa: E402
from fretcase_engine.music_representation import parse_abc_to_graph  # noqa: E402


@pytest.mark.parametrize(
    "tonic,mode,expected",
    [
        ("C", "major", ["C", "D", "E", "F", "G", "A", "B"]),
        ("F", "major", ["F", "G", "A", "Bb", "C", "D", "E"]),
        ("Bb", "major", ["Bb", "C", "D", "Eb", "F", "G", "A"]),
        ("D", "major", ["D", "E", "F#", "G", "A", "B", "C#"]),
        ("E", "major", ["E", "F#", "G#", "A", "B", "C#", "D#"]),
        ("A", "minor", ["A", "B", "C", "D", "E", "F", "G"]),
        ("G", "minor", ["G", "A", "Bb", "C", "D", "Eb", "F"]),
    ],
)
def test_scale_degrees_are_spelled_from_their_letters(tonic, mode, expected):
    from fretcase_engine.chord_spelling import NAME_TO_PC

    steps = [0, 2, 4, 5, 7, 9, 11] if mode == "major" else [0, 2, 3, 5, 7, 8, 10]
    assert [spell_pc((NAME_TO_PC[tonic] + s) % 12, tonic, mode) for s in steps] == expected


def test_chromatic_roots_use_degree_inflections():
    assert spell_pc(10, "C") == "Bb"          # bVII in C
    assert spell_pc(3, "G") == "Eb"           # bVI in G
    assert spell_pc(8, "A", "minor") == "G#"  # raised leading tone in A minor
    assert spell_pc(5, "F#") == "F"           # E# avoided for chord roots


def test_respell_and_enharmonic_identity():
    assert respell_symbol("A#maj7", "F") == "Bbmaj7"
    assert respell_symbol("Gbm7", "D") == "F#m7"
    assert respell_symbol("C/G", "C") == "C/G"
    assert enharmonic_key("A#m7") == enharmonic_key("Bbm7")
    known = ChordSet(["A#", "C", "Gbm7"])
    assert "Bb" in known and "F#m7" in known and "D" not in known
    assert parse_key("G minor") == ("G", "minor") and parse_key("F#m") == ("F#", "minor") and parse_key("Bb") == ("Bb", "major")


def test_chord_tones_are_spelled_in_thirds():
    assert spell_chord_tones("E7", [4, 8, 11, 2], "C") == {4: "E", 8: "G#", 11: "B", 2: "D"}
    assert spell_chord_tones("Bb", [10, 2, 5], "F") == {10: "Bb", 2: "D", 5: "F"}


def test_candidate_bank_in_flat_keys_uses_flats():
    symbols = {c.symbol for c in build_candidate_bank(tonic="F", mode="major", style="jazz", render_mode="sounding")}
    assert "Bb" in symbols and "A#" not in symbols
    assert not any("#" in s for s in symbols)
    d_major = {c.symbol for c in build_candidate_bank(tonic="D", mode="major", style="jazz", render_mode="sounding")}
    assert "F#m7" in d_major and not any(s.startswith("Gb") for s in d_major)


def test_parsed_chord_voice_is_spelled_for_the_key():
    abc = "X:1\nM:4/4\nL:1/8\nK:F\nV:1\nF8 | A8 |]\nV:2\n[F A c]8 | [B, D F]8 |]\n"
    graph = parse_abc_to_graph(abc)
    assert [event.symbol for event in graph.harmony] == ["F", "Bb"]








def test_substitution_reasons_are_grouped_per_chord():
    from fretcase_engine.candidate_summary import _substitution_reasons

    lines = _substitution_reasons([
        {"bar": 6, "from": "F", "to": "Dm", "reason": "no_playable_shape"},
        {"bar": 10, "from": "F", "to": "Dm", "reason": "no_playable_shape"},
        {"bar": 4, "from": "B", "to": "B7", "reason": "playable_dominant"},
        {"bar": 3, "from": "A", "to": "E", "reason": "avoid_repeat"},
    ])
    assert lines == [
        "F was replaced by Dm (bars 6 and 10) because no shape for F fits your current level yet.",
        "B7 instead of B (bar 4): B needs a barre; B7 is the shape beginners learn first.",
    ]


def test_capo_suggestion_only_for_barre_keys():
    from fretcase_engine.candidate_summary import capo_suggestion

    assert capo_suggestion("Bb")["capo"] == 3 and capo_suggestion("Bb")["shape_key"] == "G"
    assert capo_suggestion("F#m")["capo"] == 2 and capo_suggestion("F#m")["shape_key"] == "Em"
    for key in ["C", "G", "D", "A", "E", "Am", "Em", "Dm"]:
        assert capo_suggestion(key) is None


def test_fallback_candidate_summary_is_marked_unverified():
    from fretcase_engine.candidate_summary import summarize_candidate

    abc = "X:1\nM:4/4\nL:1/8\nK:Bb\nV:1\nB8 |]\nV:2\n[B, D F]8 |]\n"
    summary = summarize_candidate({"style": "traditional", "bar_analysis": []}, abc, {"skill_level": "beginner", "known_chords": ["C", "G"]})
    assert summary["unverified"] is True and summary["playability"] is None
    assert summary["capo_suggestion"]["capo"] == 3
    assert any("capo on fret 3" in reason for reason in summary["reasons"])


def test_roman_numerals_follow_chord_quality_and_mark_borrowed_degrees():
    from fretcase_engine.harmony_reasoning import infer_roman

    assert [infer_roman(s, "A", "minor") for s in ["Am", "Bdim", "C", "Dm", "E", "E7", "Em", "F", "G"]] == \
        ["i", "ii°", "III", "iv", "V", "V7", "v", "VI", "VII"]
    assert [infer_roman(s, "C", "major") for s in ["C", "Dm7", "D7", "E7", "Bb", "Fm", "Bdim"]] == \
        ["I", "ii7", "II7", "III7", "bVII", "iv", "vii°"]
