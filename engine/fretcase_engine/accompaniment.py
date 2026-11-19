"""Bass and drums from the harmony, the meter and the density level. New FretCase code (simple rules)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fretcase_engine.chord_spelling import NAME_TO_PC
from fretcase_engine.common import TPQ, bar_ticks, meter_text
from fretcase_engine.harmony_reasoning import parse_symbol_root_and_quality
from fretcase_engine.rhythm import level_for_density

KICK, SNARE, HAT, OPEN_HAT, RIDE = 36, 38, 42, 46, 51
BASS_LOW, BASS_HIGH = 36, 47  # C2 .. B2


def _bass_root(symbol: str) -> int:
    root, _ = parse_symbol_root_and_quality(symbol.split("/")[0])
    pc = NAME_TO_PC.get(root, 0)
    return BASS_LOW + pc


def _fifth(root_pitch: int) -> int:
    fifth = root_pitch + 7
    return fifth if fifth <= BASS_HIGH + 7 else fifth - 12


def bass_notes(chords: Sequence[Dict[str, Any]], meter: Dict[str, int], density: float) -> List[Dict[str, Any]]:
    """Root-based bass. start: the root held per half bar (whole bar in 2/4); next: root on every beat with the
    fifth on the second half; challenge: eighth-note root-fifth-octave figure."""
    level = level_for_density(density)
    bt = bar_ticks(meter)
    text = meter_text(meter)
    notes: List[Dict[str, Any]] = []
    for chord in chords:
        root = _bass_root(chord["symbol"])
        fifth = _fifth(root)
        c_start, c_end = int(chord["start"]), int(chord["start"]) + int(chord["duration"])
        for bar in range(c_start // bt, (c_end - 1) // bt + 1):
            b0 = bar * bt
            if text == "6/8":
                grid = [(0, root, 720), (720, fifth if level != "start" else root, 720)]
                if level == "challenge":
                    grid = [(i * 240, [root, fifth, root + 12, root, fifth, root + 12][i], 240) for i in range(6)]
            elif text == "3/4":
                grid = [(0, root, TPQ), (TPQ, fifth, TPQ), (2 * TPQ, fifth, TPQ)] if level != "start" else [(0, root, 3 * TPQ)]
                if level == "challenge":
                    grid = [(i * 240, [root, fifth, root + 12][i % 3], 240) for i in range(6)]
            elif text == "2/4":
                grid = [(0, root, 2 * TPQ)] if level == "start" else [(0, root, TPQ), (TPQ, fifth, TPQ)]
                if level == "challenge":
                    grid = [(i * 240, [root, fifth, root + 12, fifth][i % 4], 240) for i in range(4)]
            else:  # 4/4
                if level == "start":
                    grid = [(0, root, 2 * TPQ), (2 * TPQ, root, 2 * TPQ)]
                elif level == "next":
                    grid = [(0, root, TPQ), (TPQ, root, TPQ), (2 * TPQ, fifth, TPQ), (3 * TPQ, root, TPQ)]
                else:
                    grid = [(i * 240, [root, root, fifth, root + 12, fifth, root, fifth, root][i], 240) for i in range(8)]
            for offset, pitch, duration in grid:
                start = b0 + offset
                if c_start <= start < c_end:
                    notes.append({"start": start, "duration": min(duration, c_end - start), "pitch": int(pitch), "velocity": 96 if offset == 0 else 80})
    return notes


def drum_notes(first_bar: int, last_bar: int, meter: Dict[str, int], density: float, variation: int = 0, fills: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Drums for bars [first_bar, last_bar). ``variation`` changes the fill and accent pattern (another take).
    ``fills``: None keeps the milestone 1 rule; False has no fills; True ends the range with a fill."""
    level = level_for_density(density)
    bt = bar_ticks(meter)
    text = meter_text(meter)
    notes: List[Dict[str, Any]] = []

    def hit(bar_start: int, offset: int, pitch: int, velocity: int) -> None:
        notes.append({"start": bar_start + offset, "duration": 120, "pitch": pitch, "velocity": velocity})

    for bar in range(first_bar, last_bar):
        b0 = bar * bt
        eighth = TPQ // 2
        if text == "4/4":
            kicks = [0, 2 * TPQ] if level == "start" else [0, 2 * TPQ, 2 * TPQ + eighth]
            if level == "challenge":
                kicks = [0, TPQ + eighth, 2 * TPQ + eighth * 1, 3 * TPQ + eighth] if variation % 2 else [0, eighth * 3, 2 * TPQ, 2 * TPQ + eighth * 3]
            snares = [TPQ, 3 * TPQ]
            hats = [i * TPQ for i in range(4)] if level == "start" else [i * eighth for i in range(8)]
        elif text == "3/4":
            kicks, snares = [0], [TPQ, 2 * TPQ]
            hats = [i * TPQ for i in range(3)] if level == "start" else [i * eighth for i in range(6)]
        elif text == "2/4":
            kicks, snares = [0], [TPQ]
            hats = [0, TPQ] if level == "start" else [i * eighth for i in range(4)]
        else:  # 6/8
            kicks, snares = [0], [3 * eighth]
            hats = [0, 3 * eighth] if level == "start" else [i * eighth for i in range(6)]
        for offset in kicks:
            hit(b0, offset, KICK, 100 if offset == 0 else 85)
        for offset in snares:
            hit(b0, offset, SNARE, 90)
        for index, offset in enumerate(hats):
            hit(b0, offset, HAT, 78 if index % 2 == 0 else 62)
        fill_here = (variation % 3 == 1 and bar % 4 == 3) if fills is None else (fills and bar == last_bar - 1)
        if fill_here:  # fill in the last bar of each phrase
            span = bt // 4
            for i in range(4):
                hit(b0, bt - span + i * (span // 4), SNARE, 70 + 6 * i)
        if fills is None and variation % 3 == 2 and bar % 4 == 0:
            hit(b0, 0, OPEN_HAT, 70)
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes
