"""One authoritative, explainable summary per harmony candidate.

The frontend used to compute its own "playability" (which, in sounding mode, *rose* with every extra
seventh chord) and a second learner-fit number that disagreed with the backend's.  This module derives
every figure the interface shows from what the pipeline actually decided:

* ``musical_fit``  mean HRE total over the bars (how well each chord fits melody, function, phrase, learner)
* ``playability``  from the voicings ACS chose for *this* learner: shape comfort of chords the learner does
                   not know yet (difficulty relative to the learner's cap; known chords count as comfortable)
                   and the comfort of each chord change (hand shift and fingers that stay down, see
                   ``chord_changes``), minus a small penalty when the relaxed constraint set was needed:
                   ``100 * (0.4 * mean(shape) + 0.2 * min(shape) + 0.4 * mean(change)) - 6 * relaxation``
* ``learner_fit``  the learner-model score (known-chord coverage, complexity, change cost, constraint issues)
* ``chords``       known / new / stretch (a "new chord to learn" kept on purpose by the one-at-a-time policy)
* ``hardest_change`` and plain-language ``reasons`` built from HRE's verified reasons and ACS facts.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

try:
    from fretcase_engine.arrangement_solver import build_acs_learner
    from fretcase_engine.chord_changes import change_metrics
    from fretcase_engine.capo import capo_for_key
    from fretcase_engine.chord_spelling import ChordSet
    from fretcase_engine.learner_model import LearnerProfile, normalize_chord_symbol, score_harmony_for_learner
except ImportError:  # pragma: no cover - script-mode import
    from arrangement_solver import build_acs_learner  # type: ignore
    from chord_changes import change_metrics  # type: ignore
    from capo import capo_for_key  # type: ignore
    from chord_spelling import ChordSet  # type: ignore
    from learner_model import LearnerProfile, normalize_chord_symbol, score_harmony_for_learner  # type: ignore

LANE_LABELS = {"basic": "Basic", "explore": "Explore", "color": "Color"}
STYLE_TO_LANE = {"traditional": "basic", "pop": "explore", "jazz": "color"}
FUNCTION_NAMES = {"T": "tonic", "PD": "predominant", "D": "dominant"}


def resolve_tier(meta: Dict[str, Any]) -> str:
    """Complexity tier the solver assigned to the realised chords (used for the ACS difficulty caps)."""
    tier = str(meta.get("decision_tier") or "").strip().lower()
    if tier == "colour":
        tier = "color"
    if tier in LANE_LABELS:
        return tier
    return STYLE_TO_LANE.get(str(meta.get("style") or "").strip().lower(), "basic")


def resolve_lane(meta: Dict[str, Any]) -> str:
    """Lane the candidate is offered as in the interface (traditional = Basic, pop = Explore, jazz = Color)."""
    style = str(meta.get("style") or "").strip().lower()
    if style in STYLE_TO_LANE:
        return STYLE_TO_LANE[style]
    return resolve_tier(meta)


def playability_label(value: float) -> str:
    if value >= 75:
        return "Comfortable"
    if value >= 55:
        return "Some stretch"
    return "Challenging"


def _unique(symbols: Sequence[str]) -> List[str]:
    out: List[str] = []
    for symbol in symbols:
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def _bar_frets(row: Dict[str, Any]) -> Optional[List[int]]:
    voicing = row.get("voicing") if isinstance(row.get("voicing"), dict) else {}
    frets = voicing.get("frets")
    if isinstance(frets, list) and len(frets) == 6:
        return [int(f) for f in frets]
    return None


def capo_suggestion(key_text: str) -> Optional[Dict[str, Any]]:
    """For keys full of barre chords (Bb, Eb, F#m, Bm ...): the capo position whose open shapes sound in this key
    (None for open-shape keys).  Same rule as the capo arrangement in ``server/capo.py``."""
    return capo_for_key(key_text)


def plain_constraint_issue(text: str) -> str:
    """Learner-facing wording for a constraint-engine violation (H1-H5 codes are for the research log)."""
    code, _, detail = str(text or "").partition(":")
    detail = detail.strip()
    if code == "H4":
        match = re.search(r"bar (\d+)->(\d+): (\S+) -> (\S+) shift=([\d.]+)", detail)
        if match:
            return (f"Check: the change {match.group(3)} → {match.group(4)} (bars {match.group(1)}–{match.group(2)}) "
                    f"jumps about {round(float(match.group(5)))} frets along the neck.")
        return "Check: one chord change needs a big jump along the neck."
    if code == "H5":
        bars = re.search(r"Hotspot bars: ([\d, ]+)", detail)
        where = f" (most in bars {bars.group(1).strip().rstrip(',')})" if bars else ""
        return f"Check: the melody and the chords clash on many strong beats{where}."
    if code == "H3":
        return "Check: some chords are outside this option's chord vocabulary — " + detail.split("vocabulary:", 1)[-1].strip() + "."
    if code == "H2":
        return "Check: some melody notes are outside the key."
    if code == "H1":
        return "Check: " + (detail or "some bars do not add up to the time signature") + "."
    return f"Check: {detail or text}."


def _bar_list(bars: Sequence[int]) -> str:
    bars = sorted(set(int(b) for b in bars))
    if len(bars) == 1:
        return f"bar {bars[0]}"
    return "bars " + ", ".join(str(b) for b in bars[:-1]) + f" and {bars[-1]}"


def _substitution_reasons(substitutions: Sequence[Any]) -> List[str]:
    """One line per (from, to) swap the solver made for playability, with the bars it applies to."""
    grouped: Dict[tuple, List[int]] = {}
    for sub in substitutions:
        if not isinstance(sub, dict) or sub.get("reason") not in {"no_playable_shape", "playable_dominant"}:
            continue
        grouped.setdefault((str(sub.get("reason")), str(sub.get("from")), str(sub.get("to"))), []).append(int(sub.get("bar") or 0))
    lines: List[str] = []
    for (reason, before, after), bars in grouped.items():
        if reason == "playable_dominant":
            lines.append(f"{after} instead of {before} ({_bar_list(bars)}): {before} needs a barre; {after} is the shape beginners learn first.")
        else:
            lines.append(f"{before} was replaced by {after} ({_bar_list(bars)}) because no shape for {before} fits your current level yet.")
    return lines


def summarize_candidate(
    meta: Dict[str, Any],
    abc: str,
    learner_payload: Optional[Dict[str, Any]],
    constraint_report: Optional[Dict[str, Any]] = None,
    render_mode: str = "playable",
) -> Dict[str, Any]:
    """Summary for one candidate; also annotates ``meta['bar_analysis']`` rows in place with
    ``known`` / ``new_chord`` / ``stretch`` flags."""
    bars: List[Dict[str, Any]] = [row for row in (meta.get("bar_analysis") or []) if isinstance(row, dict)]
    lane = resolve_lane(meta)
    tier = resolve_tier(meta)
    profile = LearnerProfile.from_payload(learner_payload)
    known = ChordSet(profile.known_chords or [])
    acs_meta = meta.get("acs") if isinstance(meta.get("acs"), dict) else {}
    stretch = ChordSet(normalize_chord_symbol(str(s)) for s in (acs_meta.get("stretch_symbols") or []))
    relaxation = int(acs_meta.get("relaxation") or 0)
    report = constraint_report or {}

    # capo arrangement: the learner frets the shapes (G, C, D) while the score sounds in the real key (Bb, Eb, F);
    # known / new chords, changes and the learner fit are about the shapes
    applied_capo = meta.get("capo") if isinstance(meta.get("capo"), dict) else None
    symbols = [normalize_chord_symbol(str((row.get("shape_symbol") if applied_capo else None) or row.get("symbol") or "")) for row in bars]
    learner_fit_row = score_harmony_for_learner(abc, profile, report, symbols=symbols if applied_capo else None)
    learner_fit = float(learner_fit_row.get("score", 0.0))

    for row, symbol in zip(bars, symbols):
        is_known = symbol in known if known else False
        row["known"] = bool(is_known)
        row["stretch"] = bool(symbol in stretch)
        row["new_chord"] = bool(known) and not is_known

    key_match = re.search(r"^K:\s*([^\n%]+)", abc or "", re.MULTILINE)
    capo = None if applied_capo else (capo_suggestion(key_match.group(1).strip()) if key_match else None)

    if not bars:
        # unanalysed fallback (the solver found no version playable at this level, typically in a barre key)
        reasons = ["The solver found no version of this option that fits your current level, so it is a plain template without checked shapes."]
        if capo:
            reasons.append(capo["text"])
        return {
            "lane": lane, "lane_label": LANE_LABELS[lane], "musical_fit": None, "playability": None,
            "playability_label": None, "learner_fit": round(learner_fit), "chords": {"known": [], "new": [], "stretch": []},
            "hardest_change": None, "relaxation": relaxation, "capo_suggestion": capo, "unverified": True,
            "constraints": {"hard": len(report.get("hard_violations") or []), "soft": len(report.get("soft_warnings") or [])},
            "reasons": (reasons + list(learner_fit_row.get("reasons") or []))[:4],
        }

    totals = [float((row.get("scores") or {}).get("total", 0.0)) for row in bars]
    musical_fit = 100.0 * sum(totals) / len(totals)

    acs_learner = build_acs_learner(
        skill_level=profile.skill_level, render_mode=render_mode, lane=tier, known_chords=sorted(known),
    )
    cap = max(acs_learner.max_difficulty, 0.05)
    shape_scores: List[float] = []
    for row, symbol in zip(bars, symbols):
        if symbol in known:
            shape_scores.append(1.0)
            continue
        difficulty = float(((row.get("voicing") or {}).get("difficulty")) or 0.0)
        threshold = 0.6 * cap
        shape_scores.append(max(0.0, min(1.0, 1.0 - max(0.0, difficulty - threshold) / threshold)))

    change_rows: List[Dict[str, Any]] = []
    for index in range(1, len(bars)):
        left, right = symbols[index - 1], symbols[index]
        if not left or not right or left == right:
            continue
        metrics = change_metrics(left, right, _bar_frets(bars[index - 1]), _bar_frets(bars[index]))
        if metrics is None:
            continue
        change_rows.append({
            "from_bar": int(bars[index - 1].get("bar") or index), "to_bar": int(bars[index].get("bar") or index + 1),
            "from": left, "to": right, "shift": metrics.shift, "common_fingers": metrics.anchors,
            "comfort": metrics.comfort, "describe": metrics.describe(),
        })
    change_scores = [row["comfort"] for row in change_rows] or [1.0]
    playability = 100.0 * (
        0.4 * (sum(shape_scores) / len(shape_scores)) + 0.2 * min(shape_scores) + 0.4 * (sum(change_scores) / len(change_scores))
    ) - 6.0 * relaxation
    playability = max(0.0, min(100.0, playability))

    hardest = min(change_rows, key=lambda row: (row["comfort"], row["from_bar"])) if change_rows else None
    hardest_change = None
    if hardest is not None:
        hardest_change = {
            "from_bar": hardest["from_bar"], "to_bar": hardest["to_bar"], "from": hardest["from"], "to": hardest["to"],
            "shift": hardest["shift"], "common_fingers": hardest["common_fingers"], "comfort": hardest["comfort"],
            "label": f"{hardest['from']} → {hardest['to']} (bars {hardest['from_bar']}–{hardest['to_bar']}): {hardest['describe']}",
        }

    unique_symbols = _unique(symbols)
    chords = {
        "known": [s for s in unique_symbols if s in known],
        "new": [s for s in unique_symbols if known and s not in known and s not in stretch],
        "stretch": [s for s in unique_symbols if s in stretch],
    }

    def named(index: int) -> str:
        """Chord name for a reason about the music: the sounding chord, plus the fretted shape under a capo."""
        shape = symbols[index]
        sounding = normalize_chord_symbol(str(bars[index].get("symbol") or "")) if applied_capo else shape
        return f"{sounding}, {shape} shape" if sounding and sounding != shape else shape

    noun = "chord shape" if applied_capo else "chord"  # known / new lists are fingerings (shapes) under a capo
    reasons: List[str] = []
    supported = sum(1 for row in bars if any("is a chord tone" in str(r) for r in (row.get("verified_reasons") or [])))
    reasons.append(f"In {supported} of {len(bars)} bars the main strong-beat melody note belongs to the chord.")
    last = bars[-1]
    last_function = str(last.get("function") or "")
    if last_function == "T":
        reasons.append(f"It ends on the tonic ({named(len(bars) - 1)}), so the tune sounds finished.")
    elif last_function == "D":
        reasons.append(f"It ends on the dominant ({named(len(bars) - 1)}), which leaves the phrase sounding open.")
    if known:
        if not chords["new"] and not chords["stretch"]:
            reasons.append(f"Every {noun} is one you already know.")
        else:
            parts = [f"uses {len(chords['known'])} {noun}{'s' if len(chords['known']) != 1 else ''} you know"]
            if chords["new"]:
                # same terms as the option card: "New for you" (within the learner's level) and "New chord to learn"
                # (the stretch chord above it, named below)
                parts.append(f"{len(chords['new'])} new for you: {', '.join(chords['new'])}")
            reasons.append(parts[0][0].upper() + parts[0][1:] + ("; " + parts[1] if len(parts) > 1 else "") + ".")
    for symbol in chords["stretch"]:
        reasons.append(
            f"New chord to learn: {symbol} (above your current level). It was kept because it fits the melody best here; "
            "its easiest shape is shown."
        )
    if hardest_change is not None and hardest_change["comfort"] < 0.7:
        reasons.append(f"Hardest change: {hardest_change['label']}.")
    reasons.extend(_substitution_reasons(acs_meta.get("substitutions") or [])[:2])
    if relaxation:
        reasons.append("To keep every shape playable, some melody notes are not doubled in the chord shapes.")
    if applied_capo:
        reasons.insert(0, str(applied_capo.get("reason") or f"Capo on fret {applied_capo.get('fret')}."))
    elif capo and playability < 75:
        reasons.append(capo["text"])
    hard = len(report.get("hard_violations") or [])
    soft = len(report.get("soft_warnings") or [])
    if hard:
        reasons.append(plain_constraint_issue(str((report.get("hard_violations") or [""])[0])))

    return {
        "lane": lane,
        "lane_label": LANE_LABELS[lane],
        "tier": tier,
        "musical_fit": round(musical_fit),
        "playability": round(playability),
        "playability_label": playability_label(playability),
        "learner_fit": round(learner_fit),
        "chords": chords,
        "hardest_change": hardest_change,
        "capo": applied_capo,
        "capo_suggestion": capo,
        "relaxation": relaxation,
        "constraints": {"hard": hard, "soft": soft},
        "reasons": reasons[:5],
        "learner_fit_detail": {
            "known_coverage": learner_fit_row.get("known_coverage"),
            "unknown_unique": learner_fit_row.get("unknown_unique"),
            "transition_cost": learner_fit_row.get("transition_cost"),
        },
    }
