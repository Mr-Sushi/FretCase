"""Chord-change difficulty grounded in the shared voicing library.

One definition of "how hard is it to change from chord A to chord B" for every place that needs it
(learner fit, candidate summaries, practice plans, contrast suggestions).  It replaces the 29-shape
heuristic table in ``playability_critic`` for those uses: the shapes come from the same inventory the
Arrangement Constraint Solver (ACS) chooses from, and the metric is expressed in terms a teacher would
use with a beginner:

* ``shift``           how far the hand moves along the neck (difference of the fretted centres, in frets)
* ``anchors``         fretted positions (same string, same fret) that can stay down across the change
* ``comfort``         0..1, ``0.7 * (1 - min(shift, 5) / 5) + 0.3 * anchors / max(fretted notes)``

When the actual voicings chosen by ACS are known (``bar_analysis[j].voicing.frets``) they are used;
otherwise the easiest library shape of each symbol stands in.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from fretcase_engine.arrangement_solver import effective_voicing_difficulty, voicing_candidates_for_symbol, voicing_debug_summary
    from fretcase_engine.learner_model import normalize_chord_symbol
except ImportError:  # pragma: no cover - script-mode import
    from arrangement_solver import effective_voicing_difficulty, voicing_candidates_for_symbol, voicing_debug_summary  # type: ignore
    from learner_model import normalize_chord_symbol  # type: ignore

MAX_SHIFT = 5.0


@dataclass(frozen=True)
class ChangeMetrics:
    shift: float
    anchors: int
    fretted_from: int
    fretted_to: int
    comfort: float

    @property
    def anchor_ratio(self) -> float:
        return self.anchors / max(self.fretted_from, self.fretted_to, 1)

    def describe(self) -> str:
        """Plain-language description of the hand movement, e.g. "move about 2 frets; 1 finger stays down"."""
        if self.shift < 0.75:
            move = "the hand stays in the same position"
        elif self.shift < 1.75:
            move = "move about 1 fret"
        else:
            move = f"move about {round(self.shift)} frets"
        if self.anchors == 0:
            keep = "no finger can stay down"
        elif self.anchors == 1:
            keep = "1 finger stays down"
        else:
            keep = f"{self.anchors} fingers stay down"
        return f"{move}; {keep}"


def _fretted(frets: Sequence[int]) -> List[Tuple[int, int]]:
    return [(index, int(fret)) for index, fret in enumerate(frets) if int(fret) > 0]


def _centre(frets: Sequence[int]) -> float:
    pressed = [int(fret) for fret in frets if int(fret) > 0]
    return sum(pressed) / len(pressed) if pressed else 0.0


def change_metrics_from_frets(frets_from: Sequence[int], frets_to: Sequence[int]) -> ChangeMetrics:
    left = _fretted(frets_from)
    right = _fretted(frets_to)
    shift = abs(_centre(frets_to) - _centre(frets_from))
    anchors = len(set(left) & set(right))
    ratio = anchors / max(len(left), len(right), 1)
    comfort = 0.7 * (1.0 - min(shift, MAX_SHIFT) / MAX_SHIFT) + 0.3 * ratio
    return ChangeMetrics(shift=round(shift, 2), anchors=anchors, fretted_from=len(left), fretted_to=len(right), comfort=round(comfort, 3))


@lru_cache(maxsize=512)
def easiest_frets(symbol: str) -> Optional[Tuple[int, ...]]:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return None
    candidates = voicing_candidates_for_symbol(normalized)
    if not candidates:
        return None
    best = min(candidates, key=lambda v: (effective_voicing_difficulty(v), v.position_center))
    return tuple(int(f) for f in best.frets)


@lru_cache(maxsize=512)
def easiest_voicing_summary(symbol: str) -> Optional[Dict[str, object]]:
    normalized = normalize_chord_symbol(symbol)
    candidates = voicing_candidates_for_symbol(normalized) if normalized else []
    if not candidates:
        return None
    best = min(candidates, key=lambda v: (effective_voicing_difficulty(v), v.position_center))
    return voicing_debug_summary(best)


def change_metrics(
    from_symbol: str,
    to_symbol: str,
    frets_from: Optional[Sequence[int]] = None,
    frets_to: Optional[Sequence[int]] = None,
) -> Optional[ChangeMetrics]:
    left = list(frets_from) if frets_from and len(frets_from) == 6 else easiest_frets(from_symbol)
    right = list(frets_to) if frets_to and len(frets_to) == 6 else easiest_frets(to_symbol)
    if left is None or right is None:
        return None
    return change_metrics_from_frets(left, right)


def change_cost_points(from_symbol: str, to_symbol: str) -> Optional[int]:
    """Integer cost 0..3 used by the learner-fit score (0 = effortless, 3 = big jump with nothing kept)."""
    if normalize_chord_symbol(from_symbol) == normalize_chord_symbol(to_symbol):
        return 0
    metrics = change_metrics(from_symbol, to_symbol)
    if metrics is None:
        return None
    return int(round((1.0 - metrics.comfort) * 3.0))
