"""Pluggable harmony candidate sources.

The harmony pipeline is: candidate source -> HRE (harmonic evidence) -> ACS (guitar realisation).
The candidate source only has to produce *planner hypotheses*: for each lane (style) and each bar, a
short ranked list of chord symbols plus a phrase role and function hint.  Three sources exist:

  llm      HarmonyTheoryAgent (GPT) returns the planner JSON            (original behaviour)
  library  common-progression library matched to the melody, no LLM     (reviewer R3's alternative)
  rule     the symbolic defaults only (equivalent to planner_payload=None)
  hybrid   llm, falling back to library when the model is unavailable or returns no parseable plan

All sources emit the same planner-payload shape consumed by
``harmony_reranker.build_symbolic_harmony_candidates``:

    {"primary_key": {"tonic": "C", "mode": "major", "confidence": 0.8},
     "plans": [{"style": "traditional", "summary": "...", "intent": "...",
                "bars": [{"bar": 1, "phrase_role": "start", "function_hint": "T",
                          "candidate_chords": ["C", "Am", "F"]}, ...]}, ...]}

Selecting a source: request field ``harmony_source`` > env ``FRETSTUDIO_HARMONY_SOURCE`` > "llm".
When no model API key is configured the effective source is forced to ``library``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from fretcase_engine.harmony_reasoning import (
        MelodyEvent,
        anchor_pitch_classes,
        build_melody_events_by_bar,
        derive_candidate_from_symbol,
        infer_phrase_roles,
        name_to_pc,
    )
    from fretcase_engine.chord_spelling import spell_pc
    from fretcase_engine.learner_model import normalize_chord_symbol
    from fretcase_engine.music_representation import parse_abc_to_graph
except ImportError:  # pragma: no cover - script-mode import
    from harmony_reasoning import (  # type: ignore
        MelodyEvent,
        anchor_pitch_classes,
        build_melody_events_by_bar,
        derive_candidate_from_symbol,
        infer_phrase_roles,
        name_to_pc,
    )
    from chord_spelling import spell_pc  # type: ignore
    from learner_model import normalize_chord_symbol  # type: ignore
    from music_representation import parse_abc_to_graph  # type: ignore

HARMONY_SOURCES = ("llm", "library", "rule", "hybrid")
LIBRARY_PATH = Path(__file__).resolve().parent / "data" / "progression_library.json"
MAJOR_DEGREE_PC = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
MINOR_DEGREE_PC = {1: 0, 2: 2, 3: 3, 4: 5, 5: 7, 6: 8, 7: 10}
MAJOR_DIATONIC = {1: "", 2: "m", 3: "m", 4: "", 5: "", 6: "m", 7: "dim"}
MINOR_DIATONIC = {1: "m", 2: "dim", 3: "", 4: "m", 5: "m", 6: "", 7: ""}
FUNCTION_OF_DEGREE_MAJOR = {1: "T", 2: "PD", 3: "T", 4: "PD", 5: "D", 6: "T", 7: "D"}
FUNCTION_OF_DEGREE_MINOR = {1: "T", 2: "PD", 3: "T", 4: "PD", 5: "D", 6: "PD", 7: "D"}


def resolve_harmony_source(requested: Optional[str], api_key_present: bool) -> str:
    """Decide which candidate source to use for this request."""
    value = (requested or os.getenv("FRETSTUDIO_HARMONY_SOURCE") or "llm").strip().lower()
    if value not in HARMONY_SOURCES:
        value = "llm"
    if not api_key_present and value in {"llm", "hybrid"}:
        return "library"
    return value


@dataclass
class LibraryProgression:
    id: str
    name: str
    degrees: List[str]
    styles: List[str]
    weight: float


def _load_library() -> Dict[str, List[LibraryProgression]]:
    try:
        payload = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"major": [], "minor": []}
    out: Dict[str, List[LibraryProgression]] = {}
    for mode in ("major", "minor"):
        rows = []
        for row in payload.get(mode, []):
            try:
                rows.append(LibraryProgression(
                    id=str(row["id"]), name=str(row.get("name") or row["id"]),
                    degrees=[str(d) for d in row["degrees"]], styles=[str(s) for s in row.get("styles", [])],
                    weight=float(row.get("weight", 1.0)),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        out[mode] = rows
    return out


PROGRESSION_LIBRARY = _load_library()


def library_stats() -> Dict[str, object]:
    return {
        "path": str(LIBRARY_PATH.name),
        "major_progressions": len(PROGRESSION_LIBRARY.get("major", [])),
        "minor_progressions": len(PROGRESSION_LIBRARY.get("minor", [])),
    }


def _split_degree(token: str) -> Tuple[int, str]:
    """'57' -> (5, '7'); '6m7' -> (6, 'm7'); '1' -> (1, ''). Degrees are a single digit 1-7."""
    token = str(token).strip()
    if not token or not token[0].isdigit():
        return 1, token
    return int(token[0]), token[1:]


def degree_to_symbol(token: str, tonic: str, mode: str) -> str:
    degree, quality = _split_degree(token)
    is_minor = str(mode).lower() == "minor"
    pc_table = MINOR_DEGREE_PC if is_minor else MAJOR_DEGREE_PC
    default_quality = (MINOR_DIATONIC if is_minor else MAJOR_DIATONIC).get(degree, "")
    root_pc = (name_to_pc(tonic) + pc_table.get(degree, 0)) % 12
    # dominant seventh/major triad on 5 in minor is the conventional raised-leading-tone dominant
    if is_minor and degree == 5 and quality in {"7", ""} and token.endswith(("7", "5")):
        default_quality = "" if quality == "" and token == "5" else default_quality
    resolved_quality = quality if quality else default_quality
    if is_minor and degree == 5 and quality == "7":
        resolved_quality = "7"
    # key-aware spelling: iii in D major is F#m (not Gbm), IV in F major is Bb
    return normalize_chord_symbol(f"{spell_pc(root_pc, tonic, mode)}{resolved_quality}")


def _function_for(symbol: str, tonic: str, mode: str) -> str:
    try:
        return derive_candidate_from_symbol(symbol, tonic=tonic, mode=mode).function
    except Exception:
        return "T"


def _melody_support(symbol: str, events: Sequence[MelodyEvent], tonic: str, mode: str) -> float:
    """Weighted share of melody notes (by beat strength and duration) that are chord tones."""
    if not events:
        return 0.5
    try:
        chord = derive_candidate_from_symbol(symbol, tonic=tonic, mode=mode)
    except Exception:
        return 0.0
    total = 0.0
    hit = 0.0
    for event in events:
        weight = 0.6 * event.beat_strength + 0.4 * event.duration_norm
        total += weight
        if event.pitch_class in chord.chord_tones:
            hit += weight
    return hit / total if total > 0 else 0.0


def _diatonic_pool(tonic: str, mode: str, style: str) -> List[str]:
    is_minor = str(mode).lower() == "minor"
    table = MINOR_DIATONIC if is_minor else MAJOR_DIATONIC
    pool = [degree_to_symbol(f"{deg}{qual}", tonic, mode) for deg, qual in table.items()]
    if style == "jazz":
        pool += [degree_to_symbol(tok, tonic, mode) for tok in (["1maj7", "2m7", "3m7", "4maj7", "57", "6m7"] if not is_minor else ["1m7", "4m7", "57", "6maj7", "3maj7"])]
    elif style == "pop":
        pool += [degree_to_symbol(tok, tonic, mode) for tok in (["57", "6m7", "2m7"] if not is_minor else ["57", "1m7"])]
    unique: List[str] = []
    for symbol in pool:
        if symbol and symbol not in unique:
            unique.append(symbol)
    return unique


def build_library_planner_payload(
    melody_abc: str,
    style_targets: Sequence[str],
    key_hint: Optional[str] = None,
    learner_profile: Optional[Dict[str, object]] = None,
    user_goal: str = "",
) -> Dict[str, object]:
    """Planner hypotheses from the progression library, re-ranked per bar by melody support."""
    graph = parse_abc_to_graph(melody_abc)
    events_by_bar = build_melody_events_by_bar(graph)
    bar_count = len(events_by_bar)
    tonic = str((graph.key or {}).get("tonic") or (key_hint or "C").rstrip("m") or "C")
    mode = str((graph.key or {}).get("mode") or ("minor" if (key_hint or "").endswith("m") else "major"))
    if key_hint:
        hint = key_hint.strip()
        if hint.endswith("m") and len(hint) > 1:
            tonic, mode = hint[:-1], "minor"
        elif hint:
            tonic, mode = hint, "major"
    anchors = anchor_pitch_classes(events_by_bar)
    phrase_roles = infer_phrase_roles(bar_count)
    known = {normalize_chord_symbol(str(c)) for c in ((learner_profile or {}).get("known_chords") or [])}
    styles = [str(s) for s in style_targets] or ["traditional", "pop", "jazz"]
    progressions = PROGRESSION_LIBRARY.get(mode, []) or PROGRESSION_LIBRARY.get("major", [])
    func_table = FUNCTION_OF_DEGREE_MINOR if mode == "minor" else FUNCTION_OF_DEGREE_MAJOR

    plans: List[Dict[str, object]] = []
    for style in styles:
        eligible = [p for p in progressions if style in p.styles] or progressions
        # Score each progression by melody support over the whole phrase (cycled to bar_count),
        # with a small bonus for chords the learner already knows (Basic lane only).
        scored: List[Tuple[float, LibraryProgression, List[str]]] = []
        for prog in eligible:
            symbols = [degree_to_symbol(prog.degrees[i % len(prog.degrees)], tonic, mode) for i in range(bar_count)]
            if bar_count >= 2:
                # close on the tonic when the phrase ends on a tonic-chord tone (last note) or the
                # final bar is mostly tonic chord tones
                final_events = events_by_bar[-1]
                tonic_symbol = degree_to_symbol("1m" if mode == "minor" else "1", tonic, mode)
                try:
                    tonic_tones = derive_candidate_from_symbol(tonic_symbol, tonic=tonic, mode=mode).chord_tones
                except Exception:
                    tonic_tones = set()
                ends_on_tonic_tone = bool(final_events) and final_events[-1].pitch_class in tonic_tones
                if ends_on_tonic_tone or _melody_support(tonic_symbol, final_events, tonic, mode) >= 0.5:
                    symbols[-1] = tonic_symbol
            support = sum(_melody_support(sym, events_by_bar[i], tonic, mode) for i, sym in enumerate(symbols)) / max(bar_count, 1)
            familiarity = (sum(1 for sym in symbols if sym in known) / bar_count) if (known and style == "traditional") else 0.0
            scored.append((0.75 * support + 0.15 * prog.weight + 0.10 * familiarity, prog, symbols))
        scored.sort(key=lambda row: -row[0])
        best_score, best_prog, best_symbols = scored[0] if scored else (0.0, None, [])
        pool = _diatonic_pool(tonic, mode, style)
        bars: List[Dict[str, object]] = []
        for index in range(bar_count):
            events = events_by_bar[index]
            primary = best_symbols[index] if index < len(best_symbols) else degree_to_symbol("1", tonic, mode)
            # alternatives: diatonic chords ranked by melody support, excluding the primary
            ranked_alts = sorted(
                (sym for sym in pool if sym != primary),
                key=lambda sym: (-_melody_support(sym, events, tonic, mode), 0 if sym in known else 1),
            )
            candidates = [primary] + ranked_alts[:2]
            degree_token = best_prog.degrees[index % len(best_prog.degrees)] if best_prog else "1"
            degree, _ = _split_degree(degree_token)
            function_hint = func_table.get(degree, "T")
            if phrase_roles[index] == "ending_authentic":
                function_hint = "T"
            bars.append({
                "bar": index + 1,
                "phrase_role": phrase_roles[index],
                "function_hint": function_hint,
                "candidate_chords": candidates,
            })
        plans.append({
            "style": style,
            "summary": f"{best_prog.name} ({best_prog.id})" if best_prog else "diatonic default",
            "intent": (f"Library progression '{best_prog.id}' chosen for melody support {best_score:.2f}" if best_prog else "diatonic default") + (f"; goal: {user_goal}" if user_goal else ""),
            "source": "library",
            "bars": bars,
        })
    return {
        "primary_key": {"tonic": tonic, "mode": mode, "confidence": 0.6, "source": "key_signature"},
        "alternate_keys": [],
        "plans": plans,
        "source": "library",
    }
