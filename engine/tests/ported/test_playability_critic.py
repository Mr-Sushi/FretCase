import os
import sys

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SERVER_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fretcase_engine.playability_critic import estimate_transition_cost, evaluate_progression


def test_estimate_transition_cost_known_shapes() -> None:
    cost = estimate_transition_cost("C", "G")
    assert cost is not None
    assert cost >= 0.0


def test_evaluate_progression_reports_unknown() -> None:
    result = evaluate_progression(["C", "G", "C#maj7"])
    assert "C#maj7" in result["unknown_symbols"]
