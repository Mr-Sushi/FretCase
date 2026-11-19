"""Melody for a new song: from the hummed motif, or from the offline melody generator.

New FretCase code (not ported). Notes are dictionaries ``{"start", "duration", "pitch", "velocity"}`` in ticks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fretcase_engine.chord_spelling import NAME_TO_PC
from fretcase_engine.common import TPQ, bar_ticks, key_text, meter_text
from fretcase_engine.music_representation import parse_abc_to_graph
from fretcase_engine.offline_melody import generate_offline_melody

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
MELODY_LOW, MELODY_HIGH = 57, 88  # A3 .. E6, comfortable singing and piano range

Note = Dict[str, Any]


def scale_pcs(key: Dict[str, str]) -> List[int]:
    tonic = NAME_TO_PC[key["tonic"]]
    return [(tonic + step) % 12 for step in (MINOR_SCALE if key["mode"] == "minor" else MAJOR_SCALE)]


def snap_to_scale(pitch: int, key: Dict[str, str]) -> int:
    """Nearest scale tone (ties go down). Minor keys also accept the raised leading tone."""
    pcs = set(scale_pcs(key))
    if key["mode"] == "minor":
        pcs.add((NAME_TO_PC[key["tonic"]] + 11) % 12)
    for distance in range(0, 7):
        for candidate in (pitch - distance, pitch + distance):
            if candidate % 12 in pcs:
                return candidate
    return pitch


def scale_degree_index(pitch: int, key: Dict[str, str]) -> int:
    """Position of the pitch on the key's scale as a running step count (octave * 7 + degree)."""
    snapped = snap_to_scale(pitch, key)
    tonic = NAME_TO_PC[key["tonic"]]
    scale = MINOR_SCALE if key["mode"] == "minor" else MAJOR_SCALE
    rel = (snapped - tonic) % 12
    degree = min(range(7), key=lambda i: abs(scale[i] - rel))
    octave = (snapped - tonic - scale[degree]) // 12
    return octave * 7 + degree


def pitch_from_degree_index(index: int, key: Dict[str, str]) -> int:
    tonic = NAME_TO_PC[key["tonic"]]
    scale = MINOR_SCALE if key["mode"] == "minor" else MAJOR_SCALE
    octave, degree = divmod(index, 7)
    return tonic + scale[degree] + 12 * octave


def shift_diatonic(notes: Sequence[Note], steps: int, key: Dict[str, str]) -> List[Note]:
    out = []
    for note in notes:
        index = scale_degree_index(int(note["pitch"]), key) + steps
        pitch = max(0, min(127, pitch_from_degree_index(index, key)))
        out.append({**note, "pitch": pitch})
    return out


def _clean(note: Note) -> Note:
    out = {"start": int(note["start"]), "duration": max(1, int(note["duration"])), "pitch": int(note["pitch"])}
    out["velocity"] = int(note.get("velocity", 90))
    return out


def clip_notes(notes: Sequence[Note], start: int, end: int) -> List[Note]:
    """Notes starting in [start, end), shortened to end at ``end``."""
    out = []
    for note in notes:
        if start <= note["start"] < end:
            clipped = _clean(note)
            clipped["duration"] = max(1, min(clipped["duration"], end - clipped["start"]))
            out.append(clipped)
    return out


def place_into_octave(notes: Sequence[Note], key: Dict[str, str], low: int = MELODY_LOW, high: int = MELODY_HIGH) -> List[Note]:
    """Move the whole phrase by octaves so that it sits inside [low, high] as far as possible."""
    if not notes:
        return []
    pitches = [n["pitch"] for n in notes]
    shift = 0
    while max(pitches) + shift > high and min(pitches) + shift - 12 >= low - 2:
        shift -= 12
    while min(pitches) + shift < low and max(pitches) + shift + 12 <= high + 2:
        shift += 12
    return [{**n, "pitch": n["pitch"] + shift} for n in notes]


def offline_notes(key: Dict[str, str], meter: Dict[str, int], tempo: float, bars: int, variant: int = 0, seed_text: str = "") -> List[Note]:
    """Melody from FretStudio's offline generator, converted to ticks. 2/4 is written in 4/4 and re-barred."""
    text = meter_text(meter)
    gen_meter, gen_bars = text, bars
    if text == "2/4":
        gen_meter, gen_bars = "4/4", (bars + 1) // 2
    abc = generate_offline_melody(key=key_text(key), meter=gen_meter, tempo=int(tempo), length=max(1, gen_bars), variant=variant, seed_text=seed_text)
    graph = parse_abc_to_graph(abc)
    gen_bar_ticks = {"4/4": 4 * TPQ, "3/4": 3 * TPQ, "6/8": 3 * TPQ}[gen_meter]
    notes: List[Note] = []
    for event in graph.melody:
        if event.is_rest or event.midi is None:
            continue
        start = int(round(((event.bar - 1) * gen_bar_ticks) + event.start_beat * TPQ))
        duration = int(round(event.duration_beats * TPQ))
        notes.append({"start": start, "duration": duration, "pitch": int(event.midi), "velocity": 90})
    end = bars * bar_ticks(meter)
    return clip_notes(notes, 0, end)


def _motif_cell(motif: Sequence[Note], bt: int) -> tuple[List[Note], int]:
    cleaned = sorted((_clean(n) for n in motif), key=lambda n: (n["start"], n["pitch"]))
    last_end = max(n["start"] + n["duration"] for n in cleaned)
    cell_bars = max(1, -(-last_end // bt))
    return cleaned, cell_bars


def motif_notes(motif: Sequence[Note], key: Dict[str, str], meter: Dict[str, int], sections: Sequence[Dict[str, Any]], bars: int) -> List[Note]:
    """Fit a hummed motif to the section plan.

    The motif (a cell of whole bars) is repeated to fill each section: the opening states it as hummed, the
    development moves it up a scale step, the climax up a third (two steps), and the ending states it again
    and lands on the tonic. Every note is snapped to the key; repeats are cut at the section end.
    """
    bt = bar_ticks(meter)
    cell, cell_bars = _motif_cell(motif, bt)
    cell = [{**n, "pitch": snap_to_scale(n["pitch"], key)} for n in cell]
    shifts = [0, 1, 2, 0]
    out: List[Note] = []
    for index, section in enumerate(sections):
        shift = shifts[min(index, len(shifts) - 1)] if len(sections) > 1 else 0
        if index == len(sections) - 1 and len(sections) > 1:
            shift = 0
        section_start, section_end = section["startBar"] * bt, section["endBar"] * bt
        shifted = shift_diatonic(cell, shift, key) if shift else cell
        position = section_start
        while position < section_end:
            for note in shifted:
                start = position + note["start"]
                if start < section_end:
                    out.append({**note, "start": start, "duration": min(note["duration"], section_end - start)})
            position += cell_bars * bt
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    if out:
        out = _end_on_tonic(out, key, bars * bt, bt)
    return out


def _end_on_tonic(notes: List[Note], key: Dict[str, str], length: int, bt: int) -> List[Note]:
    last = notes[-1]
    tonic_pc = NAME_TO_PC[key["tonic"]]
    candidates = [last["pitch"] + d for d in range(-6, 7) if (last["pitch"] + d) % 12 == tonic_pc]
    if candidates:
        last = {**last, "pitch": min(candidates, key=lambda p: abs(p - notes[-1]["pitch"]))}
    last["duration"] = max(1, length - last["start"])
    return notes[:-1] + [last]


def build_melody(
    seed: Dict[str, Any],
    key: Dict[str, str],
    meter: Dict[str, int],
    tempo: float,
    bars: int,
    sections: Sequence[Dict[str, Any]],
    variant: int = 0,
    seed_text: str = "",
) -> List[Note]:
    motif = seed.get("motif") or []
    if motif:
        return motif_notes(motif, key, meter, sections, bars)
    return place_into_octave(offline_notes(key, meter, tempo, bars, variant, seed_text), key)


def fit_hum_to_key(notes: Sequence[Note], key: Dict[str, str], length: int, bt: int) -> List[Note]:
    """Transpose a new hum into the song's key and fit it to ``length`` ticks (one section).

    The hum's own key centre is estimated from the pitch classes it uses (best major or minor scale fit, tonic
    weighted); it is moved to the song's tonic by the smallest shift, snapped to the key, and repeated or cut
    to fill the section.
    """
    if not notes:
        return []
    cleaned, cell_bars = _motif_cell(notes, bt)
    weights = [0.0] * 12
    for n in cleaned:
        weights[n["pitch"] % 12] += n["duration"]
    best_pc, best_score = 0, -1.0
    for pc in range(12):
        score = sum(weights[(pc + step) % 12] for step in MAJOR_SCALE) + 0.5 * weights[pc] + 0.25 * weights[(pc + 7) % 12]
        if score > best_score:
            best_pc, best_score = pc, score
    hum_tonic = best_pc  # treated as the tonic of the hum, in the song's mode
    target = NAME_TO_PC[key["tonic"]]
    shift = (target - hum_tonic) % 12
    if shift > 6:
        shift -= 12
    moved = [{**n, "pitch": snap_to_scale(n["pitch"] + shift, key)} for n in cleaned]
    moved = place_into_octave(moved, key)
    out: List[Note] = []
    position = 0
    while position < length:
        for n in moved:
            start = position + n["start"]
            if start < length:
                out.append({**n, "start": start, "duration": min(n["duration"], length - start)})
        position += cell_bars * bt
    return out
