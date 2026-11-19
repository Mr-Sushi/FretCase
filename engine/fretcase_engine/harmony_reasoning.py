from __future__ import annotations

import os

from dataclasses import dataclass, field, replace
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from fretcase_engine.chord_spelling import respell_symbol, spell_pc
    from fretcase_engine.expert_runtime import load_runtime_expert_signals
    from fretcase_engine.learner_model import normalize_chord_symbol
    from fretcase_engine.music_representation import LeadSheetGraph, NoteEvent
except ImportError:
    from chord_spelling import respell_symbol, spell_pc
    from expert_runtime import load_runtime_expert_signals
    from learner_model import normalize_chord_symbol
    from music_representation import LeadSheetGraph, NoteEvent


PC_TO_NAME_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAME_TO_PC = {
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
    "E#": 5,
    "B#": 0,
    "Cb": 11,
    "Fb": 4,
}

VALID_FUNCTIONS = {"T", "PD", "D", "COLOR"}
VALID_PHRASE_ROLES = {
    "start",
    "middle",
    "pre_cadential",
    "ending_authentic",
    "ending_half",
}

HRE_PRIOR_PATH = Path(__file__).resolve().parent / "data" / "hre_priors.json"
CHOCO_FREQ_PATH = Path(__file__).resolve().parent / "data" / "choco_freq.json"


def _load_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


HRE_PRIORS: Dict[str, object] = _load_json(HRE_PRIOR_PATH)
CHOCO_FREQ_PRIORS: Dict[str, object] = _load_json(CHOCO_FREQ_PATH)

STYLE_COMPLEXITY = {
    "traditional": 0.18,
    "pop": 0.34,
    "jazz": 0.58,
}

PHRASE_TARGETS = {
    "start": {"T"},
    "middle": {"T", "PD"},
    "pre_cadential": {"PD", "D"},
    "ending_authentic": {"D", "T"},
    "ending_half": {"D"},
}

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def name_to_pc(note_name: str) -> int:
    normalized = (note_name or "C").strip()
    if not normalized:
        return 0
    normalized = normalized[0].upper() + normalized[1:]
    return NAME_TO_PC.get(normalized, NAME_TO_PC.get(normalized[0], 0))


def pc_to_name(pc: int) -> str:
    return PC_TO_NAME_SHARP[int(pc) % 12]


def midi_to_pc(midi: Optional[int]) -> Optional[int]:
    if midi is None:
        return None
    return int(midi) % 12


def pc_to_pretty_name(pc: int, tonic: Optional[str] = None, mode: Optional[str] = None) -> str:
    """Note name for learner-facing text; spelled for the key when the key is known (Bb in F major, not A#)."""
    if tonic:
        return spell_pc(pc, tonic, mode or "major")
    return pc_to_name(pc)


@dataclass
class MelodyEvent:
    pitch_class: int
    beat_strength: float
    duration_norm: float


@dataclass
class LessonSpec:
    target_complexity: float
    target_functions: Set[str]
    target_concepts: Set[str] = field(default_factory=set)


@dataclass
class LearnerProfile:
    harmonic_cap: float


@dataclass
class HREContext:
    key_scale_pcs: Set[int]
    phrase_role: str
    lesson: LessonSpec
    learner: LearnerProfile
    history_symbols: List[str] = field(default_factory=list)


@dataclass
class ChordCandidate:
    symbol: str
    function: str
    chord_tones: Set[int]
    complexity: float
    freq_norm: float
    concepts: Set[str] = field(default_factory=set)
    llm_rank: Optional[int] = None
    llm_same_function: bool = False


@dataclass
class HRECandidateEvaluation:
    chord: ChordCandidate
    roman: str
    function: str
    scores: Dict[str, float]
    total: float
    tier: str
    verified_reasons: List[str]


FUNCTION_TRANSITION = {
    ("T", "T"): 0.55,
    ("T", "PD"): 1.00,
    ("T", "D"): 0.75,
    ("T", "COLOR"): 0.60,
    ("PD", "T"): 0.40,
    ("PD", "PD"): 0.55,
    ("PD", "D"): 1.00,
    ("PD", "COLOR"): 0.65,
    ("D", "T"): 1.00,
    ("D", "PD"): 0.20,
    ("D", "D"): 0.60,
    ("D", "COLOR"): 0.45,
    ("COLOR", "T"): 0.60,
    ("COLOR", "PD"): 0.60,
    ("COLOR", "D"): 0.65,
    ("COLOR", "COLOR"): 0.50,
}

PHRASE_PREF = {
    "start": {"T": 1.00, "PD": 0.60, "D": 0.30, "COLOR": 0.45},
    "middle": {"T": 0.70, "PD": 0.80, "D": 0.60, "COLOR": 0.70},
    "pre_cadential": {"T": 0.30, "PD": 0.90, "D": 1.00, "COLOR": 0.65},
    "ending_authentic": {"T": 1.00, "PD": 0.40, "D": 0.90, "COLOR": 0.25},
    "ending_half": {"T": 0.25, "PD": 0.70, "D": 1.00, "COLOR": 0.35},
}

DEFAULT_ROMAN_FREQ_NORM = {
    "I": 1.0,
    "V": 0.92,
    "vi": 0.74,
    "IV": 0.78,
    "ii": 0.70,
    "V7": 0.65,
    "iii": 0.40,
    "vii°": 0.25,
    "i": 1.0,
    "iv": 0.78,
    "VI": 0.65,
    "VII": 0.58,
}

TIER_LABELS = {
    "safe": "basic",
    "stretch": "explore",
    "creative": "color",
}


def beat_strength_for_offset(start_beat: float) -> float:
    rounded = int(round(start_beat))
    if abs(start_beat - rounded) > 1e-3:
        return 0.35
    if rounded == 0:
        return 1.0
    if rounded == 2:
        return 0.82
    if rounded in {1, 3}:
        return 0.62
    return 0.4


def build_melody_events_by_bar(graph: LeadSheetGraph) -> List[List[MelodyEvent]]:
    if not graph.melody:
        return []

    bars: Dict[int, List[NoteEvent]] = {}
    for note in graph.melody:
        if note.is_rest or note.midi is None:
            continue
        bars.setdefault(int(note.bar), []).append(note)

    if not bars:
        return []

    bar_count = max(bars.keys())
    output: List[List[MelodyEvent]] = []
    for bar_number in range(1, bar_count + 1):
        notes = bars.get(bar_number, [])
        max_duration = max((float(note.duration_beats) for note in notes), default=1.0)
        row: List[MelodyEvent] = []
        for note in sorted(notes, key=lambda item: (item.start_beat, item.duration_beats)):
            pc = midi_to_pc(note.midi)
            if pc is None:
                continue
            row.append(
                MelodyEvent(
                    pitch_class=pc,
                    beat_strength=beat_strength_for_offset(float(note.start_beat)),
                    duration_norm=clamp01(float(note.duration_beats) / max(max_duration, 1e-8)),
                )
            )
        output.append(row)
    return output


def anchor_pitch_classes(events_by_bar: Sequence[Sequence[MelodyEvent]]) -> List[int]:
    anchors: List[int] = []
    for events in events_by_bar:
        if not events:
            anchors.append(0)
            continue
        weighted = sorted(
            events,
            key=lambda item: (0.65 * item.beat_strength + 0.35 * item.duration_norm, item.pitch_class),
            reverse=True,
        )
        anchors.append(int(weighted[0].pitch_class))
    return anchors


def infer_phrase_roles(
    bar_count: int,
    planner_roles: Optional[Sequence[Optional[str]]] = None,
) -> List[str]:
    roles: List[str] = []
    for idx in range(bar_count):
        proposed = None
        if planner_roles and idx < len(planner_roles):
            raw = (planner_roles[idx] or "").strip().lower()
            if raw in VALID_PHRASE_ROLES:
                proposed = raw
        if proposed:
            roles.append(proposed)
            continue
        bar_number = idx + 1
        phrase_start = ((bar_number - 1) // 4) * 4 + 1
        phrase_end = min(phrase_start + 3, bar_count)
        phrase_length = max(1, phrase_end - phrase_start + 1)
        phrase_position = bar_number - phrase_start + 1
        is_final_phrase = phrase_end == bar_count

        if phrase_position == 1:
            roles.append("start")
        elif phrase_position == phrase_length:
            roles.append("ending_authentic" if is_final_phrase else "ending_half")
        elif phrase_length >= 3 and phrase_position == phrase_length - 1:
            roles.append("pre_cadential")
        else:
            roles.append("middle")
    return roles


def key_scale_pcs(tonic: str, mode: str) -> Set[int]:
    tonic_pc = name_to_pc(tonic)
    intervals = [0, 2, 3, 5, 7, 8, 10] if str(mode).lower() == "minor" else [0, 2, 4, 5, 7, 9, 11]
    return {(tonic_pc + interval) % 12 for interval in intervals}


def parse_symbol_root_and_quality(symbol: str) -> Tuple[str, str]:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return "C", ""
    root = normalized[0]
    suffix_start = 1
    if len(normalized) > 1 and normalized[1] in {"#", "b"}:
        root = normalized[:2]
        suffix_start = 2
    return root, normalized[suffix_start:]


def chord_quality_intervals(quality: str) -> Tuple[List[int], float, Set[str]]:
    lowered = (quality or "").lower()
    if lowered in {"", "maj"}:
        return [0, 4, 7], 0.16, set()
    if lowered == "m":
        return [0, 3, 7], 0.20, {"minor_color"}
    if lowered == "dim":
        return [0, 3, 6], 0.48, {"dominant_tension"}
    if lowered == "aug":
        return [0, 4, 8], 0.62, {"color"}
    if lowered == "7":
        return [0, 4, 7, 10], 0.36, {"seventh_color", "dominant_tension"}
    if lowered == "maj7":
        return [0, 4, 7, 11], 0.42, {"seventh_color"}
    if lowered == "m7":
        return [0, 3, 7, 10], 0.44, {"seventh_color", "minor_color"}
    if lowered == "m9":
        return [0, 3, 7, 10, 2], 0.60, {"seventh_color", "color"}
    return [0, 4, 7], 0.28, {"color"}


def chord_symbol_to_tones(symbol: str) -> Tuple[Set[int], float, Set[str]]:
    root, quality = parse_symbol_root_and_quality(symbol)
    root_pc = name_to_pc(root)
    intervals, complexity, concepts = chord_quality_intervals(quality)
    return {((root_pc + interval) % 12) for interval in intervals}, complexity, concepts


def infer_function(symbol: str, tonic: str, mode: str) -> str:
    root, quality = parse_symbol_root_and_quality(symbol)
    interval = (name_to_pc(root) - name_to_pc(tonic)) % 12
    symbol_lower = normalize_chord_symbol(symbol).lower()
    resolved_mode = str(mode).lower()

    if resolved_mode == "minor":
        if interval in {0, 3}:
            return "T"
        if interval in {2, 5, 8}:
            return "PD"
        if interval in {7, 10, 11}:
            return "D"
    else:
        if interval in {0, 4, 9}:
            return "T"
        if interval in {2, 5}:
            return "PD"
        if interval in {7, 11}:
            return "D"

    if "dim" in symbol_lower or "°" in symbol_lower:
        return "D"
    if quality in {"7"}:
        return "D"
    return "COLOR"


# Scale-degree numerals by interval above the tonic; the case is set by the chord quality (upper = major,
# lower = minor / diminished), so E major in A minor is V (not v) and D major in C major is II (V/V).
ROMAN_DEGREE_MAJOR = {0: "I", 1: "bII", 2: "II", 3: "bIII", 4: "III", 5: "IV", 6: "#IV", 7: "V", 8: "bVI", 9: "VI", 10: "bVII", 11: "VII"}
ROMAN_DEGREE_MINOR = {0: "I", 1: "bII", 2: "II", 3: "III", 4: "#III", 5: "IV", 6: "#IV", 7: "V", 8: "VI", 9: "#VI", 10: "VII", 11: "VII"}
_MINOR_LIKE_QUALITIES = {"m", "m7", "m9", "m6", "m11", "dim", "m7b5", "mmaj7"}
_ROMAN_SUFFIX = {"dim": "°", "7": "7", "maj7": "maj7", "m7": "7", "m9": "9", "aug": "+", "9": "9", "6": "6", "m6": "6",
                 "sus2": "sus2", "sus4": "sus4", "add9": "add9", "11": "11", "m11": "11", "13": "13", "mmaj7": "(maj7)"}


def infer_roman(symbol: str, tonic: str, mode: str) -> str:
    root, quality = parse_symbol_root_and_quality(symbol)
    interval = (name_to_pc(root) - name_to_pc(tonic)) % 12
    table = ROMAN_DEGREE_MINOR if str(mode).lower() == "minor" else ROMAN_DEGREE_MAJOR
    base = table.get(interval, "?")
    lowered = (quality or "").lower()
    if lowered in _MINOR_LIKE_QUALITIES:
        base = "".join(ch.lower() if ch in "IV" else ch for ch in base)
    return f"{base}{_ROMAN_SUFFIX.get(lowered, '')}"


def derive_candidate_from_symbol(
    symbol: str,
    tonic: str,
    mode: str,
    freq_norm: float = 0.42,
    llm_rank: Optional[int] = None,
    llm_same_function: bool = False,
) -> ChordCandidate:
    tones, complexity, concepts = chord_symbol_to_tones(symbol)
    normalized = normalize_chord_symbol(symbol)
    function = infer_function(normalized, tonic=tonic, mode=mode)
    if function == "T" and normalized.endswith("m") and infer_roman(normalized, tonic, mode).lower() in {"vi", "iii", "vi7", "iii7"}:
        concepts = set(concepts) | {"tonic_substitute"}
    return ChordCandidate(
        symbol=normalized,
        function=function,
        chord_tones=tones,
        complexity=complexity,
        freq_norm=clamp01(freq_norm),
        concepts=set(concepts),
        llm_rank=llm_rank,
        llm_same_function=llm_same_function,
    )


def _parse_runtime_key_signature(text: Any) -> Tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "C", "major"
    lowered = raw.lower()
    mode = "minor" if ("minor" in lowered or lowered.endswith("m")) else "major"
    match = re.search(r"([A-Ga-g][#b]?)", raw)
    tonic = match.group(1).capitalize() if match else "C"
    return tonic, mode


_EXPERT_PRIOR_EXCLUDED_CASES: Set[str] = set()
_EXPERT_PRIOR_CACHE: Dict[Tuple[str, ...], Dict[str, Dict[str, float]]] = {}


def set_expert_prior_excluded_cases(case_ids: Optional[Sequence[str]]) -> None:
    """Exclude canonical cases from the expert phrase priors (used for leave-cases-out calibration)."""
    global _EXPERT_PRIOR_EXCLUDED_CASES
    _EXPERT_PRIOR_EXCLUDED_CASES = {str(item) for item in (case_ids or [])}


def expert_phrase_priors_enabled() -> bool:
    return os.getenv("FRETSTUDIO_EXPERT_PHRASE_PRIORS", "on").strip().lower() not in {"off", "0", "false", "no"}


def expert_phrase_function_priors() -> Dict[str, Dict[str, float]]:
    if not expert_phrase_priors_enabled():
        return {}
    cache_key = tuple(sorted(_EXPERT_PRIOR_EXCLUDED_CASES))
    cached = _EXPERT_PRIOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    priors = _compute_expert_phrase_function_priors()
    _EXPERT_PRIOR_CACHE[cache_key] = priors
    return priors


def _compute_expert_phrase_function_priors() -> Dict[str, Dict[str, float]]:
    signals = load_runtime_expert_signals()
    rows = signals.get("canonical_gold") if isinstance(signals, dict) else []
    counts: Dict[str, Dict[str, float]] = {}
    for row in rows if isinstance(rows, list) else []:
        if _EXPERT_PRIOR_EXCLUDED_CASES and str(row.get("case_id") or "") in _EXPERT_PRIOR_EXCLUDED_CASES:
            continue
        phrase_role = str(row.get("phrase_role") or "").strip().lower()
        symbol = normalize_chord_symbol(str(row.get("majority_top1_chord") or ""))
        if phrase_role not in VALID_PHRASE_ROLES or not symbol:
            continue
        tonic, mode = _parse_runtime_key_signature(row.get("key"))
        try:
            candidate = derive_candidate_from_symbol(symbol, tonic=tonic, mode=mode, freq_norm=0.5)
        except Exception:
            continue
        weight = max(float(row.get("n_valid") or 1), 1.0) * max(float(row.get("agreement_score") or 0.5), 0.1)
        counts.setdefault(phrase_role, {})
        counts[phrase_role][candidate.function] = counts[phrase_role].get(candidate.function, 0.0) + weight

    priors: Dict[str, Dict[str, float]] = {}
    for phrase_role, row in counts.items():
        total = sum(row.values())
        if total <= 0:
            continue
        priors[phrase_role] = {
            function: clamp01(score / total)
            for function, score in row.items()
        }
    return priors


def build_candidate_bank(
    tonic: str,
    mode: str,
    style: str,
    render_mode: str,
) -> List[ChordCandidate]:
    tonic_pc = name_to_pc(tonic)
    resolved_mode = str(mode).lower()
    style_name = (style or "traditional").strip().lower()
    sounding = str(render_mode).lower() == "sounding"

    specs: List[Tuple[int, str, str, float, float, Set[str]]] = []
    if resolved_mode == "minor":
        specs = [
            (0, "m", "T", 0.96, 0.16, set()),
            (3, "", "T", 0.72, 0.22, {"tonic_substitute"}),
            (5, "m", "PD", 0.84, 0.22, set()),
            (8, "", "PD", 0.76, 0.24, set()),
            (7, "", "D", 0.90, 0.24, set()),
            (7, "7", "D", 0.62 if style_name == "traditional" else 0.80, 0.34, {"seventh_color", "dominant_tension"}),
        ]
        if style_name in {"pop", "jazz"} or sounding:
            specs.extend(
                [
                    (10, "", "D", 0.52, 0.28, set()),
                    (2, "dim", "PD", 0.42, 0.40, {"dominant_tension"}),
                ]
            )
        if sounding or style_name == "jazz":
            specs.extend(
                [
                    (0, "m7", "T", 0.64, 0.44, {"seventh_color"}),
                    (5, "m7", "PD", 0.55, 0.46, {"seventh_color"}),
                    (8, "maj7", "PD", 0.42, 0.44, {"seventh_color"}),
                ]
            )
    else:
        specs = [
            (0, "", "T", 0.98, 0.14, set()),
            (9, "m", "T", 0.88, 0.20, {"tonic_substitute"}),
            (5, "", "PD", 0.86, 0.20, set()),
            (2, "m", "PD", 0.84, 0.22, set()),
            (7, "", "D", 0.94, 0.20, set()),
            (7, "7", "D", 0.68 if style_name == "traditional" else 0.90, 0.34, {"seventh_color", "dominant_tension"}),
        ]
        if style_name in {"pop", "jazz"} or sounding:
            specs.extend(
                [
                    (0, "maj7", "T", 0.44 if style_name == "pop" else 0.62, 0.40, {"seventh_color"}),
                    (9, "m7", "T", 0.48 if style_name == "pop" else 0.58, 0.42, {"seventh_color", "tonic_substitute"}),
                    (2, "m7", "PD", 0.50 if style_name == "pop" else 0.60, 0.42, {"seventh_color"}),
                    (5, "maj7", "PD", 0.40 if style_name == "pop" else 0.52, 0.40, {"seventh_color"}),
                ]
            )
        if style_name == "jazz" or sounding:
            specs.extend(
                [
                    (4, "m", "T", 0.44, 0.26, {"tonic_substitute"}),
                    (4, "m7", "T", 0.40, 0.46, {"seventh_color", "tonic_substitute"}),
                    (11, "dim", "D", 0.42, 0.48, {"dominant_tension"}),
                ]
            )

    candidates: List[ChordCandidate] = []
    seen: Set[str] = set()
    for interval, suffix, function, freq_norm, complexity_hint, concepts in specs:
        symbol = f"{spell_pc(tonic_pc + interval, tonic, resolved_mode)}{suffix}"
        tones, _, base_concepts = chord_symbol_to_tones(symbol)
        normalized = normalize_chord_symbol(symbol)
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(
            ChordCandidate(
                symbol=normalized,
                function=function,
                chord_tones=tones,
                complexity=clamp01(complexity_hint),
                freq_norm=clamp01(freq_norm),
                concepts=set(base_concepts) | set(concepts),
            )
        )
    return candidates


def simplify_symbol_for_basic_harmony(symbol: str) -> str:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return ""
    root = normalized[0]
    suffix_start = 1
    if len(normalized) > 1 and normalized[1] in {"#", "b"}:
        root = normalized[:2]
        suffix_start = 2
    suffix = normalized[suffix_start:]
    if suffix in {"maj7", "7", "9", "6", "sus2", "sus4", "add9"}:
        return root
    if suffix in {"m7", "m9", "m6"}:
        return f"{root}m"
    return normalized


def build_lesson_spec(
    style: str,
    phrase_role: str,
    function_hint: Optional[str],
    harmonic_cap: float,
    user_goal: str = "",
) -> LessonSpec:
    style_name = (style or "traditional").strip().lower()
    target_complexity = STYLE_COMPLEXITY.get(style_name, 0.28)
    adjusted = 0.55 * target_complexity + 0.45 * clamp01(harmonic_cap)
    target_functions = set(PHRASE_TARGETS.get(phrase_role, {"T", "PD"}))
    normalized_hint = (function_hint or "").strip().upper()
    if normalized_hint in VALID_FUNCTIONS:
        target_functions = {normalized_hint}

    concepts: Set[str] = set()
    goal_text = (user_goal or "").strip().lower()
    if "predominant" in goal_text or "prepare" in goal_text:
        concepts.add("predominant_focus")
    if style_name == "pop":
        concepts.add("tonic_substitute")
        if clamp01(harmonic_cap) >= 0.35 or any(token in goal_text for token in {"color", "colour", "maj7", "m7", "seventh"}):
            concepts.add("seventh_color")
    if style_name == "jazz":
        concepts.add("seventh_color")

    return LessonSpec(
        target_complexity=clamp01(adjusted),
        target_functions=target_functions,
        target_concepts=concepts,
    )


def note_chord_compatibility(note_pc: int, chord: ChordCandidate, ctx: HREContext, strong: bool) -> float:
    if note_pc in chord.chord_tones:
        return 1.0
    if note_pc in ctx.key_scale_pcs:
        return 0.35 if strong else 0.65
    return 0.0


def melody_fit(events: List[MelodyEvent], chord: ChordCandidate, ctx: HREContext) -> float:
    if not events:
        return 0.0
    weighted_sum = 0.0
    weight_total = 0.0
    for event in events:
        weight = 0.6 * event.beat_strength + 0.4 * event.duration_norm
        compatibility = note_chord_compatibility(
            note_pc=event.pitch_class,
            chord=chord,
            ctx=ctx,
            strong=event.beat_strength >= 0.5,
        )
        weighted_sum += weight * compatibility
        weight_total += weight
    return clamp01(weighted_sum / max(weight_total, 1e-8))


def function_fit(prev_chord: Optional[ChordCandidate], chord: ChordCandidate) -> float:
    if prev_chord is None:
        return 0.7
    transition_prior = HRE_PRIORS.get("transition_prob", {})
    if isinstance(transition_prior, dict):
        key = f"{prev_chord.function}->{chord.function}"
        if key in transition_prior:
            try:
                return clamp01(float(transition_prior[key]))
            except (TypeError, ValueError):
                pass
    return FUNCTION_TRANSITION.get((prev_chord.function, chord.function), 0.4)


def phrase_fit(chord: ChordCandidate, ctx: HREContext) -> float:
    phrase_prior = HRE_PRIORS.get("phrase_pref", {})
    base_score: Optional[float] = None
    if isinstance(phrase_prior, dict):
        row = phrase_prior.get(ctx.phrase_role)
        if isinstance(row, dict) and chord.function in row:
            try:
                base_score = clamp01(float(row[chord.function]))
            except (TypeError, ValueError):
                base_score = None
    if base_score is None:
        base_score = PHRASE_PREF.get(ctx.phrase_role, PHRASE_PREF["middle"]).get(chord.function, 0.4)

    expert_priors = expert_phrase_function_priors()
    expert_score = expert_priors.get(ctx.phrase_role, {}).get(chord.function)
    if expert_score is None:
        return clamp01(base_score)
    return clamp01(0.75 * base_score + 0.25 * expert_score)


def lesson_fit(chord: ChordCandidate, ctx: HREContext) -> float:
    concept_bonus = 1.0 if (
        chord.function in ctx.lesson.target_functions
        or len(chord.concepts.intersection(ctx.lesson.target_concepts)) > 0
    ) else 0.6 if chord.function in {"T", "PD", "D"} else 0.2

    if ctx.phrase_role == "start" and not ctx.history_symbols:
        if "tonic_substitute" in chord.concepts:
            concept_bonus = min(concept_bonus, 0.45)
        elif chord.function == "T":
            concept_bonus = max(concept_bonus, 1.0)

    complexity_fit = 1.0 - abs(chord.complexity - ctx.lesson.target_complexity)
    capability_fit = 1.0 - max(0.0, chord.complexity - ctx.learner.harmonic_cap)
    score = 0.5 * concept_bonus + 0.3 * complexity_fit + 0.2 * capability_fit
    return clamp01(score)


VOCABULARY_SLOPE = 0.30


def vocabulary_cap(ctx: HREContext) -> float:
    """Chord-type complexity the learner is expected to handle in this lane.

    Midpoint between the lane's target complexity (traditional/basic 0.18, pop/explore 0.34,
    jazz/colour 0.58, blended with the learner cap by ``build_lesson_spec``) and the learner's
    harmonic cap (beginner 0.35, early-intermediate 0.58)."""
    return clamp01(0.5 * (ctx.lesson.target_complexity + ctx.learner.harmonic_cap))


def vocabulary_fit(chord: ChordCandidate, ctx: HREContext) -> float:
    """Pedagogical chord-vocabulary fit (HRE feature v2), independent of fretting difficulty.

    Error analysis on the expert ranking benchmark showed that seventh-chord progressions
    systematically outscored their triad counterparts for beginners in the basic lane: a four-note
    chord trivially covers more melody pitch classes (``melody_fit``) and several seventh shapes are
    physically *easier* than the corresponding open triads (Am7 x0101x vs Am x02210), while experts
    consistently preferred the triads for beginners.  ``lesson_fit`` penalised the complexity gap too
    weakly to express that preference.  This feature penalises chord types whose complexity exceeds the
    vocabulary cap of the learner/lane with slope ``1/VOCABULARY_SLOPE``; triads always score 1.0,
    seventh chords score ~0.5--0.8 for beginners in the basic lane and 1.0 for intermediates in the
    colour lane.  Its weight ``wv`` is fitted by ``scripts/calibrate_hre.py`` (0.0 reproduces v1)."""
    excess = max(0.0, chord.complexity - vocabulary_cap(ctx))
    return clamp01(1.0 - excess / VOCABULARY_SLOPE)


def novelty_fit(chord: ChordCandidate, history_symbols: List[str], window: int = 4) -> float:
    recent = history_symbols[-window:] if history_symbols else []
    if recent and recent[-1] == chord.symbol:
        return 0.0
    repeat_ratio = recent.count(chord.symbol) / max(len(recent), 1)
    rarity_source = chord.freq_norm
    roman = getattr(chord, "_roman_cache", None)
    roman_freq = None
    if isinstance(roman, str):
        priors = HRE_PRIORS.get("roman_freq_norm", {})
        if isinstance(priors, dict):
            roman_freq = priors.get(roman)
        if roman_freq is None and isinstance(CHOCO_FREQ_PRIORS, dict):
            roman_freq = CHOCO_FREQ_PRIORS.get(roman)
    if roman_freq is None and isinstance(roman, str):
        roman_freq = DEFAULT_ROMAN_FREQ_NORM.get(roman)
    if roman_freq is not None:
        try:
            rarity_source = clamp01(float(roman_freq))
        except (TypeError, ValueError):
            rarity_source = chord.freq_norm
    rarity = 1.0 - rarity_source
    diversity = 1.0 - repeat_ratio
    return clamp01(0.6 * rarity + 0.4 * diversity)


def llm_agreement(chord: ChordCandidate) -> float:
    if chord.llm_rank is not None:
        if chord.llm_rank == 1:
            return 1.0
        if chord.llm_rank <= 3:
            return 0.8
        if chord.llm_rank <= 5:
            return 0.6
    if chord.llm_same_function:
        return 0.4
    return 0.0


def score_hre_breakdown(
    events: List[MelodyEvent],
    chord: ChordCandidate,
    prev_chord: Optional[ChordCandidate],
    ctx: HREContext,
    wm: float = 0.30,
    wf: float = 0.25,
    wp: float = 0.20,
    wl: float = 0.15,
    wn: float = 0.05,
    wa: float = 0.05,
    wv: float = 0.0,
) -> Dict[str, float]:
    """Weighted HRE score with its feature breakdown.

    ``wv`` (chord-vocabulary fit) is the v2 feature; its default of 0.0 keeps weight files written
    before the feature existed behaving exactly as before."""
    melody_score = melody_fit(events, chord, ctx)
    function_score = function_fit(prev_chord, chord)
    phrase_score = phrase_fit(chord, ctx)
    lesson_score = lesson_fit(chord, ctx)
    novelty_score = novelty_fit(chord, ctx.history_symbols)
    llm_score = llm_agreement(chord)
    vocabulary_score = vocabulary_fit(chord, ctx)
    total = clamp01(
        wm * melody_score
        + wf * function_score
        + wp * phrase_score
        + wl * lesson_score
        + wn * novelty_score
        + wa * llm_score
        + wv * vocabulary_score
    )
    if prev_chord is not None and prev_chord.symbol == chord.symbol:
        total = clamp01(total - 0.18)
    return {
        "melody_fit": melody_score,
        "function_fit": function_score,
        "phrase_fit": phrase_score,
        "lesson_fit": lesson_score,
        "novelty": novelty_score,
        "llm_agreement": llm_score,
        "vocabulary_fit": vocabulary_score,
        "total": total,
    }


def score_hre(
    events: List[MelodyEvent],
    chord: ChordCandidate,
    prev_chord: Optional[ChordCandidate],
    ctx: HREContext,
) -> float:
    return score_hre_breakdown(events, chord, prev_chord, ctx)["total"]


def classify_tier(chord: ChordCandidate, ctx: HREContext, scores: Dict[str, float]) -> str:
    cap_gap = chord.complexity - ctx.learner.harmonic_cap
    if cap_gap <= 0.05 and scores["total"] >= 0.66:
        return "basic"
    if cap_gap <= 0.22 and scores["lesson_fit"] >= 0.6:
        return "explore"
    return "color"


def build_verified_reasons(
    events: Sequence[MelodyEvent],
    chord: ChordCandidate,
    ctx: HREContext,
    prev_chord: Optional[ChordCandidate],
    tonic: str,
    mode: str,
) -> List[str]:
    reasons: List[str] = []
    strong_events = [event for event in events if event.beat_strength >= 0.5]
    chord_tone_events = [event for event in strong_events if event.pitch_class in chord.chord_tones]
    if chord_tone_events:
        anchor = max(chord_tone_events, key=lambda item: (item.beat_strength, item.duration_norm))
        reasons.append(f"strong-beat melody note {pc_to_pretty_name(anchor.pitch_class, tonic, mode)} is a chord tone")

    roman = infer_roman(chord.symbol, tonic=tonic, mode=mode)
    function = chord.function
    if function in {"T", "PD", "D"} and roman != "?":
        label = {"T": "tonic", "PD": "predominant", "D": "dominant"}[function]
        reasons.append(f"{roman} functions as {label} in {tonic} {mode}")

    if prev_chord is not None:
        relation = FUNCTION_TRANSITION.get((prev_chord.function, chord.function), 0.0)
        if relation >= 0.95:
            reasons.append(f"{prev_chord.function} to {chord.function} is a strong functional continuation")

    if ctx.phrase_role == "pre_cadential" and chord.function in {"PD", "D"}:
        reasons.append(f"{chord.function} supports a pre-cadential phrase role")
    elif ctx.phrase_role in {"ending_authentic", "ending_half"} and chord.function in {"D", "T"}:
        reasons.append(f"{chord.function} matches the phrase-ending role")
    elif ctx.phrase_role == "start" and chord.function == "T":
        reasons.append("tonic function supports phrase opening stability")

    expert_score = expert_phrase_function_priors().get(ctx.phrase_role, {}).get(chord.function)
    if expert_score is not None and expert_score >= 0.55:
        reasons.append("expert annotations often prefer this function for a similar phrase role")

    if chord.function in ctx.lesson.target_functions:
        reasons.append(f"{chord.function} aligns with the current lesson focus")
    elif "seventh_color" in chord.concepts and "seventh_color" in ctx.lesson.target_concepts:
        reasons.append("added seventh color matches the teaching target")

    unique: List[str] = []
    for item in reasons:
        if item not in unique:
            unique.append(item)
    return unique[:3]


def evaluate_candidate(
    events: List[MelodyEvent],
    chord: ChordCandidate,
    prev_chord: Optional[ChordCandidate],
    ctx: HREContext,
    tonic: str,
    mode: str,
    hre_weights: Optional[Dict[str, float]] = None,
) -> HRECandidateEvaluation:
    scores = score_hre_breakdown(events, chord, prev_chord, ctx, **(hre_weights or {}))
    roman = infer_roman(chord.symbol, tonic=tonic, mode=mode)
    setattr(chord, "_roman_cache", roman)
    reasons = build_verified_reasons(events, chord, ctx, prev_chord, tonic=tonic, mode=mode)
    tier = classify_tier(chord, ctx, scores)
    return HRECandidateEvaluation(
        chord=chord,
        roman=roman,
        function=chord.function,
        scores=scores,
        total=scores["total"],
        tier=tier,
        verified_reasons=reasons,
    )


def apply_llm_hints(
    base_candidates: Sequence[ChordCandidate],
    planner_symbols: Sequence[str],
    tonic: str,
    mode: str,
    function_hint: Optional[str] = None,
    basic_only: bool = False,
) -> List[ChordCandidate]:
    pool: Dict[str, ChordCandidate] = {candidate.symbol: replace(candidate) for candidate in base_candidates}

    for rank, raw_symbol in enumerate(planner_symbols, start=1):
        # planners may spell enharmonically (A# for Bb); key spelling makes them merge with the candidate bank
        normalized = normalize_chord_symbol(respell_symbol(normalize_chord_symbol(str(raw_symbol)), tonic, mode))
        if basic_only:
            normalized = simplify_symbol_for_basic_harmony(normalized)
        if not normalized:
            continue
        existing = pool.get(normalized)
        if existing is None:
            pool[normalized] = derive_candidate_from_symbol(
                normalized,
                tonic=tonic,
                mode=mode,
                freq_norm=0.38,
                llm_rank=rank,
            )
            continue
        existing.llm_rank = rank if existing.llm_rank is None else min(existing.llm_rank, rank)

    normalized_hint = (function_hint or "").strip().upper()
    if normalized_hint in VALID_FUNCTIONS:
        for candidate in pool.values():
            if candidate.function == normalized_hint and candidate.llm_rank is None:
                candidate.llm_same_function = True

    return list(pool.values())


def beam_search_chord_sequences(
    events_by_t: Sequence[List[MelodyEvent]],
    candidate_pools_by_t: Sequence[Sequence[ChordCandidate]],
    contexts_by_t: Sequence[HREContext],
    tonic: str,
    mode: str,
    beam_width: int = 8,
    per_step_limit: int = 6,
    hre_weights: Optional[Dict[str, float]] = None,
) -> List[Tuple[float, List[HRECandidateEvaluation]]]:
    if not events_by_t or not candidate_pools_by_t or len(events_by_t) != len(candidate_pools_by_t):
        return []

    beam: List[Tuple[float, List[HRECandidateEvaluation], List[str]]] = [(0.0, [], [])]
    for index, events in enumerate(events_by_t):
        next_beam: List[Tuple[float, List[HRECandidateEvaluation], List[str]]] = []
        for total_score, path, history in beam:
            prev = path[-1].chord if path else None
            local_ctx = replace(
                contexts_by_t[index],
                history_symbols=list(history),
            )
            ranked = [
                evaluate_candidate(
                    events,
                    chord,
                    prev,
                    local_ctx,
                    tonic=tonic,
                    mode=mode,
                    hre_weights=hre_weights,
                )
                for chord in candidate_pools_by_t[index]
            ]
            ranked.sort(
                key=lambda item: (
                    item.total,
                    1.0 - item.chord.complexity,
                    item.chord.freq_norm,
                ),
                reverse=True,
            )
            if prev is not None:
                non_repeating = [item for item in ranked if item.chord.symbol != prev.symbol]
                if non_repeating:
                    ranked = non_repeating
            for option in ranked[:per_step_limit]:
                next_beam.append(
                    (
                        total_score + option.total,
                        path + [option],
                        history + [option.chord.symbol],
                    )
                )
        next_beam.sort(key=lambda item: item[0], reverse=True)
        beam = next_beam[:beam_width]
        if not beam:
            return []

    return [(score / max(len(path), 1), path) for score, path, _ in beam]


def harmonic_cap_from_payload(payload: Optional[Dict[str, Any]]) -> float:
    if not payload:
        return 0.35
    level = str(payload.get("skill_level") or "beginner").strip().lower()
    if level == "early_intermediate":
        return 0.58
    return 0.35


def build_hre_contexts(
    bar_count: int,
    tonic: str,
    mode: str,
    style: str,
    function_hints: Sequence[Optional[str]],
    phrase_roles: Sequence[str],
    harmonic_cap: float,
    user_goal: str = "",
    initial_history: Optional[Iterable[str]] = None,
) -> List[HREContext]:
    scale = key_scale_pcs(tonic=tonic, mode=mode)
    history = list(initial_history or [])
    contexts: List[HREContext] = []
    for idx in range(bar_count):
        role = phrase_roles[idx] if idx < len(phrase_roles) else "middle"
        function_hint = function_hints[idx] if idx < len(function_hints) else None
        lesson = build_lesson_spec(
            style=style,
            phrase_role=role,
            function_hint=function_hint,
            harmonic_cap=harmonic_cap,
            user_goal=user_goal,
        )
        contexts.append(
            HREContext(
                key_scale_pcs=scale,
                phrase_role=role,
                lesson=lesson,
                learner=LearnerProfile(harmonic_cap=harmonic_cap),
                history_symbols=list(history),
            )
        )
    return contexts
