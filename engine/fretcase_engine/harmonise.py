"""Harmony for a FretCase song: library and rule candidates, ranked by HRE, voiced by ACS, with the capo rule.

New FretCase code that replaces FretStudio's ``harmony_reranker`` (not ported: it is bound to ABC strings and
learner profiles). It calls the ported modules unchanged: ``candidate_sources`` (progression library),
``harmony_reasoning`` (candidate bank, HRE scoring, beam search), ``arrangement_solver`` (ACS voicing path),
and ``capo`` (capo choice and the barre-avoidance preference).

One chord per bar. Everything is deterministic for the same input.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fretcase_engine.arrangement_solver import (
    VoicingCandidate,
    build_acs_learner,
    build_default_constraint_spec,
    build_default_voicing_inventory,
    effective_voicing_difficulty,
    feasible_voicings_for_step,
    solve_fixed_progression,
    voicing_library_fingerprint,
)
from fretcase_engine.candidate_sources import (
    FUNCTION_OF_DEGREE_MAJOR,
    FUNCTION_OF_DEGREE_MINOR,
    PROGRESSION_LIBRARY,
    _diatonic_pool,
    _melody_support,
    _split_degree,
    degree_to_symbol,
)
from fretcase_engine.capo import capo_for_key, prefer_capo_row, transpose_symbol
from fretcase_engine.chord_spelling import NAME_TO_PC, enharmonic_key, parse_key
from fretcase_engine.common import TPQ, bar_ticks, beats_per_bar
from fretcase_engine.expert_runtime import load_runtime_expert_signals
from fretcase_engine.harmony_reasoning import (
    ChordCandidate,
    MelodyEvent,
    anchor_pitch_classes,
    apply_llm_hints,
    beam_search_chord_sequences,
    beat_strength_for_offset,
    build_candidate_bank,
    build_hre_contexts,
    clamp01,
    derive_candidate_from_symbol,
    harmonic_cap_from_payload,
    infer_phrase_roles,
    name_to_pc,
    parse_symbol_root_and_quality,
)
from fretcase_engine.learner_model import normalize_chord_symbol

LANES = ("basic", "explore", "colour")
LANE_STYLE = {"basic": "traditional", "explore": "pop", "colour": "jazz"}
LANE_ACS = {"basic": "basic", "explore": "explore", "colour": "color"}

Note = Dict[str, Any]


def lane_for_complexity(value: float) -> str:
    return "basic" if value < 1 / 3 else ("explore" if value < 2 / 3 else "colour")


@dataclass
class ChordPick:
    symbol: str  # sounding symbol, spelled for the song key
    shape_symbol: Optional[str]  # shape fretted under the capo; None without a capo
    roman: str
    function: str
    voicing: VoicingCandidate  # frets relative to the capo (the nut when there is none)


@dataclass
class HarmonyCandidate:
    picks: List[ChordPick]
    score: float
    arrangement_score: float
    relaxation: int
    substitutions: Tuple[Dict[str, Any], ...] = ()
    capo: Optional[Dict[str, Any]] = None

    @property
    def signature(self) -> Tuple[str, ...]:
        return tuple(p.symbol for p in self.picks)

    # duck-typing for capo.prefer_capo_row
    @property
    def voicing_seq(self) -> List[VoicingCandidate]:
        return [p.voicing for p in self.picks]

    @property
    def acs_relaxation(self) -> int:
        return self.relaxation


def _events_by_bar(notes: Sequence[Note], meter: Dict[str, int], start_bar: int, end_bar: int, shift: int = 0) -> List[List[MelodyEvent]]:
    bt = bar_ticks(meter)
    rows: List[List[MelodyEvent]] = []
    for bar in range(start_bar, end_bar):
        window = [n for n in notes if bar * bt <= n["start"] < (bar + 1) * bt]
        longest = max((n["duration"] for n in window), default=TPQ)
        row = []
        for n in sorted(window, key=lambda x: (x["start"], x["duration"])):
            offset_beats = (n["start"] - bar * bt) / TPQ
            row.append(MelodyEvent(
                pitch_class=(int(n["pitch"]) + shift) % 12,
                beat_strength=beat_strength_for_offset(offset_beats),
                duration_norm=clamp01(n["duration"] / max(longest, 1)),
            ))
        rows.append(row)
    return rows


def _library_plan(events_by_bar: Sequence[Sequence[MelodyEvent]], tonic: str, mode: str, roles: Sequence[str], style: str) -> List[Dict[str, Any]]:
    """Per-bar candidate chords from the progression library, re-ranked by melody support.

    Adapted from ``candidate_sources.build_library_planner_payload`` without the ABC detour."""
    bar_count = len(events_by_bar)
    progressions = PROGRESSION_LIBRARY.get(mode, []) or PROGRESSION_LIBRARY.get("major", [])
    func_table = FUNCTION_OF_DEGREE_MINOR if mode == "minor" else FUNCTION_OF_DEGREE_MAJOR
    eligible = [p for p in progressions if style in p.styles] or progressions
    best = None
    for prog in eligible:
        symbols = [degree_to_symbol(prog.degrees[i % len(prog.degrees)], tonic, mode) for i in range(bar_count)]
        support = sum(_melody_support(sym, events_by_bar[i], tonic, mode) for i, sym in enumerate(symbols)) / max(bar_count, 1)
        score = 0.85 * support + 0.15 * prog.weight
        if best is None or score > best[0]:
            best = (score, prog, symbols)
    pool = _diatonic_pool(tonic, mode, style)
    bars = []
    for index in range(bar_count):
        events = events_by_bar[index]
        primary = best[2][index] if best else degree_to_symbol("1", tonic, mode)
        alts = sorted((s for s in pool if s != primary), key=lambda s: -_melody_support(s, events, tonic, mode))
        degree, _ = _split_degree(best[1].degrees[index % len(best[1].degrees)]) if best else (1, "")
        bars.append({"candidates": [primary] + alts[:2], "function_hint": func_table.get(degree, "T")})
    return bars


def _basic_allowed(tonic: str, mode: str) -> set:
    from fretcase_engine.chord_spelling import spell_pc

    tonic_pc = name_to_pc(tonic)
    specs = [(0, "m"), (3, ""), (5, "m"), (7, ""), (8, ""), (10, "")] if mode == "minor" else [(0, ""), (2, "m"), (4, "m"), (5, ""), (7, ""), (9, "m")]
    return {enharmonic_key(normalize_chord_symbol(f"{spell_pc(tonic_pc + i, tonic, mode)}{q}")) for i, q in specs}


def _tonic_only(pool: List[ChordCandidate], tonic: str, mode: str, style: str) -> List[ChordCandidate]:
    quals = ({"m"} if mode == "minor" else {""}) if style == "traditional" else ({"m", "m7", "m9"} if mode == "minor" else {"", "maj7", "6", "add9"})
    kept = []
    for c in pool:
        root, quality = parse_symbol_root_and_quality(c.symbol)
        if name_to_pc(root) == name_to_pc(tonic) and quality in quals:
            kept.append(c)
    if kept:
        return kept
    return [derive_candidate_from_symbol(normalize_chord_symbol(f"{tonic}{'m' if mode == 'minor' else ''}"), tonic=tonic, mode=mode)]


def _minor_share(symbols: Sequence[str]) -> float:
    if not symbols:
        return 0.5
    minor = 0
    for s in symbols:
        _, quality = parse_symbol_root_and_quality(s)
        if quality.startswith("m") and not quality.startswith("maj"):
            minor += 1
    return minor / len(symbols)


def brightness_bias(brightness: float) -> float:
    """-1 (darker) .. 0 (neutral third) .. +1 (brighter), per the thirds in docs/api.md."""
    if brightness < 1 / 3:
        return -(1 / 3 - brightness) * 3
    if brightness >= 2 / 3:
        return (brightness - 2 / 3) * 3
    return 0.0


def _solve(
    events: List[List[MelodyEvent]],
    roles: Sequence[str],
    tonic: str,
    mode: str,
    lane: str,
    bright: float,
    first_bar_is_song_start: bool,
    last_bar_is_song_end: bool,
    shape_capo: Optional[Dict[str, Any]],
    top_n: int,
    avoid_voicings: Optional[Dict[str, set]] = None,
    fixed_symbols: Optional[Sequence[str]] = None,
) -> List[HarmonyCandidate]:
    """Candidates in the key given by ``tonic``/``mode`` (the shape key when a capo is used)."""
    style = LANE_STYLE[lane]
    render_mode = "sounding" if lane == "colour" else "playable"
    skill = "beginner" if lane == "basic" else "early_intermediate"
    allow_barre = skill == "early_intermediate"
    n = len(events)
    melody_pcs = anchor_pitch_classes(events)
    plan = _library_plan(events, tonic, mode, roles, style)
    cap = harmonic_cap_from_payload({"skill_level": skill})
    contexts = build_hre_contexts(n, tonic, mode, style, [b["function_hint"] for b in plan], roles, cap)
    bank = build_candidate_bank(tonic=tonic, mode=mode, style=style, render_mode=render_mode)
    allowed = _basic_allowed(tonic, mode) if lane == "basic" else None
    pools: List[List[ChordCandidate]] = []
    for i, bar in enumerate(plan):
        pool = apply_llm_hints(bank, bar["candidates"], tonic, mode, bar["function_hint"], basic_only=(lane == "basic"))
        if allowed is not None:
            filtered = [c for c in pool if enharmonic_key(c.symbol) in allowed]
            pool = filtered or pool
        if i == 0 and first_bar_is_song_start:
            pool = _tonic_only(pool, tonic, mode, style)
        if i == n - 1 and last_bar_is_song_end and n >= 2:
            pool = _tonic_only(pool, tonic, mode, style)
        pools.append(pool)
    if fixed_symbols is not None:
        pools = [[derive_candidate_from_symbol(normalize_chord_symbol(s), tonic=tonic, mode=mode)] for s in fixed_symbols]
    signals = load_runtime_expert_signals()
    hre_weights = signals.get("hre_weights") if isinstance(signals, dict) else None
    paths = beam_search_chord_sequences(events, pools, contexts, tonic, mode, beam_width=16, per_step_limit=6, hre_weights=hre_weights)
    spec = build_default_constraint_spec(render_mode=render_mode, style=style, allow_barre=allow_barre, lane=LANE_ACS[lane])
    learner = build_acs_learner(skill_level=skill, render_mode=render_mode, lane=LANE_ACS[lane])
    inventory = build_default_voicing_inventory()
    if avoid_voicings:
        inventory = {
            sym: ([v for v in vs if v.frets not in avoid_voicings.get(sym, set())] or vs) for sym, vs in inventory.items()
        }
    out: Dict[Tuple[str, ...], HarmonyCandidate] = {}
    bias = brightness_bias(bright)
    for avg_score, path in paths:
        symbols = [d.chord.symbol for d in path]
        result = solve_fixed_progression(symbols, melody_pcs, spec, learner, lane=LANE_ACS[lane], inventory=inventory)
        if not result["available"]:
            # repair: the failed bars fall back to the tonic chord, which always has an open shape
            failed = set(result.get("failed_bars") or [])
            tonic_symbol = normalize_chord_symbol(f"{tonic}{'m' if mode == 'minor' else ''}")
            symbols = [tonic_symbol if (i + 1) in failed else s for i, s in enumerate(symbols)]
            result = solve_fixed_progression(symbols, melody_pcs, spec, learner, lane=LANE_ACS[lane], inventory=inventory)
            if not result["available"]:
                continue
            path = [replace(d, chord=derive_candidate_from_symbol(s, tonic=tonic, mode=mode)) if d.chord.symbol != s else d for d, s in zip(path, symbols)]
        picks = []
        for detail, symbol, voicing in zip(path, symbols, result["voicing_seq"]):
            picks.append(ChordPick(symbol=symbol, shape_symbol=None, roman=detail.roman, function=detail.function, voicing=voicing))
        score = 0.6 * avg_score + 0.4 * clamp01(result["arrangement_score"])
        score -= 0.12 * bias * (2 * _minor_share(symbols) - 1)  # darker (bias < 0) rewards minor chords
        subs = tuple(
            {"bar": i + 1, "reason": "no_playable_shape"}
            for i, (a, b) in enumerate(zip([d.chord.symbol for d in path], symbols)) if a != b
        )
        cand = HarmonyCandidate(picks=picks, score=score, arrangement_score=float(result["arrangement_score"]), relaxation=int(result["relaxation"]), substitutions=subs)
        key = tuple(symbols)
        if key not in out or out[key].score < cand.score:
            out[key] = cand
    ranked = sorted(out.values(), key=lambda c: -c.score)
    return ranked[:top_n]


def _to_sounding(cands: List[HarmonyCandidate], capo: Dict[str, Any], tonic: str, mode: str) -> List[HarmonyCandidate]:
    fret = int(capo["fret"])
    mapped = []
    for cand in cands:
        picks = [
            ChordPick(symbol=transpose_symbol(p.symbol, fret, tonic, mode), shape_symbol=p.symbol, roman=p.roman, function=p.function, voicing=p.voicing)
            for p in cand.picks
        ]
        mapped.append(replace(cand, picks=picks, capo=capo))
    return mapped


def harmonise(
    notes: Sequence[Note],
    key: Dict[str, str],
    meter: Dict[str, int],
    total_bars: int,
    start_bar: int = 0,
    end_bar: Optional[int] = None,
    lane: str = "basic",
    brightness: float = 0.5,
    capo: Optional[Dict[str, Any]] = None,
    top_n: int = 8,
    avoid_voicings: Optional[Dict[str, set]] = None,
    fixed_symbols: Optional[Sequence[str]] = None,
) -> List[HarmonyCandidate]:
    """Ranked, distinct harmonisations of bars [start_bar, end_bar), one chord per bar.

    ``capo`` is a dict from ``capo.capo_for_key`` (the caller decides whether to use it): the melody is moved
    down by the capo fret into the shape key, solved there with open shapes, and mapped back to sounding chords.
    The phrase structure is taken from the whole song so a middle section does not close on a final cadence."""
    end_bar = total_bars if end_bar is None else end_bar
    roles = infer_phrase_roles(total_bars)[start_bar:end_bar]
    tonic, mode = key["tonic"], key["mode"]
    shift = 0
    solve_tonic = tonic
    if capo:
        shift = -int(capo["fret"])
        solve_tonic, _ = parse_key(str(capo["shape_key"]))
    events = _events_by_bar(notes, meter, start_bar, end_bar, shift=shift)
    cands = _solve(
        events, roles, solve_tonic, mode, lane, brightness,
        first_bar_is_song_start=(start_bar == 0), last_bar_is_song_end=(end_bar == total_bars),
        shape_capo=capo, top_n=top_n, avoid_voicings=avoid_voicings, fixed_symbols=fixed_symbols,
    )
    if capo:
        cands = _to_sounding(cands, capo, tonic, mode)
    return cands


def choose_capo(
    notes: Sequence[Note],
    key: Dict[str, str],
    meter: Dict[str, int],
    total_bars: int,
    lane: str,
    brightness: float,
) -> Tuple[Optional[Dict[str, Any]], List[HarmonyCandidate]]:
    """The capo rule: for barre-heavy keys solve once plainly and once in the capo's shape key, and keep the capo
    version when ``capo.prefer_capo_row`` says it needs fewer barre-avoiding substitutions or is clearly easier to
    fret. Returns (capo or None, ranked candidates for the whole song)."""
    plain = harmonise(notes, key, meter, total_bars, lane=lane, brightness=brightness, capo=None)
    suggestion = capo_for_key(f"{key['tonic']}m" if key["mode"] == "minor" else key["tonic"])
    if not suggestion:
        return None, plain
    shaped = harmonise(notes, key, meter, total_bars, lane=lane, brightness=brightness, capo=suggestion)
    if prefer_capo_row(plain[0] if plain else None, shaped[0] if shaped else None):
        return suggestion, shaped
    return None, plain


def capo_to_song(capo: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not capo:
        return None
    return {"fret": int(capo["fret"]), "shapeKey": str(capo["shape_key"]), "soundingKey": str(capo["sounding_key"]), "reason": str(capo["reason"])}


def voicing_to_song(voicing: VoicingCandidate) -> Dict[str, Any]:
    fingers = list(voicing.fingers) if len(voicing.fingers) == 6 else [0] * 6
    return {
        "frets": [int(f) for f in voicing.frets],
        "fingers": [max(0, min(4, int(f))) for f in fingers],
        "barres": sorted({int(b) for b in voicing.barres if 1 <= int(b) <= 15}),
        "baseFret": int(voicing.base_fret),
        "difficulty": round(float(effective_voicing_difficulty(voicing)), 3),
    }


def chord_events(picks: Sequence[ChordPick], meter: Dict[str, int], start_bar: int) -> List[Dict[str, Any]]:
    bt = bar_ticks(meter)
    events = []
    for i, pick in enumerate(picks):
        event: Dict[str, Any] = {"start": (start_bar + i) * bt, "duration": bt, "symbol": pick.symbol}
        if pick.shape_symbol:
            event["shapeSymbol"] = pick.shape_symbol
        if pick.roman:
            event["roman"] = pick.roman
        if pick.function in {"T", "PD", "D", "COLOR"}:
            event["function"] = pick.function
        event["voicing"] = voicing_to_song(pick.voicing)
        events.append(event)
    return events


def provenance() -> Dict[str, Any]:
    signals = load_runtime_expert_signals()
    return {
        "voicingLibrary": voicing_library_fingerprint(),
        "hreCalibration": str((signals or {}).get("calibration_version", "none")) if isinstance(signals, dict) else "none",
        "harmonySource": "library",
    }
