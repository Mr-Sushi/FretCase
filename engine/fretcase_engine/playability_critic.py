from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ChordShape:
    symbol: str
    frets: Tuple[int, ...]
    difficulty: float


_SHAPES: Dict[str, ChordShape] = {
    "C": ChordShape("C", (-1, 3, 2, 0, 1, 0), 0.15),
    "Cmaj7": ChordShape("Cmaj7", (-1, 3, 2, 0, 0, 0), 0.22),
    "Cm": ChordShape("Cm", (-1, 3, 5, 5, 4, 3), 0.70),
    "D": ChordShape("D", (-1, -1, 0, 2, 3, 2), 0.20),
    "Dm": ChordShape("Dm", (-1, -1, 0, 2, 3, 1), 0.22),
    "Dm7": ChordShape("Dm7", (-1, -1, 0, 2, 1, 1), 0.28),
    "E": ChordShape("E", (0, 2, 2, 1, 0, 0), 0.18),
    "Em": ChordShape("Em", (0, 2, 2, 0, 0, 0), 0.12),
    "Em7": ChordShape("Em7", (0, 2, 0, 0, 0, 0), 0.16),
    "F": ChordShape("F", (1, 3, 3, 2, 1, 1), 0.82),
    "Fmaj7": ChordShape("Fmaj7", (-1, -1, 3, 2, 1, 0), 0.32),
    "Fm": ChordShape("Fm", (1, 3, 3, 1, 1, 1), 0.88),
    "G": ChordShape("G", (3, 2, 0, 0, 3, 3), 0.20),
    "Gm": ChordShape("Gm", (3, 5, 5, 3, 3, 3), 0.85),
    "A": ChordShape("A", (-1, 0, 2, 2, 2, 0), 0.20),
    "Am": ChordShape("Am", (-1, 0, 2, 2, 1, 0), 0.18),
    "Am7": ChordShape("Am7", (-1, 0, 2, 0, 1, 0), 0.18),
    "B": ChordShape("B", (-1, 2, 4, 4, 4, 2), 0.90),
    "Bdim": ChordShape("Bdim", (-1, 2, 3, 1, 3, -1), 0.48),
    "Bm": ChordShape("Bm", (-1, 2, 4, 4, 3, 2), 0.95),
    "A7": ChordShape("A7", (-1, 0, 2, 0, 2, 0), 0.20),
    "B7": ChordShape("B7", (-1, 2, 1, 2, 0, 2), 0.38),
    "C7": ChordShape("C7", (-1, 3, 2, 3, 1, 0), 0.30),
    "D7": ChordShape("D7", (-1, -1, 0, 2, 1, 2), 0.22),
    "E7": ChordShape("E7", (0, 2, 0, 1, 0, 0), 0.18),
    "F7": ChordShape("F7", (1, 3, 1, 2, 1, 1), 0.88),
    "G7": ChordShape("G7", (3, 2, 0, 0, 0, 1), 0.25),
}


def estimate_transition_cost(left_symbol: str, right_symbol: str) -> Optional[float]:
    left = _SHAPES.get(left_symbol)
    right = _SHAPES.get(right_symbol)
    if left is None or right is None:
        return None
    return _shape_distance(left, right)


def evaluate_progression(symbols: Sequence[str]) -> Dict[str, object]:
    edges = []
    unknown: List[str] = []
    total = 0.0
    counted = 0

    for symbol in symbols:
        if symbol not in _SHAPES and symbol not in unknown:
            unknown.append(symbol)

    for left, right in zip(symbols, symbols[1:]):
        cost = estimate_transition_cost(left, right)
        if cost is None:
            edges.append({"from": left, "to": right, "cost": None})
            continue
        edges.append({"from": left, "to": right, "cost": round(cost, 3)})
        total += cost
        counted += 1

    average = total / counted if counted > 0 else 0.0
    maximum = max((row["cost"] for row in edges if isinstance(row["cost"], (float, int))), default=0.0)
    return {
        "avg_transition_cost": round(float(average), 3),
        "max_transition_cost": round(float(maximum), 3),
        "unknown_symbols": unknown,
        "edges": edges,
    }


def _shape_distance(left: ChordShape, right: ChordShape) -> float:
    left_positions = _fretted_positions(left.frets)
    right_positions = _fretted_positions(right.frets)

    left_center = _centroid(left_positions)
    right_center = _centroid(right_positions)
    center_shift = abs(right_center - left_center)

    overlap = _fingering_overlap(left_positions, right_positions)
    string_change = _string_pattern_distance(left.frets, right.frets)
    diff_delta = abs(right.difficulty - left.difficulty)

    return (
        0.45 * center_shift
        + 0.35 * string_change
        + 0.25 * diff_delta
        + 0.4 * (1.0 - overlap)
    )


def _fretted_positions(frets: Tuple[int, ...]) -> List[Tuple[int, int]]:
    rows: List[Tuple[int, int]] = []
    for string_index, fret in enumerate(frets):
        if fret <= 0:
            continue
        rows.append((string_index, fret))
    return rows


def _centroid(positions: List[Tuple[int, int]]) -> float:
    if not positions:
        return 0.0
    return sum(fret for _, fret in positions) / len(positions)


def _fingering_overlap(left: List[Tuple[int, int]], right: List[Tuple[int, int]]) -> float:
    if not left and not right:
        return 1.0
    left_set = set(left)
    right_set = set(right)
    inter = len(left_set & right_set)
    union = len(left_set | right_set)
    if union == 0:
        return 1.0
    return inter / union


def _string_pattern_distance(left: Tuple[int, ...], right: Tuple[int, ...]) -> float:
    active_left = [1 if fret > 0 else 0 for fret in left]
    active_right = [1 if fret > 0 else 0 for fret in right]
    delta = sum(abs(a - b) for a, b in zip(active_left, active_right))
    return delta / max(1, len(left))
