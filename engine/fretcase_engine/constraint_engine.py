from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import re
from typing import Dict, List, Literal, Optional, Set

from fretcase_engine.key_tempo_validator import check_key_compliance
from fretcase_engine.music_representation import ChordEvent, LeadSheetGraph, NoteEvent, graph_to_abc
Lane = Literal["basic", "explore", "color"]

# Position shift (frets, between the fretted centres of consecutive voicings) a learner is expected to
# manage at tempo.  Grounded in the voicing library shared with the ACS; see _check_h4_transition_cost.
H4_MAX_POSITION_SHIFT = {"playable": 4.0, "sounding": 7.0}
LANE_ALIASES = {"basic": "basic", "traditional": "basic", "explore": "explore", "pop": "explore", "color": "color", "colour": "color", "jazz": "color"}


def normalize_lane(lane: Optional[str]) -> Optional[Lane]:
    if not lane:
        return None
    return LANE_ALIASES.get(str(lane).strip().lower())  # type: ignore[return-value]


@dataclass
class ConstraintReport:
    hard_violations: List[str] = field(default_factory=list)
    soft_warnings: List[str] = field(default_factory=list)
    suggested_repairs: List[str] = field(default_factory=list)


def evaluate(
    graph: LeadSheetGraph,
    mode: Literal["playable", "sounding"] = "playable",
    lane: Optional[str] = None,
    voicings_by_bar: Optional[Dict[int, List[int]]] = None,
) -> ConstraintReport:
    """Hard constraints H1--H5 for a lead sheet.

    ``lane`` (basic / explore / color, or the style aliases traditional / pop / jazz) makes the chord
    vocabulary (H3) lane-aware: the explore lane admits the cautious seventh/suspended colours it is
    designed to introduce, which the plain ``playable`` vocabulary used to flag as hard violations.
    ``voicings_by_bar`` (bar -> six fret numbers, as chosen by the ACS) lets H4 judge the transitions the
    learner will actually play; without it the easiest library shapes are used."""
    report = ConstraintReport()

    _check_h1_bar_durations(graph, report)
    _check_h2_key_compliance(graph, report)
    _check_h3_chord_vocabulary(graph, mode, report, lane=normalize_lane(lane))
    _check_h4_transition_cost(graph, mode, report, voicings_by_bar=voicings_by_bar)
    _check_h5_melody_harmony_fit(graph, mode, report)

    return report


# Meters the interface offers (Step 0) and the offline melody generator writes.  H1 used to accept only 4/4,
# so every 3/4 or 6/8 score was reported with a hard violation although nothing was wrong with it.
SUPPORTED_METERS = ("4/4", "3/4", "6/8", "2/4")


def _check_h1_bar_durations(graph: LeadSheetGraph, report: ConstraintReport) -> None:
    if graph.meter not in SUPPORTED_METERS:
        report.hard_violations.append(
            f"H1: Meter {graph.meter} is not supported (use {', '.join(SUPPORTED_METERS[:3])})"
        )
        return

    beats_per_bar = _beats_per_bar(graph.meter)
    tolerance = 1e-3

    melody_totals = _bar_duration_totals(graph.melody)
    harmony_totals = _bar_duration_totals(graph.harmony)

    melody_has = len(graph.melody) > 0
    harmony_has = len(graph.harmony) > 0

    bars = set()
    if melody_has:
        bars |= set(melody_totals.keys())
    if harmony_has:
        bars |= set(harmony_totals.keys())
    if not bars:
        return

    max_bar = max(bars)
    for bar in range(1, max_bar + 1):
        if melody_has:
            duration = melody_totals.get(bar, 0.0)
            if abs(duration - beats_per_bar) > tolerance:
                report.hard_violations.append(
                    f"H1: Melody bar {bar} duration {duration:.3f} != {beats_per_bar:.3f}"
                )
        if harmony_has:
            duration = harmony_totals.get(bar, 0.0)
            if abs(duration - beats_per_bar) > tolerance:
                report.hard_violations.append(
                    f"H1: Harmony bar {bar} duration {duration:.3f} != {beats_per_bar:.3f}"
                )


def _check_h2_key_compliance(graph: LeadSheetGraph, report: ConstraintReport) -> None:
    key_info = graph.key or {}
    tonic = str(key_info.get("tonic", "C"))
    mode = str(key_info.get("mode", "major")).lower()
    expected_key = tonic
    if mode == "minor" and not tonic.endswith("m"):
        expected_key = f"{tonic}m"

    # H2 is melody-only: harmony can intentionally include non-diatonic color tones.
    melody_only_graph = LeadSheetGraph(
        meter=graph.meter,
        tempo=graph.tempo,
        key=graph.key,
        melody=graph.melody,
        harmony=[],
        rhythm=graph.rhythm,
        ornament=graph.ornament,
    )
    abc = graph_to_abc(melody_only_graph)
    compliance = check_key_compliance(abc, expected_key)
    if not compliance.get("compliant", True):
        report.hard_violations.append(f"H2: {compliance.get('suggestions', 'Key violation')}")
        report.suggested_repairs.append("H2 repair: Snap out-of-key melody notes to nearest scale tone.")


def _check_h3_chord_vocabulary(
    graph: LeadSheetGraph,
    mode: Literal["playable", "sounding"],
    report: ConstraintReport,
    lane: Optional[Lane] = None,
) -> None:
    if not graph.harmony:
        return

    key_roots = _key_root_pcs(graph)
    invalid: List[str] = []
    for chord in graph.harmony:
        normalized = _normalize_chord_symbol(chord.symbol)
        if not _is_allowed_chord_symbol(normalized, mode, lane=lane, key_roots=key_roots):
            invalid.append(f"bar {chord.bar}: {chord.symbol}")

    if invalid:
        scope = f"{lane}-lane" if lane else mode
        report.hard_violations.append(
            f"H3: Chord(s) outside {scope} vocabulary: {', '.join(invalid[:6])}"
        )
        report.suggested_repairs.append(
            "H3 repair: Replace invalid chord with same-function in-vocabulary alternative."
        )


def _check_h4_transition_cost(
    graph: LeadSheetGraph,
    mode: Literal["playable", "sounding"],
    report: ConstraintReport,
    voicings_by_bar: Optional[Dict[int, List[int]]] = None,
) -> None:
    """H4: consecutive chords must not require a position shift beyond the mode's limit.

    Earlier versions scored transitions with a 29-shape heuristic table whose centroid/string-pattern
    distance flagged ordinary open-chord changes (Am->G cost 1.18 > 1.05) as hard violations while
    rating C->F (a barre) as easy; the basic lane was then reported as "unsafe".  Shape difficulty is
    the ACS's responsibility (learner caps, H3 vocabulary); what makes a *transition* infeasible for a
    learner at tempo is a large jump along the neck.  The check therefore measures the position shift
    between the voicings the learner will play (the ACS choice when given, else the easiest library
    shape for each symbol) against ``H4_MAX_POSITION_SHIFT``.  Symbols with no library shape fall back
    to the category-cost heuristic of the deployed version."""
    if len(graph.harmony) < 2:
        return

    sorted_harmony = sorted(graph.harmony, key=lambda e: (e.bar, e.start_beat))
    violations: List[str] = []
    limit = H4_MAX_POSITION_SHIFT.get(mode, H4_MAX_POSITION_SHIFT["playable"])

    for prev, curr in zip(sorted_harmony, sorted_harmony[1:]):
        prev_symbol = _normalize_chord_symbol(prev.symbol)
        curr_symbol = _normalize_chord_symbol(curr.symbol)
        prev_center = _voicing_center(prev_symbol, (voicings_by_bar or {}).get(prev.bar))
        curr_center = _voicing_center(curr_symbol, (voicings_by_bar or {}).get(curr.bar))
        if prev_center is not None and curr_center is not None:
            shift = abs(curr_center - prev_center)
            if shift > limit:
                violations.append(
                    f"bar {prev.bar}->{curr.bar}: {prev_symbol} -> {curr_symbol} "
                    f"shift={shift:.1f} frets (limit {limit:.0f})"
                )
        else:
            prev_cat = _chord_category(prev_symbol)
            curr_cat = _chord_category(curr_symbol)
            cost = float(_transition_cost(prev_cat, curr_cat))
            threshold = 2.0 if mode == "playable" else 3.0
            if cost > threshold:
                violations.append(
                    f"bar {prev.bar}->{curr.bar}: {prev_symbol} -> {curr_symbol} "
                    f"cost={cost:.2f} (category-fallback)"
                )
        if len(violations) >= 3:
            break

    if violations:
        report.hard_violations.append(
            "H4: Chord transition exceeds mode position-shift limit: "
            f"{', '.join(violations)}"
        )
        report.suggested_repairs.append(
            "H4 repair: Choose a closer voicing or substitute an easier same-function chord."
        )


def _voicing_center(symbol: str, frets: Optional[List[int]]) -> Optional[float]:
    """Fretted centre (mean fret of pressed strings; 0 for an all-open shape) of the voicing the learner
    will play: the given ACS frets, else the easiest library shape for the symbol."""
    try:
        from fretcase_engine.arrangement_solver import effective_voicing_difficulty, voicing_candidates_for_symbol
    except ImportError:  # pragma: no cover - script-mode import
        from arrangement_solver import effective_voicing_difficulty, voicing_candidates_for_symbol  # type: ignore
    if frets and len(frets) == 6:
        pressed = [int(f) for f in frets if int(f) > 0]
        return float(sum(pressed) / len(pressed)) if pressed else 0.0
    candidates = voicing_candidates_for_symbol(symbol)
    if not candidates:
        return None
    easiest = min(candidates, key=effective_voicing_difficulty)
    return float(easiest.position_center)


def _check_h5_melody_harmony_fit(
    graph: LeadSheetGraph,
    mode: Literal["playable", "sounding"],
    report: ConstraintReport,
) -> None:
    if not graph.melody or not graph.harmony:
        return

    harmony_by_bar: Dict[int, List[ChordEvent]] = {}
    for chord in graph.harmony:
        harmony_by_bar.setdefault(chord.bar, []).append(chord)
    for bar_events in harmony_by_bar.values():
        bar_events.sort(key=lambda event: event.start_beat)

    strong_total = 0
    strong_non_chord = 0
    sustained_strong_non_chord = 0
    mismatch_bars: Dict[int, int] = {}

    for note in graph.melody:
        if note.is_rest or not _is_strong_beat(note.start_beat):
            continue

        overlapping = _find_overlapping_chords(note, harmony_by_bar.get(note.bar, []))
        if not overlapping:
            continue

        strong_total += 1
        note_pc = _note_event_pc(note)
        if note_pc is None:
            continue

        is_chord_tone = any(note_pc in _chord_pcs(chord) for chord in overlapping)
        if is_chord_tone:
            continue

        strong_non_chord += 1
        mismatch_bars[note.bar] = mismatch_bars.get(note.bar, 0) + 1
        if note.duration_beats >= 1.0 - 1e-6:
            sustained_strong_non_chord += 1

    if strong_total < 4:
        return

    mismatch_ratio = strong_non_chord / strong_total
    sustained_ratio = sustained_strong_non_chord / strong_total
    hotspot_bars = ", ".join(str(bar) for bar, _ in sorted(
        mismatch_bars.items(),
        key=lambda item: (-item[1], item[0]),
    )[:3])

    hard_mismatch_threshold = 0.55 if mode == "playable" else 0.72
    hard_sustained_threshold = 0.45 if mode == "playable" else 0.58
    soft_mismatch_threshold = 0.35 if mode == "playable" else 0.45
    soft_sustained_threshold = 0.25 if mode == "playable" else 0.32

    if mismatch_ratio >= hard_mismatch_threshold or sustained_ratio >= hard_sustained_threshold:
        label = "Melody-harmony mismatch on strong beats is high"
        if mode == "sounding":
            label = "Strong-beat melody clashes exceed sounding-mode tolerance"
        report.hard_violations.append(
            f"H5: {label} "
            f"({strong_non_chord}/{strong_total}, sustained={sustained_strong_non_chord}). "
            f"Hotspot bars: {hotspot_bars or 'N/A'}."
        )
        if mode == "sounding":
            report.suggested_repairs.append(
                "H5 repair: Keep color tones, but move sharper clashes off strong beats or support them with a closer extension."
            )
        else:
            report.suggested_repairs.append(
                "H5 repair: Align strong-beat melody notes with chord tones or move non-chord tones to weak beats."
            )
    elif mismatch_ratio >= soft_mismatch_threshold or sustained_ratio >= soft_sustained_threshold:
        label = "Several strong-beat melody notes are non-chord tones"
        if mode == "sounding":
            label = "Several accented melody notes lean outside the supporting chord"
        report.soft_warnings.append(
            f"H5: {label} "
            f"({strong_non_chord}/{strong_total}). Hotspot bars: {hotspot_bars or 'N/A'}."
        )
        if mode == "sounding":
            report.suggested_repairs.append(
                "H5 suggestion: Jazz color is fine, but anchor the accented melody on chord tones or compatible extensions more often."
            )
        else:
            report.suggested_repairs.append(
                "H5 suggestion: Keep passing tones mainly on weak beats and reinforce chord tones on accents."
            )


def _bar_duration_totals(events) -> Dict[int, float]:
    totals: Dict[int, float] = {}
    for event in events:
        totals[event.bar] = totals.get(event.bar, 0.0) + event.duration_beats
    return totals


def _beats_per_bar(meter: str) -> float:
    try:
        num, denom = meter.split("/")
        return float(Fraction(int(num), int(denom)) * 4)
    except (ValueError, ZeroDivisionError):
        return 4.0


def _normalize_chord_symbol(symbol: str) -> str:
    raw = (symbol or "").strip().replace(" ", "")
    if not raw:
        return "N.C."

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


PLAYABLE_QUALITIES = {"", "m", "7", "dim"}
EXPLORE_QUALITIES = PLAYABLE_QUALITIES | {"maj7", "m7", "sus2", "sus4", "add9", "6"}
SOUNDING_QUALITIES = PLAYABLE_QUALITIES | {"maj7", "m7", "m9", "9", "11", "13", "sus2", "sus4", "add9", "aug", "6"}


_SCALE_STEPS = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10, 11)}  # minor: + raised leading tone


def _key_root_pcs(graph: LeadSheetGraph) -> Optional[Set[int]]:
    """Pitch classes that are diatonic chord roots in the score's key (harmonic-minor leading tone included)."""
    key = graph.key or {}
    tonic = str(key.get("tonic") or "").strip()
    if not tonic:
        return None
    tonic_pc = _name_to_pc(tonic[:2] if len(tonic) > 1 and tonic[1] in "#b" else tonic[:1])
    if tonic_pc is None:
        return None
    mode = "minor" if str(key.get("mode") or "").lower().startswith("min") else "major"
    return {(tonic_pc + step) % 12 for step in _SCALE_STEPS[mode]}


def _is_allowed_chord_symbol(
    normalized_symbol: str,
    mode: Literal["playable", "sounding"],
    lane: Optional[Lane] = None,
    key_roots: Optional[Set[int]] = None,
) -> bool:
    """H3 vocabulary.  Basic: triads, dominant sevenths and diminished chords on the key's own scale degrees
    (F#m in D major is basic vocabulary; whether its shape is playable is the solver's job, not H3's).
    Explore: adds the cautious colours (maj7, m7, sus, add9, 6) on any root.  Colour / sounding: extended
    chords.  Without a key the basic lane falls back to natural-note roots."""
    match = re.match(r"^([A-G](?:#|b)?)(.*)$", normalized_symbol)
    if not match:
        return False

    root, quality = match.group(1), match.group(2)

    if lane == "color" or mode == "sounding":
        return quality in SOUNDING_QUALITIES
    if lane == "explore":
        return quality in EXPLORE_QUALITIES
    if key_roots is not None:
        root_ok = _name_to_pc(root) in key_roots
    else:
        root_ok = root in {"A", "B", "C", "D", "E", "F", "G"}
    return root_ok and quality in PLAYABLE_QUALITIES


def _chord_category(normalized_symbol: str) -> str:
    match = re.match(r"^([A-G](?:#|b)?)(.*)$", normalized_symbol)
    if not match:
        return "barre"

    root, quality = match.group(1), match.group(2)

    open_like = {
        "C", "Cm", "D", "Dm", "E", "Em", "F", "Fm", "G", "Gm", "A", "Am",
        "A7", "B7", "C7", "D7", "E7", "F7", "G7",
    }
    if f"{root}{quality}" in open_like:
        return "open"

    if "#" in root or "b" in root:
        return "barre"

    if quality in {"maj7", "m7", "m9", "9", "11", "13", "sus2", "sus4", "add9", "aug"}:
        return "extension"

    if root in {"B"} and quality in {"", "m"}:
        return "barre"

    return "open"


def _transition_cost(from_category: str, to_category: str) -> int:
    if from_category == "barre" and to_category == "barre":
        return 3

    level = {"open": 0, "extension": 1, "barre": 2}
    from_level = level.get(from_category, 2)
    to_level = level.get(to_category, 2)
    return max(from_level, to_level)


def _is_strong_beat(start_beat: float, tolerance: float = 1e-3) -> bool:
    rounded = round(start_beat)
    if abs(start_beat - rounded) > tolerance:
        return False
    return rounded in {0, 1, 2, 3}


def _find_overlapping_chords(note: NoteEvent, chords: List[ChordEvent]) -> List[ChordEvent]:
    note_start = note.start_beat
    note_end = note.start_beat + note.duration_beats
    if note_end <= note_start:
        note_end = note_start + 1e-6

    overlap_rows = []
    for chord in chords:
        chord_start = chord.start_beat
        chord_end = chord.start_beat + chord.duration_beats
        overlap = min(note_end, chord_end) - max(note_start, chord_start)
        if overlap > 1e-6:
            overlap_rows.append((chord, overlap))

    overlap_rows.sort(key=lambda item: item[1], reverse=True)
    return [item[0] for item in overlap_rows]


def _note_event_pc(note: NoteEvent) -> Optional[int]:
    if note.midi is not None:
        return int(note.midi) % 12
    match = re.match(r"^([A-G](?:#|b)?)", str(note.pitch or ""))
    if not match:
        return None
    return _name_to_pc(match.group(1))


def _chord_pcs(chord: ChordEvent) -> Set[int]:
    pcs: Set[int] = set()
    for name in chord.notes:
        match = re.match(r"^([A-G](?:#|b)?)", str(name or ""))
        if not match:
            continue
        note_pc = _name_to_pc(match.group(1))
        if note_pc is not None:
            pcs.add(note_pc)
    return pcs


def _name_to_pc(name: str) -> Optional[int]:
    normalized = str(name or "").strip()
    pc_map = {
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
    return pc_map.get(normalized)
