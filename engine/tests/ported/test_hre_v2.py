"""Tests for the HRE v2 chord-vocabulary feature and the lane-based benchmark contexts."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fretcase_engine.harmony_reasoning import (  # noqa: E402
    MelodyEvent,
    build_hre_contexts,
    derive_candidate_from_symbol,
    score_hre_breakdown,
    vocabulary_cap,
    vocabulary_fit,
)


def _ctx(style: str, cap: float):
    return build_hre_contexts(bar_count=1, tonic="C", mode="major", style=style, function_hints=[None], phrase_roles=["middle"], harmonic_cap=cap)[0]


def test_vocabulary_fit_penalises_seventh_chords_for_beginners_in_the_basic_lane_only() -> None:
    beginner_basic = _ctx("traditional", 0.35)
    intermediate_colour = _ctx("jazz", 0.58)
    c = derive_candidate_from_symbol("C", tonic="C", mode="major")
    cmaj7 = derive_candidate_from_symbol("Cmaj7", tonic="C", mode="major")
    dm7 = derive_candidate_from_symbol("Dm7", tonic="C", mode="major")
    bdim = derive_candidate_from_symbol("Bdim", tonic="C", mode="major")
    assert vocabulary_fit(c, beginner_basic) == 1.0
    assert 0.4 < vocabulary_fit(cmaj7, beginner_basic) < 0.8
    assert vocabulary_fit(dm7, beginner_basic) < vocabulary_fit(cmaj7, beginner_basic)
    assert vocabulary_fit(bdim, beginner_basic) < vocabulary_fit(dm7, beginner_basic)
    assert vocabulary_fit(cmaj7, intermediate_colour) == 1.0 and vocabulary_fit(dm7, intermediate_colour) == 1.0
    assert vocabulary_cap(beginner_basic) < vocabulary_cap(_ctx("pop", 0.35)) < vocabulary_cap(intermediate_colour)


def test_breakdown_exposes_vocabulary_fit_and_wv_defaults_to_zero() -> None:
    ctx = _ctx("traditional", 0.35)
    events = [MelodyEvent(pitch_class=11, beat_strength=1.0, duration_norm=0.5)]
    cmaj7 = derive_candidate_from_symbol("Cmaj7", tonic="C", mode="major")
    base = score_hre_breakdown(events, cmaj7, None, ctx)
    assert "vocabulary_fit" in base and base["vocabulary_fit"] < 1.0
    assert score_hre_breakdown(events, cmaj7, None, ctx, wv=0.0)["total"] == base["total"]
    weighted = score_hre_breakdown(events, cmaj7, None, ctx, wm=0.55, wl=0.2, wp=0.0, wf=0.0, wn=0.0, wa=0.05, wv=0.2)
    assert weighted["total"] < score_hre_breakdown(events, cmaj7, None, ctx, wm=0.75, wl=0.2, wp=0.0, wf=0.0, wn=0.0, wa=0.05)["total"]


