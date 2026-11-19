"""Capo-aware arrangement.

Keys full of barre chords (Bb, Eb, F#m, Bm ...) are played by beginners with a capo and open shapes:
Bb major = capo on fret 3 + G-key shapes.  The harmony pipeline (HRE + ACS) therefore runs once more on the
melody transposed down into the shape key, where the learner's open shapes exist, and the result is mapped
back: the score (V:2) and ``bar_analysis[*].symbol`` stay in sounding pitch, while everything the learner
reads as a fingering (shape names, diagrams, known / new chords, practice plan) uses the shapes, with the
capo acting as the nut — the convention of guitar song books ("Capo 3: G C D Em").
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from fretcase_engine.chord_spelling import NAME_TO_PC, parse_key, spell_pc
    from fretcase_engine.music_representation import graph_to_abc, parse_abc_to_graph
except ImportError:  # pragma: no cover - script-mode import
    from chord_spelling import NAME_TO_PC, parse_key, spell_pc  # type: ignore
    from music_representation import graph_to_abc, parse_abc_to_graph  # type: ignore

# keys whose I, IV and V (or i, iv, V) have open beginner shapes, most common first
OPEN_SHAPE_KEYS = {"major": ["G", "C", "D", "A", "E"], "minor": ["Em", "Am", "Dm"]}
MAX_CAPO_FRET = 7
_ROOT_RE = re.compile(r"^([A-G][#b]?)(.*)$")


def key_name(tonic: str, mode: str) -> str:
    return f"{tonic} {'minor' if mode == 'minor' else 'major'}"


def capo_for_key(key_text: str) -> Optional[Dict[str, Any]]:
    """Capo position whose open shapes sound in this key, or None for open-shape keys.

    Prefers the most common shape keys (G, C, Am, Em ...) and low frets: score = rank + 0.6 * fret."""
    tonic, mode = parse_key(key_text)
    shapes = OPEN_SHAPE_KEYS[mode]
    tonic_pc = NAME_TO_PC[tonic]
    if any(NAME_TO_PC[shape.rstrip("m")] == tonic_pc for shape in shapes):
        return None
    best: Optional[Tuple[float, int, str]] = None
    for fret in range(1, MAX_CAPO_FRET + 1):
        shape_pc = (tonic_pc - fret) % 12
        for rank, shape in enumerate(shapes):
            if NAME_TO_PC[shape.rstrip("m")] == shape_pc:
                score = rank + 0.6 * fret
                if best is None or score < best[0]:
                    best = (score, fret, shape)
    if best is None:
        return None
    _, fret, shape = best
    sounding = key_name(tonic, mode)
    return {
        "fret": fret,
        "shape_key": shape,
        "sounding_key": f"{tonic}m" if mode == "minor" else tonic,
        "reason": f"{sounding} needs several barre chords; with a capo on fret {fret} the {shape}-key shapes sound in {sounding}.",
        # kept for the summary's older field name
        "capo": fret,
        "text": f"{sounding} needs several barre chords. With a capo on fret {fret}, {shape}-key shapes sound in {sounding}.",
    }


def transpose_symbol(symbol: str, semitones: int, tonic: str, mode: str) -> str:
    """Chord symbol moved by `semitones` and spelled for the target key (G + 3 in Bb major -> Bb)."""
    raw = str(symbol or "").strip()
    match = _ROOT_RE.match(raw)
    if not match or match.group(1) not in NAME_TO_PC:
        return raw
    suffix = match.group(2)
    bass = ""
    if "/" in suffix:
        suffix, _, bass_text = suffix.partition("/")
        bass_match = _ROOT_RE.match(bass_text.strip())
        if bass_match and bass_match.group(1) in NAME_TO_PC:
            bass = "/" + spell_pc(NAME_TO_PC[bass_match.group(1)] + semitones, tonic, mode) + bass_match.group(2)
    return spell_pc(NAME_TO_PC[match.group(1)] + semitones, tonic, mode) + suffix + bass


def transpose_melody_abc(abc: str, semitones: int, target_key: str) -> str:
    """Melody-only ABC moved by `semitones` into `target_key` (used to solve the arrangement in the shape key)."""
    graph = parse_abc_to_graph(abc)
    tonic, mode = parse_key(target_key)
    melody = [
        replace(note, midi=int(note.midi) + int(semitones)) if note.midi is not None and not note.is_rest else note
        for note in graph.melody
    ]
    shifted = replace(graph, melody=melody, harmony=[], key={**(graph.key or {}), "tonic": tonic, "mode": mode})
    text = graph_to_abc(shifted)
    return text.split("\nV:2", 1)[0].rstrip() + "\n"


_NOTE_IN_REASON = re.compile(r"(melody note )([A-G][#b]?)")


def _sounding_reason(text: str, capo: int, shape_tonic: str, tonic: str, mode: str) -> str:
    """Move note names and the key in a verified reason from the shape key to the sounding key."""
    out = _NOTE_IN_REASON.sub(lambda m: m.group(1) + spell_pc(NAME_TO_PC.get(m.group(2), 0) + capo, tonic, mode), str(text))
    return out.replace(f" in {key_name(shape_tonic, mode)}", f" in {key_name(tonic, mode)}")


def shape_row_to_sounding(
    row: Any,
    capo: Dict[str, Any],
    melody_abc: str,
    melody_graph: Any,
    render_v2,
) -> Any:
    """A HarmonyPlanCandidate solved in the shape key, re-expressed in sounding pitch.

    ``render_v2(melody_abc, style, key_hypothesis, voicing_seq, melody_graph)`` writes the V:2 ABC."""
    fret = int(capo["fret"])
    tonic, mode = parse_key(str(capo["sounding_key"]))
    shape_tonic, _ = parse_key(str(capo["shape_key"]))
    sounding_voicings = []
    for voicing in row.voicing_seq:
        sounding_voicings.append(
            replace(
                voicing,
                chord_symbol=transpose_symbol(voicing.chord_symbol, fret, tonic, mode),
                chord_root=transpose_symbol(voicing.chord_root, fret, tonic, mode),
                pitch_list=[int(p) + fret for p in voicing.pitch_list],
                pitch_classes={(int(pc) + fret) % 12 for pc in voicing.pitch_classes},
                top_note_pc=(int(voicing.top_note_pc) + fret) % 12,
            )
        )
    key_hypothesis = {**(row.key_hypothesis or {}), "tonic": tonic, "mode": mode, "capo": fret, "shape_key": capo["shape_key"]}
    bar_rows: List[Dict[str, Any]] = []
    for bar in row.bar_analysis:
        shape_symbol = str(bar.get("symbol") or "")
        voicing = dict(bar.get("voicing") or {})
        voicing["capo"] = fret
        voicing["shape_symbol"] = shape_symbol
        bar_rows.append({
            **bar,
            "symbol": transpose_symbol(shape_symbol, fret, tonic, mode),
            "shape_symbol": shape_symbol,
            "capo": fret,
            "verified_reasons": [_sounding_reason(r, fret, shape_tonic, tonic, mode) for r in (bar.get("verified_reasons") or [])],
            "voicing": voicing,
        })
    return replace(
        row,
        abc_v2=render_v2(melody_abc, row.style, key_hypothesis, sounding_voicings, melody_graph),
        voicing_seq=sounding_voicings,
        key_hypothesis=key_hypothesis,
        bar_analysis=bar_rows,
    )


def capo_policy(learner_profile_payload: Optional[Dict[str, Any]]) -> str:
    """'allow' (default) or 'never', from learner_profile.capo or learner_profile.preferences.capo."""
    payload = learner_profile_payload or {}
    raw = payload.get("capo")
    if raw is None and isinstance(payload.get("preferences"), dict):
        raw = payload["preferences"].get("capo")
    value = str(raw or "allow").strip().lower()
    return "never" if value == "never" else "allow"


def substitution_count(row: Any) -> int:
    return sum(1 for sub in (getattr(row, "substitutions", ()) or ()) if isinstance(sub, dict) and sub.get("reason") == "no_playable_shape")


# mean effective voicing difficulty (0..1) that counts as clearly easier: open shapes are ~0.2, barre
# voicings ~0.4-0.6, so a lane full of barres versus the same lane in open shapes differs by 0.15-0.3
CLEAR_DIFFICULTY_MARGIN = 0.05


def mean_fretting_difficulty(row: Any) -> float:
    """Mean effective difficulty of the voicings as fretted (use the shape-key row for a capo version)."""
    try:
        from fretcase_engine.arrangement_solver import effective_voicing_difficulty
    except ImportError:  # pragma: no cover - script-mode import
        from arrangement_solver import effective_voicing_difficulty  # type: ignore
    values = [effective_voicing_difficulty(voicing) for voicing in (getattr(row, "voicing_seq", None) or [])]
    return sum(values) / len(values) if values else 1.0


def prefer_capo_row(plain: Optional[Any], capo_row: Optional[Any]) -> bool:
    """Use the capo version (``capo_row`` = the row solved in the shape key) when the plain version is missing,
    needs more barre-avoiding substitutions, or — with as many substitutions — is clearly harder to fret
    (a Color lane of movable barre 7ths in Bb versus open 7th shapes with capo 3).  Otherwise fewer melody-note
    relaxations decide, and when nothing is gained the plain version (no capo) is kept."""
    if capo_row is None:
        return False
    if plain is None:
        return True
    subs_capo, subs_plain = substitution_count(capo_row), substitution_count(plain)
    if subs_capo != subs_plain:
        return subs_capo < subs_plain
    difficulty_capo, difficulty_plain = mean_fretting_difficulty(capo_row), mean_fretting_difficulty(plain)
    if abs(difficulty_capo - difficulty_plain) >= CLEAR_DIFFICULTY_MARGIN:
        return difficulty_capo < difficulty_plain
    relax_capo, relax_plain = getattr(capo_row, "acs_relaxation", 0), getattr(plain, "acs_relaxation", 0)
    return relax_capo < relax_plain


def capo_of_rows(rows: Sequence[Dict[str, Any]]) -> int:
    """Capo fret recorded on bar_analysis rows (0 when none)."""
    for row in rows or []:
        try:
            fret = int(row.get("capo") or (row.get("voicing") or {}).get("capo") or 0)
        except (TypeError, ValueError, AttributeError):
            fret = 0
        if fret > 0:
            return fret
    return 0


def shape_key_for(sounding_key: str, fret: int) -> Tuple[str, str]:
    """(shape tonic, mode) for a sounding key played with a capo on `fret` (Bb, 3 -> ('G', 'major'))."""
    tonic, mode = parse_key(sounding_key)
    suggestion = capo_for_key(sounding_key)
    if suggestion and int(suggestion["fret"]) == int(fret):
        shape_tonic, _ = parse_key(str(suggestion["shape_key"]))
        return shape_tonic, mode
    shape_pc = (NAME_TO_PC[tonic] - int(fret)) % 12
    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return names[shape_pc], mode


def to_shape(symbol: str, fret: int, shape_tonic: str, mode: str) -> str:
    """Sounding chord -> the shape fretted with a capo on `fret` (Bb with capo 3 -> G)."""
    return transpose_symbol(symbol, -int(fret), shape_tonic, mode) if fret else symbol
