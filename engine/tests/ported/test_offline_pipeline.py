"""End-to-end tests of the offline (no model key) pipeline, candidate sources, logging and persistence."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MELODY = """X:1
T:Test melody
M:4/4
L:1/8
Q:1/4=80
K:C
V:1
C2 D2 E2 G2 | G2 E2 D2 C2 | E2 F2 G2 E2 | D2 C2 B,2 C2 |
"""


def test_library_planner_payload_has_the_planner_shape() -> None:
    from fretcase_engine.candidate_sources import build_library_planner_payload, degree_to_symbol, resolve_harmony_source

    payload = build_library_planner_payload(MELODY, ["traditional", "pop", "jazz"], key_hint="C", learner_profile={"known_chords": ["C", "G"]})
    assert payload["source"] == "library"
    assert payload["primary_key"]["tonic"] == "C" and payload["primary_key"]["mode"] == "major"
    assert [plan["style"] for plan in payload["plans"]] == ["traditional", "pop", "jazz"]
    for plan in payload["plans"]:
        assert len(plan["bars"]) == 4
        for bar in plan["bars"]:
            assert bar["function_hint"] in {"T", "PD", "D", "COLOR"}
            assert 1 <= len(bar["candidate_chords"]) <= 4
    # the melody ends on C, so every lane should close on the tonic
    assert all(plan["bars"][-1]["candidate_chords"][0] in {"C", "Cmaj7"} for plan in payload["plans"])
    assert degree_to_symbol("5", "C", "major") == "G"
    assert degree_to_symbol("57", "A", "minor") == "E7"
    assert degree_to_symbol("6m7", "G", "major") == "Em7"
    assert resolve_harmony_source("llm", api_key_present=False) == "library"
    assert resolve_harmony_source("rule", api_key_present=False) == "rule"
    assert resolve_harmony_source(None, api_key_present=True) in {"llm", "library", "rule", "hybrid"}








