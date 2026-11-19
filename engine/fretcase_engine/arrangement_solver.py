from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

try:
    from fretcase_engine.chord_spelling import ChordSet
    from fretcase_engine.harmony_reasoning import clamp01
    from fretcase_engine.learner_model import normalize_chord_symbol
except ImportError:
    from chord_spelling import ChordSet
    from harmony_reasoning import clamp01
    from learner_model import normalize_chord_symbol


NEG_INF = -1e9
STANDARD_TUNING_MIDI = (40, 45, 50, 55, 59, 64)
TYPE_PRIOR_PATH = Path(__file__).resolve().parent / "data" / "acs_type_difficulty.json"
TRANSITION_PRIOR_PATH = Path(__file__).resolve().parent / "data" / "acs_transition_priors.json"
VOICING_LIBRARY_PATH = Path(__file__).resolve().parent / "data" / "guitar_voicings.json"
BEGINNER_SHAPES_PATH = Path(__file__).resolve().parent / "data" / "beginner_shapes.json"
DEFAULT_TYPE_PRIORS_BY_TYPE = {
    "": 0.28,
    "m": 0.27,
    "7": 0.34,
    "m7": 0.31,
    "maj7": 0.36,
    "dim": 0.48,
}
DEFAULT_STYLE_LANE = {
    "traditional": "basic",
    "pop": "explore",
    "jazz": "color",
}
ROOT_TO_PC = {
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


def _load_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


TYPE_PRIORS: Dict[str, object] = _load_json(TYPE_PRIOR_PATH)
TRANSITION_PRIORS: Dict[str, object] = _load_json(TRANSITION_PRIOR_PATH)
TYPE_PRIORS_SOURCE = "json" if TYPE_PRIORS else "builtin_type_defaults"
TRANSITION_PRIORS_SOURCE = "json" if TRANSITION_PRIORS else "none"


@dataclass
class ACSLearner:
    target_tech_difficulty: float
    max_difficulty: float
    known_symbols: frozenset = frozenset()
    known_allowance: float = 0.20  # chords the learner already plays may exceed max_difficulty by this much
    stretch_symbols: frozenset = frozenset()  # at most one chord type introduced beyond the current level
    stretch_allowance: float = 0.10

    def max_difficulty_for(self, chord_symbol: str) -> float:
        if chord_symbol in self.known_symbols:
            return clamp01(self.max_difficulty + self.known_allowance)
        if chord_symbol in self.stretch_symbols:
            return clamp01(self.max_difficulty + self.stretch_allowance)
        return self.max_difficulty


@dataclass
class ConstraintSpec:
    must_contain_melody_note: bool = True
    must_top_align: bool = False
    max_fret_span: int = 4
    allow_barre: bool = False
    preferred_center: float = 3.0
    max_register_distance: float = 8.0
    max_shift: float = 7.0
    max_pitch_move: float = 12.0
    allow_inner_mutes: bool = True  # muted string between sounding strings (needs damping skill)


@dataclass
class VoicingCandidate:
    chord_symbol: str
    chord_root: str
    chord_type: str
    frets: Tuple[int, ...]
    pitch_classes: Set[int]
    pitch_list: List[int]
    top_note_pc: int
    fret_span: int
    barre: bool
    finger_count: int
    difficulty: float
    position_center: float
    fingers: Tuple[int, ...] = ()
    barres: Tuple[int, ...] = ()
    source: str = "builtin"
    beginner_friendly: bool = False

    @property
    def base_fret(self) -> int:
        positive = [fret for fret in self.frets if fret > 0]
        return min(positive) if positive else 0

    @property
    def inner_mutes(self) -> int:
        sounding = [index for index, fret in enumerate(self.frets) if fret >= 0]
        if not sounding:
            return 0
        return sum(1 for index in range(sounding[0], sounding[-1] + 1) if self.frets[index] < 0)

    def pressed_positions(self) -> Set[Tuple[int, int]]:
        out: Set[Tuple[int, int]] = set()
        for string_index, fret in enumerate(self.frets):
            if fret >= 0:
                out.add((string_index, fret))
        return out


@dataclass(frozen=True)
class VoicingTemplate:
    symbol: str
    frets: Tuple[int, ...]
    difficulty: float
    barre: bool = False
    fingers: Tuple[int, ...] = ()
    barres: Tuple[int, ...] = ()
    source: str = "builtin"
    beginner_friendly: bool = False


DEFAULT_VOICING_LIBRARY: Tuple[VoicingTemplate, ...] = (
    VoicingTemplate("C", (-1, 3, 2, 0, 1, 0), 0.16),
    VoicingTemplate("Cmaj7", (-1, 3, 2, 0, 0, 0), 0.22),
    VoicingTemplate("C7", (-1, 3, 2, 3, 1, 0), 0.30),
    VoicingTemplate("Dm", (-1, -1, 0, 2, 3, 1), 0.22),
    VoicingTemplate("Dm7", (-1, -1, 0, 2, 1, 1), 0.28),
    VoicingTemplate("D", (-1, -1, 0, 2, 3, 2), 0.20),
    VoicingTemplate("D7", (-1, -1, 0, 2, 1, 2), 0.22),
    VoicingTemplate("Em", (0, 2, 2, 0, 0, 0), 0.12),
    VoicingTemplate("Em7", (0, 2, 0, 0, 0, 0), 0.16),
    VoicingTemplate("E", (0, 2, 2, 1, 0, 0), 0.18),
    VoicingTemplate("E7", (0, 2, 0, 1, 0, 0), 0.18),
    VoicingTemplate("F", (1, 3, 3, 2, 1, 1), 0.82, True),
    VoicingTemplate("Fmaj7", (-1, -1, 3, 2, 1, 0), 0.32),
    VoicingTemplate("G", (3, 2, 0, 0, 0, 3), 0.20),
    VoicingTemplate("G7", (3, 2, 0, 0, 0, 1), 0.25),
    VoicingTemplate("A", (-1, 0, 2, 2, 2, 0), 0.20),
    VoicingTemplate("Am", (-1, 0, 2, 2, 1, 0), 0.18),
    VoicingTemplate("Am7", (-1, 0, 2, 0, 1, 0), 0.18),
    VoicingTemplate("A7", (-1, 0, 2, 0, 2, 0), 0.20),
    VoicingTemplate("B7", (-1, 2, 1, 2, 0, 2), 0.38),
    VoicingTemplate("Bdim", (-1, 2, 3, 4, 3, -1), 0.48),  # x2343x: B F B D (x2313x adds G#, i.e. Bdim7)
)


def infer_fingering(frets: Sequence[int], barres: Sequence[int] = ()) -> Tuple[int, ...]:
    """Conventional left-hand fingering for a shape that has none stored (built-in templates).

    Fretted notes are numbered 1-4 in order of (fret, string from low E); a barre is played with
    finger 1 on every string at the barre fret.  This reproduces the textbook fingerings of the open
    shapes (C x32010 -> 0,3,2,0,1,0; G 320003 -> 2,1,0,0,0,3; Am x02210 -> 0,0,2,3,1,0; F 133211 ->
    1,3,4,2,1,1).  Returns () when the shape needs more than four fingers, so callers can fall back to
    showing frets only.  Used for display; difficulty and finger_count keep their original definition."""
    values = [int(f) for f in frets]
    if len(values) != 6:
        return ()
    fingers = [0] * 6
    pressed = [(fret, index) for index, fret in enumerate(values) if fret > 0]
    if not pressed:
        return tuple(fingers)
    next_finger = 1
    barre_fret = min(int(b) for b in barres) if barres else None
    if barre_fret is not None:
        for fret, index in pressed:
            if fret == barre_fret:
                fingers[index] = 1
        next_finger = 2
        pressed = [(fret, index) for fret, index in pressed if fret != barre_fret]
    for fret, index in sorted(pressed):
        if next_finger > 4:
            return ()
        fingers[index] = next_finger
        next_finger += 1
    return tuple(fingers)


def template_to_voicing(template: VoicingTemplate) -> VoicingCandidate:
    normalized_symbol = normalize_chord_symbol(template.symbol)
    chord_root, chord_type = split_root_and_type(normalized_symbol)
    pitch_list: List[int] = []
    pitch_classes: Set[int] = set()
    pressed_frets = [fret for fret in template.frets if fret >= 0]
    positive_frets = [fret for fret in template.frets if fret > 0]
    for string_index, fret in enumerate(template.frets):
        if fret < 0:
            continue
        midi = STANDARD_TUNING_MIDI[string_index] + fret
        pitch_list.append(midi)
        pitch_classes.add(midi % 12)
    top_note_pc = max(pitch_list) % 12 if pitch_list else 0
    fret_span = 0
    if positive_frets:
        fret_span = max(positive_frets) - min(positive_frets) + 1
    position_center = 0.0
    if positive_frets:
        position_center = sum(positive_frets) / len(positive_frets)
    return VoicingCandidate(
        chord_symbol=normalized_symbol,
        chord_root=chord_root,
        chord_type=chord_type,
        frets=template.frets,
        pitch_classes=pitch_classes,
        pitch_list=sorted(pitch_list),
        top_note_pc=top_note_pc,
        fret_span=fret_span,
        barre=template.barre,
        finger_count=len({int(f) for f in template.fingers if int(f) > 0}) if template.fingers else len(set(positive_frets)),
        difficulty=clamp01(template.difficulty),
        position_center=position_center,
        fingers=(
            tuple(int(f) for f in template.fingers)
            if len(template.fingers) == 6
            else infer_fingering(template.frets, template.barres)
        ),
        barres=tuple(int(b) for b in template.barres),
        source=template.source,
        beginner_friendly=bool(template.beginner_friendly),
    )


def split_root_and_type(symbol: str) -> Tuple[str, str]:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return "C", ""
    root = normalized[0]
    suffix_start = 1
    if len(normalized) > 1 and normalized[1] in {"#", "b"}:
        root = normalized[:2]
        suffix_start = 2
    return root, normalized[suffix_start:]


def type_difficulty_prior(chord_root: str, chord_type: str) -> float:
    key = f"{chord_root}:{chord_type}"
    value = TYPE_PRIORS.get(key)
    if value is None:
        value = DEFAULT_TYPE_PRIORS_BY_TYPE.get(chord_type, 0.5)
    try:
        return clamp01(float(value))
    except (TypeError, ValueError):
        return clamp01(float(DEFAULT_TYPE_PRIORS_BY_TYPE.get(chord_type, 0.5)))


def effective_voicing_difficulty(voicing: VoicingCandidate) -> float:
    local = clamp01(voicing.difficulty)
    prior = type_difficulty_prior(voicing.chord_root, voicing.chord_type)
    return clamp01(0.75 * local + 0.25 * prior)


def _library_difficulty_fallback(frets: Sequence[int], barres: Sequence[int], fingers: Sequence[int]) -> float:
    """Same formula as scripts/build_voicing_library.py, for curated entries without a stored value."""
    pressed = [f for f in frets if f > 0]
    sounding = [f for f in frets if f >= 0]
    open_count = sum(1 for f in frets if f == 0)
    span = (max(pressed) - min(pressed) + 1) if pressed else 0
    finger_ids = {int(x) for x in fingers if int(x) > 0}
    finger_count = len(finger_ids) if finger_ids else len(pressed)
    first = next((i for i, f in enumerate(frets) if f >= 0), None)
    last = next((i for i in range(len(frets) - 1, -1, -1) if frets[i] >= 0), None)
    inner = sum(1 for i in range(first, last + 1) if frets[i] < 0) if first is not None and last is not None else 0
    lowest = min(pressed) if pressed else 0
    value = (
        0.30 * min(max(span - 1, 0) / 4.0, 1.0)
        + 0.25 * (1.0 if barres else 0.0)
        + 0.20 * min(max(finger_count - 1, 0) / 3.0, 1.0)
        + 0.15 * min(max(lowest - 1, 0) / 6.0, 1.0)
        + 0.05 * (1.0 - min(open_count / 3.0, 1.0))
        + 0.05 * min(inner / 2.0, 1.0)
    )
    return clamp01(value)


def _load_library_templates() -> List[VoicingTemplate]:
    templates: List[VoicingTemplate] = []
    for path in (VOICING_LIBRARY_PATH, BEGINNER_SHAPES_PATH):
        payload = _load_json(path)
        rows = payload.get("voicings") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            try:
                frets = tuple(int(f) for f in row["frets"])
                if len(frets) != 6:
                    continue
                fingers = tuple(int(f) for f in row.get("fingers", ()))
                barres = tuple(int(b) for b in row.get("barres", ()))
                difficulty = row.get("difficulty")
                if difficulty is None:
                    difficulty = _library_difficulty_fallback(frets, barres, fingers)
                beginner = row.get("beginner_friendly")
                if beginner is None:
                    pressed = [f for f in frets if f > 0]
                    beginner = bool(not barres and (min(pressed) if pressed else 0) <= 4 and sum(1 for f in frets if f >= 0) >= 4)
                templates.append(
                    VoicingTemplate(
                        symbol=str(row["symbol"]),
                        frets=frets,
                        difficulty=clamp01(float(difficulty)),
                        barre=bool(barres),
                        fingers=fingers,
                        barres=barres,
                        source=str(row.get("source") or path.stem),
                        beginner_friendly=bool(beginner),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return templates


LIBRARY_VOICING_TEMPLATES: Tuple[VoicingTemplate, ...] = tuple(_load_library_templates())
VOICING_LIBRARY_SOURCE = "json" if LIBRARY_VOICING_TEMPLATES else "builtin_only"


def voicing_library_fingerprint() -> str:
    """Stable hash of the voicing inventory, for provenance records."""
    digest = hashlib.sha1()
    for template in list(DEFAULT_VOICING_LIBRARY) + list(LIBRARY_VOICING_TEMPLATES):
        digest.update(f"{template.symbol}:{template.frets}:{template.difficulty:.4f};".encode("utf-8"))
    return digest.hexdigest()[:12]


def voicing_library_stats() -> Dict[str, object]:
    inventory = build_default_voicing_inventory()
    total = sum(len(rows) for rows in inventory.values())
    return {
        "source": VOICING_LIBRARY_SOURCE,
        "builtin_templates": len(DEFAULT_VOICING_LIBRARY),
        "library_templates": len(LIBRARY_VOICING_TEMPLATES),
        "symbols": len(inventory),
        "voicings": total,
        "fingerprint": voicing_library_fingerprint(),
    }


def _unified_builtin_templates() -> List[VoicingTemplate]:
    """Built-in open shapes re-scored with the library difficulty formula so every voicing shares one scale."""
    rows: List[VoicingTemplate] = []
    for template in DEFAULT_VOICING_LIBRARY:
        pressed = [f for f in template.frets if f > 0]
        barres = (min(pressed),) if (template.barre and pressed) else ()
        rows.append(
            replace(
                template,
                difficulty=_library_difficulty_fallback(template.frets, barres, template.fingers),
                barres=barres,
                beginner_friendly=bool(not template.barre and (min(pressed) if pressed else 0) <= 4 and sum(1 for f in template.frets if f >= 0) >= 4),
            )
        )
    return rows


@lru_cache(maxsize=1)
def _cached_default_inventory() -> Dict[str, Tuple[VoicingCandidate, ...]]:
    inventory: Dict[str, List[VoicingCandidate]] = {}
    seen: Set[Tuple[str, Tuple[int, ...]]] = set()
    # Built-in templates first (they define the canonical open shapes), then the library.
    for template in _unified_builtin_templates() + list(LIBRARY_VOICING_TEMPLATES):
        voicing = template_to_voicing(template)
        key = (voicing.chord_symbol, voicing.frets)
        if key in seen:
            continue
        seen.add(key)
        inventory.setdefault(voicing.chord_symbol, []).append(voicing)
    for symbol in inventory:
        inventory[symbol].sort(key=lambda v: (effective_voicing_difficulty(v), v.position_center))
    return {symbol: tuple(rows) for symbol, rows in inventory.items()}


def build_default_voicing_inventory() -> Dict[str, List[VoicingCandidate]]:
    """Inventory keyed by normalized chord symbol: built-in open shapes + chords-db library + curated shapes."""
    return {symbol: list(rows) for symbol, rows in _cached_default_inventory().items()}


def normalize_constraint_lane(lane: Optional[str], style: str = "") -> str:
    raw = (lane or "").strip().lower()
    if raw == "colour":
        raw = "color"
    if raw in {"basic", "explore", "color"}:
        return raw
    return DEFAULT_STYLE_LANE.get((style or "").strip().lower(), "basic")


def transpose_template(
    template: VoicingTemplate,
    semitones: int,
    target_symbol: str,
) -> Optional[VoicingCandidate]:
    if semitones < 0:
        return None
    shifted: List[int] = []
    for fret in template.frets:
        if fret < 0:
            shifted.append(-1)
            continue
        shifted.append(fret + semitones)
    if max((fret for fret in shifted if fret >= 0), default=0) > 12:
        return None
    extra_penalty = 0.03 * min(semitones, 6) + (0.10 if semitones > 0 else 0.0)
    return template_to_voicing(
        VoicingTemplate(
            symbol=target_symbol,
            frets=tuple(shifted),
            difficulty=clamp01(template.difficulty + extra_penalty),
            barre=template.barre or semitones > 0,
        )
    )


def transposed_voicings_for_symbol(symbol: str) -> List[VoicingCandidate]:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return []
    target_root, target_type = split_root_and_type(normalized)
    target_pc = ROOT_TO_PC.get(target_root)
    if target_pc is None:
        return []

    candidates: List[VoicingCandidate] = []
    seen: Set[Tuple[int, ...]] = set()
    for template in DEFAULT_VOICING_LIBRARY:
        template_voicing = template_to_voicing(template)
        if template_voicing.chord_type != target_type:
            continue
        source_pc = ROOT_TO_PC.get(template_voicing.chord_root)
        if source_pc is None:
            continue
        semitones = (target_pc - source_pc) % 12
        shifted = transpose_template(template, semitones, normalized)
        if shifted is None or shifted.frets in seen:
            continue
        seen.add(shifted.frets)
        candidates.append(shifted)
    return candidates


def simplify_symbol_for_inventory(symbol: str) -> List[str]:
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return ["C"]
    options = [normalized]

    root = normalized[0]
    suffix_start = 1
    if len(normalized) > 1 and normalized[1] in {"#", "b"}:
        root = normalized[:2]
        suffix_start = 2
    suffix = normalized[suffix_start:]

    if suffix in {"", "m"}:
        pass
    elif suffix in {"maj7", "7"}:
        options.append(root)
    elif suffix in {"m7", "m9"}:
        options.append(f"{root}m")
    elif suffix == "dim":
        options.append("Bdim")
    else:
        options.append(root)

    unique: List[str] = []
    for item in options:
        clean = normalize_chord_symbol(item)
        if clean and clean not in unique:
            unique.append(clean)
    return unique


def voicing_candidates_for_symbol(
    symbol: str,
    inventory: Optional[Dict[str, List[VoicingCandidate]]] = None,
) -> List[VoicingCandidate]:
    stock = inventory or build_default_voicing_inventory()
    normalized = normalize_chord_symbol(symbol)
    if not normalized:
        return []

    candidates: List[VoicingCandidate] = []
    seen: Set[Tuple[int, ...]] = set()
    for voicing in stock.get(normalized, []):
        if voicing.frets in seen:
            continue
        seen.add(voicing.frets)
        candidates.append(voicing)
    for voicing in transposed_voicings_for_symbol(normalized):
        if voicing.frets in seen:
            continue
        seen.add(voicing.frets)
        candidates.append(voicing)
    if candidates:
        return candidates

    options = simplify_symbol_for_inventory(normalized)
    for option in options[1:]:
        for voicing in stock.get(option, []):
            if voicing.frets in seen:
                continue
            seen.add(voicing.frets)
            candidates.append(voicing)
        if candidates:
            continue
        for voicing in transposed_voicings_for_symbol(option):
            if voicing.frets in seen:
                continue
            seen.add(voicing.frets)
            candidates.append(voicing)
    return candidates


def hard_violation(
    v: VoicingCandidate,
    melody_pc: int,
    spec: ConstraintSpec,
    learner: ACSLearner,
) -> bool:
    if spec.must_contain_melody_note and melody_pc not in v.pitch_classes:
        return True
    if spec.must_top_align and melody_pc != v.top_note_pc:
        return True
    if v.fret_span > spec.max_fret_span:
        return True
    if v.barre and not spec.allow_barre:
        return True
    if not spec.allow_inner_mutes and v.inner_mutes > 0:
        return True
    if effective_voicing_difficulty(v) > learner.max_difficulty_for(v.chord_symbol):
        return True
    return False


def melody_top_fit(v: VoicingCandidate, melody_pc: int) -> float:
    if v.top_note_pc == melody_pc:
        return 1.0
    if melody_pc in v.pitch_classes:
        return 0.75
    return 0.0


def playability(v: VoicingCandidate, spec: ConstraintSpec) -> float:
    span_fit = 1.0 - (v.fret_span / max(spec.max_fret_span, 1))
    barre_fit = 0.0 if v.barre else 1.0
    finger_fit = 1.0 - (max(0, v.finger_count - 1) / 3.0)
    score = 0.45 * span_fit + 0.35 * barre_fit + 0.20 * finger_fit
    return clamp01(score)


def difficulty_match(v: VoicingCandidate, learner: ACSLearner) -> float:
    return clamp01(1.0 - abs(effective_voicing_difficulty(v) - learner.target_tech_difficulty))


def register_fit(v: VoicingCandidate, spec: ConstraintSpec) -> float:
    dist = abs(v.position_center - spec.preferred_center)
    return clamp01(1.0 - dist / max(spec.max_register_distance, 1e-8))


def unary_score(
    v: VoicingCandidate,
    melody_pc: int,
    spec: ConstraintSpec,
    learner: ACSLearner,
    um: float = 0.35,
    up: float = 0.30,
    ud: float = 0.20,
    ur: float = 0.15,
) -> float:
    if hard_violation(v, melody_pc, spec, learner):
        return NEG_INF
    mt = melody_top_fit(v, melody_pc)
    pl = playability(v, spec)
    dm = difficulty_match(v, learner)
    rf = register_fit(v, spec)
    return clamp01(um * mt + up * pl + ud * dm + ur * rf)


def shift_fit(v_prev: VoicingCandidate, v_cur: VoicingCandidate, spec: ConstraintSpec) -> float:
    dist = abs(v_cur.position_center - v_prev.position_center)
    return clamp01(1.0 - dist / max(spec.max_shift, 1e-8))


def finger_reuse(v_prev: VoicingCandidate, v_cur: VoicingCandidate) -> float:
    left = v_prev.pressed_positions()
    right = v_cur.pressed_positions()
    overlap = len(left.intersection(right))
    denom = max(len(left), len(right), 1)
    return clamp01(overlap / denom)


def continuity(v_prev: VoicingCandidate, v_cur: VoicingCandidate, spec: ConstraintSpec) -> float:
    if not v_prev.pitch_list or not v_cur.pitch_list:
        prev_top = max(v_prev.pitch_list) if v_prev.pitch_list else 0
        cur_top = max(v_cur.pitch_list) if v_cur.pitch_list else 0
        move = abs(cur_top - prev_top)
        return clamp01(1.0 - move / max(spec.max_pitch_move, 1e-8))

    n = min(len(v_prev.pitch_list), len(v_cur.pitch_list))
    prev_sorted = sorted(v_prev.pitch_list)[-n:]
    cur_sorted = sorted(v_cur.pitch_list)[-n:]
    mean_move = sum(abs(a - b) for a, b in zip(prev_sorted, cur_sorted)) / max(n, 1)
    return clamp01(1.0 - mean_move / max(spec.max_pitch_move, 1e-8))


def pairwise_score(
    v_prev: VoicingCandidate,
    v_cur: VoicingCandidate,
    spec: ConstraintSpec,
    ts: float = 0.40,
    tf: float = 0.30,
    tc: float = 0.30,
) -> float:
    sf = shift_fit(v_prev, v_cur, spec)
    fr = finger_reuse(v_prev, v_cur)
    ct = continuity(v_prev, v_cur, spec)
    prior_bonus = 0.0
    transition_key = f"{v_prev.chord_symbol}->{v_cur.chord_symbol}"
    if isinstance(TRANSITION_PRIORS, dict) and transition_key in TRANSITION_PRIORS:
        try:
            prior_bonus = 0.10 * clamp01(float(TRANSITION_PRIORS[transition_key]))
        except (TypeError, ValueError):
            prior_bonus = 0.0
    return clamp01(ts * sf + tf * fr + tc * ct + prior_bonus)


def decode_voicings_viterbi(
    candidates_by_t: List[List[VoicingCandidate]],
    melody_pcs: List[int],
    spec: ConstraintSpec,
    learner: ACSLearner,
    unary_weights: Optional[Dict[str, float]] = None,
    pairwise_weights: Optional[Dict[str, float]] = None,
) -> Tuple[float, List[VoicingCandidate]]:
    if not candidates_by_t:
        return NEG_INF, []

    T = len(candidates_by_t)
    dp: List[Dict[int, float]] = []
    back: List[Dict[int, Optional[int]]] = []
    # melody containment is only enforced where the chord actually contains the melody note
    step_specs = [effective_spec_for_step(spec, melody_pcs[t], candidates_by_t[t]) for t in range(T)]

    for _ in range(T):
        dp.append({})
        back.append({})

    for idx, voicing in enumerate(candidates_by_t[0]):
        score = unary_score(voicing, melody_pcs[0], step_specs[0], learner, **(unary_weights or {}))
        if score > NEG_INF:
            dp[0][idx] = score
            back[0][idx] = None

    for t in range(1, T):
        for idx, v_cur in enumerate(candidates_by_t[t]):
            unary = unary_score(v_cur, melody_pcs[t], step_specs[t], learner, **(unary_weights or {}))
            if unary <= NEG_INF:
                continue
            best_score = NEG_INF
            best_prev: Optional[int] = None
            for prev_idx, v_prev in enumerate(candidates_by_t[t - 1]):
                if prev_idx not in dp[t - 1]:
                    continue
                score = (
                    dp[t - 1][prev_idx]
                    + pairwise_score(v_prev, v_cur, spec, **(pairwise_weights or {}))
                    + unary
                )
                if score > best_score:
                    best_score = score
                    best_prev = prev_idx
            if best_prev is not None:
                dp[t][idx] = best_score
                back[t][idx] = best_prev

    if not dp[-1]:
        return NEG_INF, []

    last_idx = max(dp[-1], key=lambda item: dp[-1][item])
    best_total = dp[-1][last_idx]

    path = [last_idx]
    for t in range(T - 1, 0, -1):
        prev_idx = back[t][last_idx]
        if prev_idx is None:
            return NEG_INF, []
        last_idx = prev_idx
        path.append(last_idx)
    path.reverse()

    voicing_path = [candidates_by_t[t][idx] for t, idx in enumerate(path)]
    unary_total = sum(
        unary_score(v, melody_pcs[t], step_specs[t], learner, **(unary_weights or {}))
        for t, v in enumerate(voicing_path)
    )
    pair_total = sum(
        pairwise_score(voicing_path[t - 1], voicing_path[t], spec, **(pairwise_weights or {}))
        for t in range(1, len(voicing_path))
    )
    denom = len(voicing_path) + max(0, len(voicing_path) - 1)
    norm_score = (unary_total + pair_total) / max(denom, 1)
    return norm_score, voicing_path


def build_default_constraint_spec(
    render_mode: str,
    style: str,
    allow_barre: bool,
    lane: Optional[str] = None,
) -> ConstraintSpec:
    sounding = str(render_mode).lower() == "sounding"
    resolved_lane = normalize_constraint_lane(lane, style=style)
    max_fret_span = 5 if sounding else 4
    resolved_allow_barre = allow_barre or sounding
    preferred_center = 4.5 if sounding else 3.0
    max_register_distance = 10.0 if sounding else 8.0
    max_shift = 8.0 if sounding else 6.0
    max_pitch_move = 14.0 if sounding else 12.0

    allow_inner_mutes = True
    if resolved_lane == "basic":
        resolved_allow_barre = resolved_allow_barre and sounding
        allow_inner_mutes = False
        preferred_center -= 0.5
        max_register_distance -= 1.0
        max_shift -= 1.0
        max_pitch_move -= 1.5
    elif resolved_lane == "color":
        max_fret_span += 1
        resolved_allow_barre = True
        preferred_center += 1.0
        max_register_distance += 1.5
        max_shift += 1.5
        max_pitch_move += 2.0

    return ConstraintSpec(
        must_contain_melody_note=True,
        must_top_align=False,
        max_fret_span=max_fret_span,
        allow_barre=resolved_allow_barre,
        preferred_center=preferred_center,
        max_register_distance=max_register_distance,
        max_shift=max_shift,
        max_pitch_move=max_pitch_move,
        allow_inner_mutes=allow_inner_mutes,
    )


# Difficulty thresholds on the unified voicing-difficulty scale (see scripts/build_voicing_library.py):
# open C/G/D/Am/Em/E/A ~ 0.10-0.30, Dm/G7/B7/Fmaj7 ~ 0.28-0.33, small F / C7 / Bdim ~ 0.35-0.42,
# four-string Bm ~ 0.42, full barre F / Bm ~ 0.65-0.70, barre B ~ 0.77.
ACS_MAX_DIFFICULTY = {
    ("beginner", "playable"): 0.40,
    ("beginner", "sounding"): 0.52,
    ("early_intermediate", "playable"): 0.62,
    ("early_intermediate", "sounding"): 0.72,
}
ACS_TARGET_DIFFICULTY = {
    ("beginner", "playable"): 0.22,
    ("beginner", "sounding"): 0.30,
    ("early_intermediate", "playable"): 0.38,
    ("early_intermediate", "sounding"): 0.48,
}
ACS_LANE_ADJUST = {"basic": -0.05, "explore": 0.0, "color": 0.06}


def build_acs_learner(
    skill_level: str,
    render_mode: str,
    lane: Optional[str] = None,
    known_chords: Optional[Sequence[str]] = None,
) -> ACSLearner:
    level = (skill_level or "beginner").strip().lower()
    if level not in {"beginner", "early_intermediate"}:
        level = "beginner"
    mode = "sounding" if str(render_mode).lower() == "sounding" else "playable"
    target = ACS_TARGET_DIFFICULTY[(level, mode)]
    max_difficulty = ACS_MAX_DIFFICULTY[(level, mode)]
    if lane:
        adjust = ACS_LANE_ADJUST.get(normalize_constraint_lane(lane), 0.0)
        target += adjust
        max_difficulty += adjust
    known = ChordSet(normalize_chord_symbol(str(symbol)) for symbol in (known_chords or []) if str(symbol).strip())
    return ACSLearner(
        target_tech_difficulty=clamp01(target),
        max_difficulty=clamp01(max_difficulty),
        known_symbols=known,
    )


def relax_constraint_spec(
    spec: ConstraintSpec,
    lane: Optional[str] = None,
    allow_melody_omission: bool = False,
) -> ConstraintSpec:
    resolved_lane = normalize_constraint_lane(lane)
    return replace(
        spec,
        must_contain_melody_note=False if allow_melody_omission else spec.must_contain_melody_note,
        max_fret_span=spec.max_fret_span + (0 if resolved_lane == "basic" else 1),
        allow_barre=spec.allow_barre or resolved_lane in {"explore", "color"},
        max_register_distance=spec.max_register_distance + 1.0,
        max_shift=spec.max_shift + (1.0 if resolved_lane == "basic" else 1.5),
        max_pitch_move=spec.max_pitch_move + (1.5 if resolved_lane == "basic" else 2.5),
    )


def relax_acs_learner(learner: ACSLearner, lane: Optional[str] = None) -> ACSLearner:
    resolved_lane = normalize_constraint_lane(lane)
    difficulty_bonus = 0.06 if resolved_lane == "basic" else 0.10
    target_bonus = 0.03 if resolved_lane == "basic" else 0.05
    return replace(
        learner,
        target_tech_difficulty=clamp01(learner.target_tech_difficulty + target_bonus),
        max_difficulty=clamp01(learner.max_difficulty + difficulty_bonus),
    )


def effective_spec_for_step(
    spec: ConstraintSpec,
    melody_pc: int,
    candidates: Sequence[VoicingCandidate],
) -> ConstraintSpec:
    """The accompaniment is played *under* a separate melody voice, so requiring the voicing to contain
    the melody pitch class only makes sense when the chord itself contains that note (then the voicing
    should keep it audible).  When the melody note is a non-chord tone for this chord (e.g. B over C
    major), the containment rule is vacuous and is dropped for this step; melody_top_fit still rewards
    voicings that support the melody."""
    if not spec.must_contain_melody_note:
        return spec
    if any(melody_pc in voicing.pitch_classes for voicing in candidates):
        return spec
    return replace(spec, must_contain_melody_note=False, must_top_align=False)


def feasible_voicings_for_step(
    symbol: str,
    melody_pc: int,
    spec: ConstraintSpec,
    learner: ACSLearner,
    inventory: Optional[Dict[str, List[VoicingCandidate]]] = None,
    unary_weights: Optional[Dict[str, float]] = None,
) -> List[VoicingCandidate]:
    candidates = voicing_candidates_for_symbol(symbol, inventory=inventory)
    step_spec = effective_spec_for_step(spec, melody_pc, candidates)
    return [
        voicing
        for voicing in candidates
        if unary_score(voicing, melody_pc, step_spec, learner, **(unary_weights or {})) > NEG_INF
    ]


def voicing_debug_summary(voicing: VoicingCandidate) -> Dict[str, object]:
    return {
        "chord_symbol": voicing.chord_symbol,
        "chord_root": voicing.chord_root,
        "chord_type": voicing.chord_type,
        "frets": list(voicing.frets),
        "fingers": list(voicing.fingers) if voicing.fingers else [],
        "barres": list(voicing.barres) if voicing.barres else ([voicing.base_fret] if voicing.barre and voicing.base_fret else []),
        "base_fret": int(voicing.base_fret),
        "barre": bool(voicing.barre),
        "fret_span": int(voicing.fret_span),
        "finger_count": int(voicing.finger_count),
        "difficulty": round(effective_voicing_difficulty(voicing), 3),
        "local_difficulty": round(clamp01(voicing.difficulty), 3),
        "beginner_friendly": bool(voicing.beginner_friendly),
        "source": voicing.source,
        "top_note_pc": int(voicing.top_note_pc),
        "position_center": round(voicing.position_center, 3),
    }


RELAXATION_PENALTY = 0.10  # subtracted from the arrangement score per relaxation level that was needed


def stretch_symbols_for(
    chord_symbols: Sequence[str],
    melody_pcs: Sequence[int],
    spec: ConstraintSpec,
    learner: ACSLearner,
    inventory: Optional[Dict[str, List[VoicingCandidate]]] = None,
    unary_weights: Optional[Dict[str, float]] = None,
) -> Optional[frozenset]:
    """Chord symbols that have no feasible voicing for ``learner`` under ``spec``.

    Returns the set when it contains exactly one distinct symbol (the "one new chord at a time" rule a
    stretch relaxation may introduce), otherwise ``None``."""
    failing = {
        symbol
        for index, symbol in enumerate(chord_symbols)
        if not feasible_voicings_for_step(symbol, melody_pcs[index], spec, learner, inventory=inventory, unary_weights=unary_weights)
    }
    if len(failing) == 1:
        return frozenset(failing)
    return None


def solve_fixed_progression(
    chord_symbols: Sequence[str],
    melody_pcs: Sequence[int],
    spec: ConstraintSpec,
    learner: ACSLearner,
    lane: Optional[str] = None,
    allow_melody_omission: bool = True,
    inventory: Optional[Dict[str, List[VoicingCandidate]]] = None,
    unary_weights: Optional[Dict[str, float]] = None,
    pairwise_weights: Optional[Dict[str, float]] = None,
    allow_stretch: bool = False,
) -> Dict[str, object]:
    """Find a voicing path for a fixed chord progression using the same relaxation ladder as the runtime.

    Returns {"available": bool, "voicing_seq": [...], "arrangement_score": float, "relaxation": 0|1|2,
             "stretch_symbols": [...], "failed_bars": [...], "reasons": {...}}.
    Level 0 = strict spec; level 1 = relaxed spec (wider span, barre permitted outside the basic lane,
    melody-note omission, slightly higher difficulty cap); level 2 (only with ``allow_stretch``) = level 1
    plus one *stretch chord*: when exactly one chord type still has no feasible shape, that type may
    exceed the relaxed cap by ``ACSLearner.stretch_allowance`` (e.g. a simplified Bm xx4432 for a
    beginner).  Each level costs ``RELAXATION_PENALTY``.  The runtime pipeline uses levels 0--1 and
    repairs an unplayable chord by substitution instead; level 2 is an analysis option used by the
    expert-benchmark evaluation to quantify how many expert-preferred progressions would become
    realisable by introducing a single new chord.
    """
    stock = inventory or build_default_voicing_inventory()
    relaxed_spec = relax_constraint_spec(spec, lane=lane, allow_melody_omission=allow_melody_omission)
    relaxed_learner = relax_acs_learner(learner, lane=lane)
    attempts = [(spec, learner, 0), (relaxed_spec, relaxed_learner, 1)]
    if allow_stretch:
        stretch = stretch_symbols_for(chord_symbols, melody_pcs, relaxed_spec, relaxed_learner, inventory=stock, unary_weights=unary_weights)
        if stretch:
            attempts.append((relaxed_spec, replace(relaxed_learner, stretch_symbols=stretch), 2))
    last_failed: List[int] = []
    reasons: Dict[str, int] = {"melody_top_conflict": 0, "difficulty_penalty": 0, "span_or_barre": 0, "no_shape": 0}
    for spec_try, learner_try, level in attempts:
        candidates_by_t: List[List[VoicingCandidate]] = []
        failed: List[int] = []
        for index, symbol in enumerate(chord_symbols):
            feasible = feasible_voicings_for_step(symbol, melody_pcs[index], spec_try, learner_try, inventory=stock, unary_weights=unary_weights)
            candidates_by_t.append(feasible)
            if not feasible:
                failed.append(index + 1)
                step_spec = effective_spec_for_step(spec_try, melody_pcs[index], voicing_candidates_for_symbol(symbol, inventory=stock))
                for voicing in voicing_candidates_for_symbol(symbol, inventory=stock):
                    if step_spec.must_contain_melody_note and melody_pcs[index] not in voicing.pitch_classes:
                        reasons["melody_top_conflict"] += 1
                    elif effective_voicing_difficulty(voicing) > learner_try.max_difficulty_for(voicing.chord_symbol):
                        reasons["difficulty_penalty"] += 1
                    else:
                        reasons["span_or_barre"] += 1
                if not voicing_candidates_for_symbol(symbol, inventory=stock):
                    reasons["no_shape"] += 1
        if failed:
            last_failed = failed
            continue
        score, voicing_seq = decode_voicings_viterbi(
            candidates_by_t=candidates_by_t,
            melody_pcs=list(melody_pcs),
            spec=spec_try,
            learner=learner_try,
            unary_weights=unary_weights,
            pairwise_weights=pairwise_weights,
        )
        if score <= NEG_INF or not voicing_seq:
            last_failed = list(range(1, len(chord_symbols) + 1))
            continue
        return {
            "available": True,
            "voicing_seq": voicing_seq,
            "arrangement_score": clamp01(score - RELAXATION_PENALTY * level),
            "raw_arrangement_score": score,
            "relaxation": level,
            "stretch_symbols": sorted(learner_try.stretch_symbols),
            "spec": spec_try,
            "learner": learner_try,
            "failed_bars": [],
            "reasons": reasons,
        }
    return {
        "available": False,
        "voicing_seq": [],
        "arrangement_score": NEG_INF,
        "raw_arrangement_score": NEG_INF,
        "relaxation": attempts[-1][2],
        "stretch_symbols": [],
        "spec": attempts[-1][0],
        "learner": attempts[-1][1],
        "failed_bars": last_failed,
        "reasons": reasons,
    }

