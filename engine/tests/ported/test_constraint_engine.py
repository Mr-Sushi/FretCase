import os
import sys
from unittest.mock import patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from fretcase_engine.constraint_engine import evaluate
from fretcase_engine.music_representation import ChordEvent, LeadSheetGraph, NoteEvent


def _build_graph() -> LeadSheetGraph:
    return LeadSheetGraph(
        meter="4/4",
        tempo=100,
        key={"tonic": "C", "mode": "major"},
        melody=[
            NoteEvent(pitch="C4", midi=60, start_beat=0.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="E4", midi=64, start_beat=1.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="G4", midi=67, start_beat=2.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="A4", midi=69, start_beat=3.0, duration_beats=1.0, bar=1),
        ],
        harmony=[
            ChordEvent(
                symbol="A7",
                notes=["A", "C#", "E", "G"],
                start_beat=0.0,
                duration_beats=4.0,
                bar=1,
            )
        ],
        rhythm={},
        ornament={},
    )


def test_h2_uses_melody_only_abc_input() -> None:
    graph = _build_graph()

    with patch(
        "fretcase_engine.constraint_engine.check_key_compliance",
        return_value={"compliant": True, "suggestions": ""},
    ) as mock_check:
        report = evaluate(graph)

    assert report.hard_violations == []
    assert mock_check.call_count == 1

    abc_arg = mock_check.call_args.args[0]
    assert "V:1" in abc_arg
    assert "V:2" in abc_arg
    assert "[A C# E G]" not in abc_arg


def test_h2_reports_melody_key_violation() -> None:
    graph = _build_graph()

    with patch(
        "fretcase_engine.constraint_engine.check_key_compliance",
        return_value={
            "compliant": False,
            "suggestions": "Found notes outside C: F#",
        },
    ):
        report = evaluate(graph)

    assert any(v.startswith("H2:") for v in report.hard_violations)
    assert "Found notes outside C: F#" in report.hard_violations[0]


def test_h3_playable_rejects_extended_or_accidental_chords() -> None:
    graph = LeadSheetGraph(
        meter="4/4",
        tempo=100,
        key={"tonic": "C", "mode": "major"},
        melody=[
            NoteEvent(pitch="C4", midi=60, start_beat=0.0, duration_beats=4.0, bar=1),
        ],
        harmony=[
            ChordEvent(
                symbol="C#maj7",
                notes=["C#", "F", "G#", "C"],
                start_beat=0.0,
                duration_beats=4.0,
                bar=1,
            )
        ],
        rhythm={},
        ornament={},
    )

    report = evaluate(graph, mode="playable")
    assert any(v.startswith("H3:") for v in report.hard_violations)


def test_h3_sounding_allows_extended_or_accidental_chords() -> None:
    graph = LeadSheetGraph(
        meter="4/4",
        tempo=100,
        key={"tonic": "C", "mode": "major"},
        melody=[
            NoteEvent(pitch="C4", midi=60, start_beat=0.0, duration_beats=4.0, bar=1),
        ],
        harmony=[
            ChordEvent(
                symbol="C#maj7",
                notes=["C#", "F", "G#", "C"],
                start_beat=0.0,
                duration_beats=4.0,
                bar=1,
            )
        ],
        rhythm={},
        ornament={},
    )

    report = evaluate(graph, mode="sounding")
    assert not any(v.startswith("H3:") for v in report.hard_violations)


def _two_bar_graph(first: str, second: str) -> LeadSheetGraph:
    return LeadSheetGraph(
        meter="4/4",
        tempo=100,
        key={"tonic": "C", "mode": "major"},
        melody=[
            NoteEvent(pitch="C4", midi=60, start_beat=0.0, duration_beats=4.0, bar=1),
            NoteEvent(pitch="D4", midi=62, start_beat=0.0, duration_beats=4.0, bar=2),
        ],
        harmony=[
            ChordEvent(symbol=first, notes=[], start_beat=0.0, duration_beats=4.0, bar=1),
            ChordEvent(symbol=second, notes=[], start_beat=0.0, duration_beats=4.0, bar=2),
        ],
        rhythm={},
        ornament={},
    )


def test_h4_open_chord_changes_are_not_hard_violations() -> None:
    # Am -> G and C -> G were flagged by the old 29-shape heuristic (cost 1.18 > 1.05); they are ordinary
    # beginner changes and must pass now that H4 is grounded in the shared voicing library.
    for first, second in [("Am", "G"), ("C", "G"), ("F", "G"), ("Dm", "Am"), ("G", "Em")]:
        report = evaluate(_two_bar_graph(first, second), mode="playable")
        assert not any(v.startswith("H4:") for v in report.hard_violations), (first, second, report.hard_violations)


def test_h4_flags_large_position_shift_between_played_voicings_in_playable_mode_only() -> None:
    graph = _two_bar_graph("C", "G")
    voicings = {1: [-1, 3, 2, 0, 1, 0], 2: [-1, -1, 9, 7, 8, 7]}  # open C (centre 2.0) -> G at the 7th position (centre 7.75)
    playable = evaluate(graph, mode="playable", voicings_by_bar=voicings)
    assert any(v.startswith("H4:") and "shift=" in v for v in playable.hard_violations)
    sounding = evaluate(graph, mode="sounding", voicings_by_bar=voicings)
    assert not any(v.startswith("H4:") for v in sounding.hard_violations)
    # the same chords with the ACS's open voicings are fine
    assert not any(v.startswith("H4:") for v in evaluate(graph, mode="playable", voicings_by_bar={1: [-1, 3, 2, 0, 1, 0], 2: [3, 2, 0, 0, 0, 3]}).hard_violations)


def test_h3_vocabulary_is_lane_aware() -> None:
    graph = _two_bar_graph("Cmaj7", "Am7")
    assert any(v.startswith("H3:") for v in evaluate(graph, mode="playable").hard_violations)
    assert any(v.startswith("H3:") for v in evaluate(graph, mode="playable", lane="basic").hard_violations)
    assert not any(v.startswith("H3:") for v in evaluate(graph, mode="playable", lane="explore").hard_violations)
    assert not any(v.startswith("H3:") for v in evaluate(graph, mode="playable", lane="pop").hard_violations)
    assert not any(v.startswith("H3:") for v in evaluate(graph, mode="playable", lane="color").hard_violations)
    # the explore lane still rejects extended jazz colours
    assert any(v.startswith("H3:") for v in evaluate(_two_bar_graph("Cmaj9", "Am11"), mode="playable", lane="explore").hard_violations)


def test_h5_no_warning_for_strong_chord_tones() -> None:
    graph = LeadSheetGraph(
        meter="4/4",
        tempo=100,
        key={"tonic": "C", "mode": "major"},
        melody=[
            NoteEvent(pitch="C4", midi=60, start_beat=0.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="E4", midi=64, start_beat=1.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="G4", midi=67, start_beat=2.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="C5", midi=72, start_beat=3.0, duration_beats=1.0, bar=1),
        ],
        harmony=[
            ChordEvent(
                symbol="C",
                notes=["C", "E", "G"],
                start_beat=0.0,
                duration_beats=4.0,
                bar=1,
            ),
        ],
        rhythm={},
        ornament={},
    )

    with patch(
        "fretcase_engine.constraint_engine.check_key_compliance",
        return_value={"compliant": True, "suggestions": ""},
    ):
        report = evaluate(graph, mode="playable")

    assert not any(v.startswith("H5:") for v in report.hard_violations)
    assert not any(v.startswith("H5:") for v in report.soft_warnings)


def test_h5_reports_strong_beat_mismatch() -> None:
    graph = LeadSheetGraph(
        meter="4/4",
        tempo=100,
        key={"tonic": "C", "mode": "major"},
        melody=[
            NoteEvent(pitch="F#4", midi=66, start_beat=0.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="A#4", midi=70, start_beat=1.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="D#5", midi=75, start_beat=2.0, duration_beats=1.0, bar=1),
            NoteEvent(pitch="F#5", midi=78, start_beat=3.0, duration_beats=1.0, bar=1),
        ],
        harmony=[
            ChordEvent(
                symbol="C",
                notes=["C", "E", "G"],
                start_beat=0.0,
                duration_beats=4.0,
                bar=1,
            ),
        ],
        rhythm={},
        ornament={},
    )

    with patch(
        "fretcase_engine.constraint_engine.check_key_compliance",
        return_value={"compliant": True, "suggestions": ""},
    ):
        report = evaluate(graph, mode="playable")

    assert any(v.startswith("H5:") for v in report.hard_violations)


def _keyed_graph(tonic: str, mode: str, chords) -> LeadSheetGraph:
    graph = _two_bar_graph(*chords)
    graph.key = {"tonic": tonic, "mode": mode}
    return graph


def test_h3_basic_vocabulary_follows_the_key_not_natural_note_roots() -> None:
    # F#m (iii in D, ii in E) and C#m (vi in E) are basic diatonic vocabulary; playability is the solver's job
    assert not any(v.startswith("H3:") for v in evaluate(_keyed_graph("D", "major", ("D", "F#m")), mode="playable", lane="basic").hard_violations)
    assert not any(v.startswith("H3:") for v in evaluate(_keyed_graph("E", "major", ("C#m", "F#m")), mode="playable", lane="basic").hard_violations)
    # the raised leading tone makes E (V) basic vocabulary in A minor
    assert not any(v.startswith("H3:") for v in evaluate(_keyed_graph("A", "minor", ("E", "Am")), mode="playable", lane="basic").hard_violations)
    # a chromatic root is still outside the basic lane
    assert any(v.startswith("H3:") for v in evaluate(_keyed_graph("C", "major", ("C#m", "C")), mode="playable", lane="basic").hard_violations)


def test_h3_explore_lane_admits_cautious_colours_on_any_root() -> None:
    assert not any(v.startswith("H3:") for v in evaluate(_keyed_graph("E", "major", ("F#m7", "Emaj7")), mode="playable", lane="explore").hard_violations)


def test_h1_accepts_the_meters_the_interface_offers() -> None:
    from fretcase_engine.offline_melody import generate_offline_melody
    from fretcase_engine.music_representation import parse_abc_to_graph

    for meter in ["4/4", "3/4", "6/8"]:
        abc = generate_offline_melody(key="G", meter=meter, tempo=90, length=16, variant=0, seed_text="h1", title="t")
        report = evaluate(parse_abc_to_graph(abc), mode="playable", lane="basic")
        assert not any(v.startswith("H1:") for v in report.hard_violations), (meter, report.hard_violations)
    graph = _two_bar_graph("C", "G")
    graph.meter = "5/4"
    assert any(v.startswith("H1: Meter 5/4 is not supported") for v in evaluate(graph, mode="playable").hard_violations)
