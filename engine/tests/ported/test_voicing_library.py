"""Tests for the chords-db-backed voicing library, learner-aware ACS thresholds and the shared solver."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fretcase_engine.arrangement_solver import (  # noqa: E402
    build_acs_learner,
    build_default_constraint_spec,
    build_default_voicing_inventory,
    effective_voicing_difficulty,
    feasible_voicings_for_step,
    solve_fixed_progression,
    voicing_candidates_for_symbol,
    voicing_debug_summary,
    voicing_library_fingerprint,
    voicing_library_stats,
)


def test_library_is_loaded_and_much_larger_than_builtin_templates() -> None:
    stats = voicing_library_stats()
    assert stats["source"] == "json"
    # 881 validated chords-db positions + 16 curated shapes (dim7 / m7b5 / 7sus4 are not imported: the
    # runtime vocabulary cannot name them, and importing them labelled e.g. Am7b5 shapes as "Am7")
    assert stats["library_templates"] > 850
    assert stats["symbols"] > 200
    assert len(voicing_library_fingerprint()) == 12


def test_every_voicing_plays_exactly_its_chord() -> None:
    """Data integrity: no voicing may sound a non-chord tone or miss a defining tone of its label."""
    from fretcase_engine.harmony_reasoning import name_to_pc, parse_symbol_root_and_quality
    from fretcase_engine.voicing_check import CHORD_TYPE_TONES, voicing_tone_problems

    inventory = build_default_voicing_inventory()
    checked = 0
    problems = []
    for symbol, rows in inventory.items():
        root, quality = parse_symbol_root_and_quality(symbol)
        bass_pc = None
        if "/" in quality:
            quality, _, bass = quality.partition("/")
            bass_pc = name_to_pc(bass[:1].upper() + bass[1:])
        if quality not in CHORD_TYPE_TONES:
            continue
        for voicing in rows:
            checked += 1
            issue = voicing_tone_problems(voicing.frets, name_to_pc(root), quality, bass_pc)
            if issue:
                problems.append((symbol, voicing.frets, voicing.source, issue))
    assert checked > 850
    assert problems == []


def test_easiest_shapes_of_core_beginner_chords_are_the_real_chords() -> None:
    inventory = build_default_voicing_inventory()
    expected = {"E7": (0, 2, 0, 1, 0, 0), "B7": (-1, 2, 1, 2, 0, 2), "Am7": (-1, 0, 2, 0, 1, 0), "Bm7": (-1, 2, 0, 2, 0, 2)}
    for symbol, frets in expected.items():
        easiest = min(voicing_candidates_for_symbol(symbol, inventory=inventory), key=effective_voicing_difficulty)
        assert tuple(easiest.frets) == frets, (symbol, easiest.frets)


def test_every_symbol_has_shapes_with_fingers_and_absolute_frets() -> None:
    inventory = build_default_voicing_inventory()
    for symbol in ["C", "F", "Bm", "G7", "Dm7", "Fmaj7", "Bb", "F#m", "Asus2", "Cadd9"]:
        rows = voicing_candidates_for_symbol(symbol, inventory=inventory)
        assert rows, symbol
        for voicing in rows:
            assert len(voicing.frets) == 6
            assert all(f >= -1 for f in voicing.frets)
        summary = voicing_debug_summary(rows[0])
        assert set(summary) >= {"frets", "fingers", "barres", "base_fret", "difficulty", "beginner_friendly", "source"}


def test_difficulty_scale_orders_classic_shapes_sensibly() -> None:
    def easiest(symbol: str) -> float:
        return min(effective_voicing_difficulty(v) for v in voicing_candidates_for_symbol(symbol))

    assert easiest("Em") < easiest("C") < easiest("F")
    assert easiest("G") < easiest("Bm")
    assert easiest("Am") < easiest("B")


def test_beginner_basic_lane_admits_open_chords_but_not_barre_shapes() -> None:
    spec = build_default_constraint_spec("playable", "traditional", allow_barre=False, lane="basic")
    learner = build_acs_learner("beginner", "playable", lane="basic")
    for symbol, pc in [("C", 0), ("G", 7), ("D", 2), ("Em", 4), ("Am", 9), ("Dm", 2), ("G7", 7)]:
        feasible = feasible_voicings_for_step(symbol, pc, spec, learner)
        assert feasible, symbol
        assert all(not v.barre for v in feasible)
        assert all(v.inner_mutes == 0 for v in feasible)
    assert not feasible_voicings_for_step("B", 11, spec, learner)


def test_known_chords_raise_the_difficulty_allowance_for_that_chord_only() -> None:
    spec = build_default_constraint_spec("playable", "traditional", allow_barre=False, lane="basic")
    plain = build_acs_learner("beginner", "playable", lane="basic")
    knows_f = build_acs_learner("beginner", "playable", lane="basic", known_chords=["F"])
    assert not feasible_voicings_for_step("F", 5, spec, plain)
    assert feasible_voicings_for_step("F", 5, spec, knows_f)
    assert not feasible_voicings_for_step("Bm", 2, spec, knows_f)


def test_melody_containment_is_dropped_when_the_chord_lacks_the_melody_note() -> None:
    spec = build_default_constraint_spec("playable", "traditional", allow_barre=False, lane="basic")
    learner = build_acs_learner("beginner", "playable", lane="basic")
    # B over C major: C contains no B, so the containment rule is vacuous and must not block the chord
    assert feasible_voicings_for_step("C", 11, spec, learner)
    # F over C major: C has no F either
    assert feasible_voicings_for_step("C", 5, spec, learner)


def test_fixed_progression_solver_uses_strict_then_relaxed_ladder() -> None:
    spec = build_default_constraint_spec("playable", "traditional", allow_barre=False, lane="basic")
    learner = build_acs_learner("beginner", "playable", lane="basic")
    strict = solve_fixed_progression(["C", "Am", "Dm", "G"], [4, 9, 2, 7], spec, learner, lane="basic")
    assert strict["available"] and strict["relaxation"] == 0
    assert len(strict["voicing_seq"]) == 4
    relaxed = solve_fixed_progression(["C", "Am", "F", "G"], [4, 9, 0, 7], spec, learner, lane="basic")
    assert relaxed["available"] and relaxed["relaxation"] == 1
    assert relaxed["arrangement_score"] < relaxed["raw_arrangement_score"]
    impossible = solve_fixed_progression(["C", "B", "F#m", "G"], [4, 11, 6, 7], spec, learner, lane="basic")
    assert not impossible["available"]
    assert impossible["failed_bars"]


def test_stretch_relaxation_introduces_at_most_one_new_chord_type() -> None:
    spec = build_default_constraint_spec("playable", "traditional", allow_barre=False, lane="basic")
    learner = build_acs_learner("beginner", "playable", lane="basic")
    # D-Bm-G-A-D: Bm has no beginner shape under the relaxed cap but a simplified xx4432 shape within +0.10
    plain = solve_fixed_progression(["D", "Bm", "G", "A", "D"], [2, 11, 7, 9, 2], spec, learner, lane="basic")
    assert not plain["available"] and plain["failed_bars"] == [2]
    stretched = solve_fixed_progression(["D", "Bm", "G", "A", "D"], [2, 11, 7, 9, 2], spec, learner, lane="basic", allow_stretch=True)
    assert stretched["available"] and stretched["relaxation"] == 2 and stretched["stretch_symbols"] == ["Bm"]
    assert stretched["arrangement_score"] < stretched["raw_arrangement_score"] - 0.19  # two relaxation penalties
    assert list(stretched["voicing_seq"][1].frets) == [-1, -1, 4, 4, 3, 2]
    # two different unplayable chord types are not a single stretch: still unavailable
    two = solve_fixed_progression(["D", "Bm", "F#m", "A"], [2, 11, 6, 9], spec, learner, lane="basic", allow_stretch=True)
    assert not two["available"]
    # a barre chord in the basic lane is never admitted, even as a stretch chord
    barre = solve_fixed_progression(["F", "Dm", "Bb", "C", "F"], [5, 2, 10, 0, 5], spec, learner, lane="basic", allow_stretch=True)
    assert not barre["available"] and barre["failed_bars"] == [3]
