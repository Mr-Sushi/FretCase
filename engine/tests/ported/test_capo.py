"""Capo arrangements for barre-heavy keys: shapes for learning, sounding pitch for the score."""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fretcase_engine.capo import capo_for_key, capo_policy, shape_key_for, transpose_melody_abc, transpose_symbol  # noqa: E402
from fretcase_engine.chord_spelling import enharmonic_key  # noqa: E402
from fretcase_engine.music_representation import parse_abc_to_graph  # noqa: E402
from fretcase_engine.offline_melody import generate_offline_melody  # noqa: E402


def test_capo_positions_and_shape_keys():
    assert (capo_for_key("Bb")["fret"], capo_for_key("Bb")["shape_key"]) == (3, "G")
    assert (capo_for_key("F#m")["fret"], capo_for_key("F#m")["shape_key"]) == (2, "Em")
    assert (capo_for_key("Bm")["fret"], capo_for_key("Bm")["shape_key"]) == (2, "Am")
    for key in ["C", "G", "D", "A", "E", "Am", "Em", "Dm"]:
        assert capo_for_key(key) is None
    assert shape_key_for("Bb", 3) == ("G", "major")
    assert transpose_symbol("Em7", 3, "Bb", "major") == "Gm7"
    assert transpose_symbol("C/G", 3, "Eb", "major") == "Eb/Bb"
    assert capo_policy({"preferences": {"capo": "never"}}) == "never" and capo_policy(None) == "allow"


@pytest.mark.parametrize("key,meter", [("Bb", "4/4"), ("F#m", "3/4"), ("Eb", "6/8")])
def test_melody_transposition_keeps_rhythm_and_moves_pitch(key, meter):
    melody = generate_offline_melody(key=key, meter=meter, tempo=90, length=16, variant=1, seed_text="capo", title="t")
    capo = capo_for_key(key)
    shape = transpose_melody_abc(melody, -capo["fret"], capo["shape_key"])
    original = [(n.bar, round(n.start_beat, 4), round(n.duration_beats, 4), n.midi) for n in parse_abc_to_graph(melody).melody]
    moved = [(n.bar, round(n.start_beat, 4), round(n.duration_beats, 4), None if n.midi is None else n.midi + capo["fret"])
             for n in parse_abc_to_graph(shape).melody]
    assert original == moved
















# keys offered on the start screen (client/src/lib/startKeys.ts) and where the capo goes; the client mirror
# capoPositionForKey is tested against the same table in client/tests/startKeys.test.ts
START_KEY_CAPO = {
    "C": None, "G": None, "D": None, "A": None, "E": None, "F": (3, "D"), "Bb": (3, "G"), "Eb": (1, "D"),
    "Am": None, "Em": None, "Dm": None, "Bm": (2, "Am"), "F#m": (2, "Em"), "Gm": (3, "Em"), "Cm": (3, "Am"),
}


def test_start_screen_keys_have_the_expected_capo_positions():
    for key, expected in START_KEY_CAPO.items():
        capo = capo_for_key(key)
        assert (None if capo is None else (capo["fret"], capo["shape_key"])) == expected, key




