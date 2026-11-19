"""Guitar rhythm: choosing a preset from density, and turning a preset plus chord voicings into notes.

New FretCase code, written from the behaviour of FretStudio's ``client/src/lib/rhythmRealization.ts``:
strumming steps ``D`` and ``U`` sound the chord for one step, ``-``/``X``/``C``/``P`` are rests; arpeggio
tokens are ``T`` (lowest sounding string), digits for strings (1 = high E ... 6 = low E; several digits sound
together) and ``-``/``X`` rests. The grid has ``subdivisions`` steps per bar (12 is a triplet grid).
Differences from the ABC version: notes come from the real voicing's strings (plus the capo fret), and a
strummed chord rings until the next hit instead of being followed by a written rest.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fretcase_engine.arrangement_solver import STANDARD_TUNING_MIDI
from fretcase_engine.common import bar_ticks, meter_text

LEVELS = ("start", "next", "challenge")


def _presets_path() -> Path:
    env = os.environ.get("FRETCASE_RHYTHM_PRESETS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "shared" / "data" / "rhythm-presets.json"


@lru_cache(maxsize=1)
def load_presets() -> Dict[str, Any]:
    return json.loads(_presets_path().read_text(encoding="utf-8"))


def presets_by_id() -> Dict[str, Dict[str, Any]]:
    return {p["id"]: p for p in load_presets()["presets"]}


def level_for_density(density: float) -> str:
    return LEVELS[0] if density < 1 / 3 else (LEVELS[1] if density < 2 / 3 else LEVELS[2])


def available_levels(meter: str, family: str) -> List[str]:
    return [lv for lv in LEVELS if any(p["meter"] == meter and p["family"] == family and p["level"] == lv for p in load_presets()["presets"])]


def nearest_level(requested: str, available: Sequence[str]) -> Optional[str]:
    """The requested level if present, else the nearest one that exists (ties go to the easier level)."""
    if not available:
        return None
    if requested in available:
        return requested
    idx = LEVELS.index(requested)
    return min(available, key=lambda lv: (abs(LEVELS.index(lv) - idx), LEVELS.index(lv)))


def choose_preset(meter: Dict[str, int], density: float, family: str = "strumming") -> Dict[str, Any]:
    """Preset for a density value. The density third picks the level (nearest existing level for the meter); the
    position inside the third picks among that level's presets, so turning the knob inside a third still varies."""
    text = meter_text(meter)
    level = nearest_level(level_for_density(density), available_levels(text, family))
    if level is None:
        family = "arpeggio" if family == "strumming" else "strumming"
        level = nearest_level(level_for_density(density), available_levels(text, family))
    pool = [p for p in load_presets()["presets"] if p["meter"] == text and p["family"] == family and p["level"] == level]
    third = min(2, int(density * 3)) if density < 1 else 2
    fraction = min(0.999, max(0.0, density * 3 - third))
    return pool[min(len(pool) - 1, int(fraction * len(pool)))]


def _string_pitches(voicing: Dict[str, Any], capo_fret: int) -> List[Optional[int]]:
    out: List[Optional[int]] = []
    for idx, fret in enumerate(voicing["frets"]):
        out.append(None if fret < 0 else STANDARD_TUNING_MIDI[idx] + int(fret) + capo_fret)
    return out


def _arpeggio_tokens(picking: str, subdivisions: int) -> List[str]:
    cleaned = picking.strip()
    if " " in cleaned:
        tokens = [t for t in cleaned.split() if t]
    else:
        tokens = [c.upper() for c in cleaned.replace("|", "") if c in "TtXx-123456"]
    if not tokens:
        return ["-"] * subdivisions
    return [tokens[i % len(tokens)] for i in range(subdivisions)]


def realise(chords: Sequence[Dict[str, Any]], preset: Dict[str, Any], meter: Dict[str, int], capo_fret: int = 0, section_end: Optional[int] = None) -> List[Dict[str, Any]]:
    """Guitar notes for the chord events (dicts with start, duration, voicing) using ``preset``."""
    bt = bar_ticks(meter)
    subdivisions = int(preset["subdivisions"])
    step = bt / subdivisions
    notes: List[Dict[str, Any]] = []
    for chord in chords:
        voicing = chord.get("voicing")
        if not voicing:
            continue
        pitches = _string_pitches(voicing, capo_fret)
        sounding = [i for i, p in enumerate(pitches) if p is not None]
        if not sounding:
            continue
        c_start, c_end = int(chord["start"]), int(chord["start"]) + int(chord["duration"])
        first_bar = c_start // bt
        last_bar = (c_end - 1) // bt
        for bar in range(first_bar, last_bar + 1):
            hits: List[tuple] = []  # (tick, [pitches], velocity)
            for s in range(subdivisions):
                tick = int(round(bar * bt + s * step))
                if tick < c_start or tick >= c_end:
                    continue
                if preset["family"] == "strumming":
                    token = preset["steps"][s % len(preset["steps"])]
                    if token not in ("D", "U"):
                        continue
                    chosen = [pitches[i] for i in sounding]
                    if token == "U":
                        chosen = chosen[-4:]  # upstrokes catch the higher strings
                    hits.append((tick, chosen, (100 if s == 0 else 88) if token == "D" else 70))
                else:
                    token = _arpeggio_tokens(preset["picking"], subdivisions)[s]
                    if token in ("-", "X"):
                        continue
                    if token == "T":
                        chosen = [pitches[sounding[0]]]
                    else:
                        chosen = []
                        for ch in token:
                            if ch not in "123456":
                                continue
                            want = 6 - int(ch)  # string 6 = low E = index 0
                            nearest = min(sounding, key=lambda i: (abs(i - want), i))
                            if pitches[nearest] not in chosen:
                                chosen.append(pitches[nearest])
                    if chosen:
                        hits.append((tick, chosen, 92 if s == 0 else 78))
            bar_end = min((bar + 1) * bt, c_end)
            for index, (tick, chosen, velocity) in enumerate(hits):
                if preset["family"] == "strumming":
                    until = hits[index + 1][0] if index + 1 < len(hits) else bar_end
                else:
                    until = min(tick + int(step * 2), bar_end) if index + 1 >= len(hits) else min(hits[index + 1][0], tick + int(step * 2))
                for pitch in chosen:
                    notes.append({"start": tick, "duration": max(1, until - tick), "pitch": int(pitch), "velocity": velocity})
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes
