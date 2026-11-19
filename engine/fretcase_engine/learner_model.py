from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fretcase_engine.music_representation import parse_abc_to_graph
try:
    from fretcase_engine.chord_spelling import ChordSet
    from fretcase_engine.playability_critic import estimate_transition_cost
except ImportError:
    from chord_spelling import ChordSet
    from playability_critic import estimate_transition_cost


@dataclass
class LearnerProfile:
    known_chords: List[str]
    prefer_simple_transitions: bool = True
    skill_level: str = "beginner"
    known_transitions: List[Tuple[str, str]] = None

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "LearnerProfile":
        if not payload:
            return cls(known_chords=[])
        known_chords_raw = payload.get("known_chords") or []
        known_chords = []
        for item in known_chords_raw:
            normalized = normalize_chord_symbol(str(item))
            if normalized and normalized not in known_chords:
                known_chords.append(normalized)

        known_transitions_raw = payload.get("known_transitions") or []
        known_transitions: List[Tuple[str, str]] = []
        for item in known_transitions_raw:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            left = normalize_chord_symbol(str(item[0]))
            right = normalize_chord_symbol(str(item[1]))
            if not left or not right:
                continue
            known_transitions.append((left, right))

        skill_level = str(payload.get("skill_level") or "beginner").strip().lower()
        if skill_level not in {"beginner", "early_intermediate"}:
            skill_level = "beginner"

        prefer_simple = bool(payload.get("prefer_simple_transitions", True))
        return cls(
            known_chords=known_chords,
            prefer_simple_transitions=prefer_simple,
            skill_level=skill_level,
            known_transitions=known_transitions,
        )


NOTE_PC: Dict[str, int] = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}

PC_NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

OPEN_LIKE_SYMBOLS = {
    "C", "Cm", "D", "Dm", "E", "Em", "F", "Fm", "G", "Gm", "A", "Am",
    "A7", "Am7", "B7", "Bdim", "C7", "Cmaj7", "D7", "Dm7", "E7", "Em7", "F7", "Fmaj7", "G7",
}


def normalize_chord_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().replace(" ", "")
    if not raw:
        return ""

    match = re.match(r"^([A-G](?:#|b)?)(.*)$", raw)
    if not match:
        return raw

    root, suffix = match.group(1), match.group(2)
    suffix_lower = suffix.lower()
    if suffix_lower in {"", "maj", "major"}:
        quality = ""
    elif suffix_lower in {"m", "min", "minor", "-"}:
        quality = "m"
    elif "dim" in suffix_lower or "°" in suffix_lower:
        quality = "dim"
    elif "aug" in suffix_lower or "+" in suffix_lower:
        quality = "aug"
    elif suffix_lower.startswith("maj7"):
        quality = "maj7"
    elif suffix_lower.startswith("m7"):
        quality = "m7"
    elif suffix_lower.startswith("m9"):
        quality = "m9"
    elif suffix_lower.startswith("7"):
        quality = "7"
    elif suffix_lower.startswith("9"):
        quality = "9"
    elif suffix_lower.startswith("11"):
        quality = "11"
    elif suffix_lower.startswith("13"):
        quality = "13"
    elif suffix_lower.startswith("sus2"):
        quality = "sus2"
    elif suffix_lower.startswith("sus4"):
        quality = "sus4"
    elif suffix_lower.startswith("add9"):
        quality = "add9"
    else:
        quality = suffix_lower
    return f"{root}{quality}"


def chord_quality_tier(symbol: str) -> int:
    normalized = normalize_chord_symbol(symbol)
    suffix_match = re.match(r"^([A-G](?:#|b)?)(.*)$", normalized)
    suffix = suffix_match.group(2) if suffix_match else normalized
    if suffix in {"", "m"}:
        return 0
    if suffix in {"7", "dim"}:
        return 1
    if suffix in {"maj7", "m7", "sus2", "sus4", "add9"}:
        return 2
    return 3


def chord_category(symbol: str) -> str:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return "barre"
    if normalized in OPEN_LIKE_SYMBOLS:
        return "open"
    if "#" in normalized or "b" in normalized:
        return "barre"
    if chord_quality_tier(normalized) >= 2:
        return "extension"
    root = normalized[0]
    if root == "B":
        return "barre"
    return "open"


def transition_cost(left: str, right: str) -> int:
    """0..3 cost of changing between two chords.

    Uses the voicing-library change model shared with the ACS (hand shift and fingers that stay down,
    see ``chord_changes``); the 29-shape heuristic of ``playability_critic`` and the category table are
    only fallbacks for symbols without a library shape."""
    try:
        from fretcase_engine.chord_changes import change_cost_points
    except ImportError:  # pragma: no cover - script-mode import
        from chord_changes import change_cost_points  # type: ignore
    grounded = change_cost_points(left, right)
    if grounded is not None:
        return grounded
    physical = estimate_transition_cost(normalize_chord_symbol(left), normalize_chord_symbol(right))
    if physical is not None:
        return int(round(physical * 2.0))
    level = {"open": 0, "extension": 1, "barre": 2}
    left_level = level.get(chord_category(left), 2)
    right_level = level.get(chord_category(right), 2)
    return max(left_level, right_level)


def extract_harmony_symbols(abc: str) -> List[str]:
    graph = parse_abc_to_graph(abc)
    events = sorted(graph.harmony, key=lambda item: (item.bar, item.start_beat))
    return [normalize_chord_symbol(item.symbol) for item in events if normalize_chord_symbol(item.symbol)]


def build_slot_symbol_map(abc: str) -> Dict[str, str]:
    graph = parse_abc_to_graph(abc)
    bars: Dict[int, List[Any]] = {}
    for event in graph.harmony:
        bars.setdefault(event.bar, []).append(event)

    slot_map: Dict[str, str] = {}
    for bar_number in sorted(bars.keys()):
        ordered = sorted(bars[bar_number], key=lambda item: item.start_beat)
        for index, event in enumerate(ordered):
            normalized = normalize_chord_symbol(event.symbol)
            if normalized:
                slot_map[f"{bar_number}:{index}"] = normalized
    return slot_map


def learner_penalty_for_progression(symbols: Sequence[str], profile: LearnerProfile) -> float:
    if not symbols:
        return 0.0

    known_set = ChordSet(profile.known_chords or [])  # enharmonic-insensitive: A#m is known if Bbm is
    unknown_count = 0
    complexity_sum = 0
    transition_sum = 0

    for idx, symbol in enumerate(symbols):
        normalized = normalize_chord_symbol(symbol)
        if not normalized:
            continue
        complexity_sum += chord_quality_tier(normalized)
        if known_set and normalized not in known_set:
            unknown_count += 1
        if idx > 0:
            transition_sum += transition_cost(symbols[idx - 1], normalized)

    unknown_penalty = unknown_count * 2.0
    complexity_penalty = complexity_sum * (1.4 if profile.skill_level == "beginner" else 0.9)
    transition_penalty = transition_sum * (1.1 if profile.prefer_simple_transitions else 0.6)
    return unknown_penalty + complexity_penalty + transition_penalty


def score_harmony_for_learner(
    abc: str,
    profile: LearnerProfile,
    constraint_report: Optional[Dict[str, Any]] = None,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """``symbols`` overrides the chords read from the ABC — for a capo arrangement the learner plays the
    shapes (G, C, D), not the sounding chords (Bb, Eb, F), so the shapes are what they know or not."""
    symbols = [normalize_chord_symbol(s) for s in symbols] if symbols else extract_harmony_symbols(abc)
    if not symbols:
        return {
            "score": 0,
            "known_coverage": 0.0,
            "unknown_unique": [],
            "transition_cost": 0,
            "reasons": ["No harmony symbols found."],
        }

    unique_symbols = sorted(set(symbols))
    known_set = ChordSet(profile.known_chords or [])  # enharmonic-insensitive: A#m is known if Bbm is
    unknown_unique = [ch for ch in unique_symbols if known_set and ch not in known_set]
    known_coverage = (
        1.0 if not known_set else (len(unique_symbols) - len(unknown_unique)) / max(1, len(unique_symbols))
    )

    transition_sum = sum(transition_cost(symbols[i], symbols[i + 1]) for i in range(len(symbols) - 1))
    avg_complexity = sum(chord_quality_tier(symbol) for symbol in symbols) / max(1, len(symbols))

    hard_count = len((constraint_report or {}).get("hard_violations", []) or [])
    soft_count = len((constraint_report or {}).get("soft_warnings", []) or [])
    score = 100.0
    score -= (1.0 - known_coverage) * 35.0
    score -= avg_complexity * (10.0 if profile.skill_level == "beginner" else 6.0)
    score -= transition_sum * (2.0 if profile.prefer_simple_transitions else 1.0)
    score -= hard_count * 8.0 + soft_count * 2.0
    score = max(0.0, min(100.0, score))

    reasons: List[str] = []
    if known_set:
        reasons.append(f"Known-chord coverage: {round(known_coverage * 100)}%.")
    if unknown_unique:
        reasons.append(f"Unfamiliar chords: {', '.join(unknown_unique[:4])}.")
    if profile.prefer_simple_transitions:
        reasons.append("Transition simplicity is prioritized for this learner.")
    if hard_count > 0:
        reasons.append(f"{hard_count} hard constraint issue(s) reduce learner fit.")

    if not reasons:
        reasons.append("Learner profile constraints are well satisfied.")

    return {
        "score": round(score, 1),
        "known_coverage": round(known_coverage, 3),
        "unknown_unique": unknown_unique,
        "transition_cost": transition_sum,
        "reasons": reasons,
    }


def rank_harmony_candidates_for_learner(
    candidates: List[str],
    candidate_styles: List[str],
    constraint_reports: List[Dict[str, Any]],
    learner_profile_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    profile = LearnerProfile.from_payload(learner_profile_payload)
    if not profile.known_chords and not profile.known_transitions:
        return {
            "candidates": candidates,
            "candidate_styles": candidate_styles,
            "constraint_reports": constraint_reports,
            "learner_scores": [],
            "ordered_indices": list(range(len(candidates))),
        }

    rows = []
    for idx, abc in enumerate(candidates):
        report = constraint_reports[idx] if idx < len(constraint_reports) else {}
        learner_fit = score_harmony_for_learner(abc, profile, report)
        hard_count = len((report or {}).get("hard_violations", []) or [])
        ranking_score = float(learner_fit["score"]) - hard_count * 3.0
        rows.append(
            {
                "index": idx,
                "ranking_score": ranking_score,
                "learner_fit": learner_fit,
            }
        )

    rows.sort(key=lambda row: row["ranking_score"], reverse=True)
    ordered_indices = [row["index"] for row in rows]
    return {
        "candidates": [candidates[i] for i in ordered_indices],
        "candidate_styles": [candidate_styles[i] for i in ordered_indices],
        "constraint_reports": [constraint_reports[i] for i in ordered_indices],
        "learner_scores": [rows[pos]["learner_fit"] for pos in range(len(rows))],
        "ordered_indices": ordered_indices,
    }


def build_diatonic_chords(key: str, mode: str = "playable") -> List[str]:
    tonic_match = re.match(r"^([A-G](?:#|b)?)(m?)$", (key or "C").strip())
    if not tonic_match:
        tonic = "C"
        is_minor = False
    else:
        tonic = tonic_match.group(1)
        is_minor = tonic_match.group(2) == "m"

    tonic_pc = NOTE_PC.get(tonic, 0)
    major_scale = [0, 2, 4, 5, 7, 9, 11]
    minor_scale = [0, 2, 3, 5, 7, 8, 10]
    intervals = minor_scale if is_minor else major_scale
    tones = [PC_NOTE[(tonic_pc + step) % 12] for step in intervals]

    if is_minor:
        chords = [
            f"{tones[0]}m",
            f"{tones[1]}dim",
            tones[2],
            f"{tones[3]}m",
            f"{tones[4]}m",
            tones[5],
            tones[6],
        ]
    else:
        chords = [
            tones[0],
            f"{tones[1]}m",
            f"{tones[2]}m",
            tones[3],
            tones[4],
            f"{tones[5]}m",
            f"{tones[6]}dim",
        ]

    if mode == "sounding":
        chords.extend([f"{tones[4]}7", f"{tones[0]}maj7", f"{tones[5]}m7"])

    deduped: List[str] = []
    for chord in chords:
        normalized = normalize_chord_symbol(chord)
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def first_n_unique(items: Iterable[str], n: int) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        normalized = normalize_chord_symbol(str(item))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
        if len(output) >= n:
            break
    return output
