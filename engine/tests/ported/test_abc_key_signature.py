"""Standard ABC pitch semantics: key signature, accidentals lasting to the bar line, key-aware spelling."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fretcase_engine.music_representation import graph_to_abc, key_signature_alterations, midi_to_abc, parse_abc_to_graph, spell_bar_tokens  # noqa: E402


def _melody(key: str, body: str):
    return parse_abc_to_graph(f"X:1\nM:4/4\nL:1/8\nK:{key}\nV:1\n{body}\n").melody


def test_key_signature_applies_and_accidentals_last_until_the_bar_line() -> None:
    notes = _melody("G", "F2 G2 =F2 F2 | F8 |")
    assert [n.midi for n in notes] == [66, 67, 65, 65, 66]
    assert [n.midi for n in _melody("F", "B2 =B2 B2 c2 | B8 |")] == [70, 71, 71, 72, 70]
    assert [n.midi for n in _melody("D", "f2 c2 F2 ^c2 | c8 |")] == [78, 73, 66, 73, 73]
    # an accidental affects only the same octave
    assert [n.midi for n in _melody("C", "^F2 f2 F4 |")] == [66, 77, 66]
    assert [n.midi for n in _melody("Am", "G2 ^G2 G2 A2 | G8 |")] == [67, 68, 68, 69, 67]


def test_chord_voice_uses_the_key_signature() -> None:
    graph = parse_abc_to_graph("X:1\nM:4/4\nL:1/8\nK:G\nV:1\nG8 | G8 |\nV:2\n[D F A]8 | [=F A c]4 [F A c]4 |\n")
    assert [(c.symbol, c.notes) for c in graph.harmony] == [("D", ["D", "F#", "A"]), ("F", ["F", "A", "C"]), ("F", ["F", "A", "C"])]


@pytest.mark.parametrize("key,mode", [("C", "major"), ("G", "major"), ("D", "major"), ("A", "major"), ("E", "major"),
                                      ("F", "major"), ("Bb", "major"), ("Eb", "major"), ("A", "minor"), ("E", "minor"), ("D", "minor")])
def test_key_aware_spelling_round_trips_every_pitch(key: str, mode: str) -> None:
    signature = key_signature_alterations(key, mode)
    k = key + ("m" if mode == "minor" else "")
    midis = list(range(48, 85))
    # bar-aware speller: a whole chromatic run in ONE bar (accidentals carry over within the bar)
    body = " ".join(token[0] for token in spell_bar_tokens([[m] for m in midis], signature)) + " |"
    assert [n.midi for n in _melody(k, body)] == midis
    # descending as well (e.g. D natural after D flat needs a natural sign)
    body = " ".join(token[0] for token in spell_bar_tokens([[m] for m in reversed(midis)], signature)) + " |"
    assert [n.midi for n in _melody(k, body)] == list(reversed(midis))
    # explicit chord-voice speller: same pitches, and readable without applying the key signature
    explicit = spell_bar_tokens([[m] for m in midis], signature, explicit=True)
    assert [n.midi for n in _melody(k, " ".join(t[0] for t in explicit) + " |")] == midis
    naive = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    for (token,), midi in zip(explicit, midis):
        letter = token.lstrip("^_=")[0].upper()
        shift = token.count("^") - token.count("_")
        assert (naive[letter] + shift) % 12 == midi % 12, (token, midi)
    # stateless single-note writer: correct at the start of any bar
    body = " | ".join(midi_to_abc(m, signature) for m in midis) + " |"
    assert [n.midi for n in _melody(k, body)] == midis




def test_graph_export_preserves_pitches_in_sharp_and_flat_keys() -> None:
    for key in ("G", "F", "Em"):
        source = f"X:1\nM:4/4\nL:1/8\nK:{key}\nV:1\nF2 =F2 B2 _B2 | c8 |\nV:2\n[C E G]8 | [=F A c]8 |\n"
        graph = parse_abc_to_graph(source)
        again = parse_abc_to_graph(graph_to_abc(graph))
        assert [n.midi for n in again.melody] == [n.midi for n in graph.melody]
        assert [c.notes for c in again.harmony] == [c.notes for c in graph.harmony]


def test_offline_g_major_melody_is_heard_and_analysed_with_f_sharp() -> None:
    from fretcase_engine.offline_melody import generate_offline_melody

    abc = generate_offline_melody("G", "4/4", 80, 16, 0, "x")
    pcs = {n.midi % 12 for n in parse_abc_to_graph(abc).melody if n.midi is not None}
    assert 5 not in pcs  # no F natural: the key signature supplies F sharp
    assert pcs <= {7, 9, 11, 0, 2, 4, 6}
