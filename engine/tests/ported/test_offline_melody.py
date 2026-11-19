"""Rule-based offline melody drafts: form, cadences, register and metre handling."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fretcase_engine.music_representation import parse_abc_to_graph  # noqa: E402
from fretcase_engine.offline_melody import generate_offline_melody, key_signature, parse_key  # noqa: E402

BEATS = {"4/4": 4.0, "3/4": 3.0, "6/8": 3.0}
TONIC_PC = {"C": 0, "G": 7, "D": 2, "A": 9, "E": 4, "F": 5, "Bb": 10, "Eb": 3,
            "Am": 9, "Em": 4, "Dm": 2, "Bm": 11, "F#m": 6, "Gm": 7, "Cm": 0}
# every key offered on the start screen (client/src/lib/startKeys.ts)
START_KEYS = ["C", "G", "D", "A", "E", "F", "Bb", "Eb", "Am", "Em", "Dm", "Bm", "F#m", "Gm", "Cm"]


@pytest.mark.parametrize("key", START_KEYS)
@pytest.mark.parametrize("meter", ["4/4", "3/4", "6/8"])
@pytest.mark.parametrize("variant", [0, 1, 2])
def test_drafts_are_complete_singable_and_end_on_the_tonic(key: str, meter: str, variant: int) -> None:
    abc = generate_offline_melody(key, meter, 80, 16, variant, "a happy song")
    graph = parse_abc_to_graph(abc)
    totals = {}
    for note in graph.melody:
        totals[note.bar] = totals.get(note.bar, 0.0) + note.duration_beats
    assert sorted(totals) == list(range(1, 17))
    assert all(abs(total - BEATS[meter]) < 1e-6 for total in totals.values())
    midis = [note.midi for note in graph.melody if note.midi is not None]
    assert 48 <= min(midis) and max(midis) <= 76  # beginner register
    assert max(abs(a - b) for a, b in zip(midis, midis[1:])) <= 9  # no leap larger than a major sixth
    last = graph.melody[-1]
    assert last.midi % 12 == TONIC_PC[key] and last.bar == 16  # authentic close on the tonic
    eighth_bar = [n for n in graph.melody if n.bar == 8]
    assert eighth_bar[-1].midi % 12 == TONIC_PC[key]  # first period closes on the tonic


def test_motif_returns_and_variants_differ() -> None:
    drafts = [generate_offline_melody("C", "4/4", 80, 16, v, "x") for v in range(3)]
    assert len({d.split("V:1")[1] for d in drafts}) == 3
    bars = [b.strip() for b in drafts[0].split("V:1")[1].replace("|]", "|").replace("\n", " ").split("|") if b.strip()]
    assert bars[0] == bars[4] == bars[12]  # opening motif returns in the answering phrases
    assert generate_offline_melody("C", "4/4", 80, 16, 0, "x") == drafts[0]  # deterministic


def test_key_parsing_and_signature_spelling() -> None:
    assert parse_key("Am") == ("A", True) and parse_key("G") == ("G", False) and parse_key("F#m") == ("F#", True)
    assert key_signature("D", False)["F"] == 1 and key_signature("D", False)["C"] == 1
    assert key_signature("F", False)["B"] == -1 and key_signature("E", True)["F"] == 1
    # A minor uses the raised leading tone (G#) over the dominant
    abc = generate_offline_melody("Am", "4/4", 80, 16, 0, "x")
    assert "^G" in abc or "^g" in abc or "G" not in abc.split("V:1")[1]
