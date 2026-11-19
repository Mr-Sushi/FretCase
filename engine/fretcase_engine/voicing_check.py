"""Check that a guitar voicing actually plays the chord it is labelled with.

Used by ``scripts/build_voicing_library.py`` (positions that fail are not imported) and by the test suite
(every voicing in the runtime inventory must pass).  A voicing passes when every sounding note is a chord
tone of its type and the type's defining tones are present.  The fifth may be omitted (common in guitar
shapes); 9th/11th/13th chords may omit the tones guitarists usually drop.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

STANDARD_TUNING_MIDI = (40, 45, 50, 55, 59, 64)  # E2 A2 D3 G3 B3 E4, low string first

# normalized chord type -> (allowed intervals above the root, required intervals)
CHORD_TYPE_TONES: Dict[str, Tuple[FrozenSet[int], FrozenSet[int]]] = {
    "": (frozenset({0, 4, 7}), frozenset({0, 4})),
    "m": (frozenset({0, 3, 7}), frozenset({0, 3})),
    "dim": (frozenset({0, 3, 6}), frozenset({0, 3, 6})),
    "aug": (frozenset({0, 4, 8}), frozenset({0, 4, 8})),
    "7": (frozenset({0, 4, 7, 10}), frozenset({0, 4, 10})),
    "maj7": (frozenset({0, 4, 7, 11}), frozenset({0, 4, 11})),
    "m7": (frozenset({0, 3, 7, 10}), frozenset({0, 3, 10})),
    "6": (frozenset({0, 4, 7, 9}), frozenset({0, 4, 9})),
    "m6": (frozenset({0, 3, 7, 9}), frozenset({0, 3, 9})),
    "69": (frozenset({0, 2, 4, 7, 9}), frozenset({0, 2, 4, 9})),
    "9": (frozenset({0, 2, 4, 7, 10}), frozenset({0, 2, 4, 10})),
    "m9": (frozenset({0, 2, 3, 7, 10}), frozenset({0, 2, 3, 10})),
    "maj9": (frozenset({0, 2, 4, 7, 11}), frozenset({0, 2, 4, 11})),
    "11": (frozenset({0, 2, 4, 5, 7, 10}), frozenset({0, 5, 10})),
    "m11": (frozenset({0, 2, 3, 5, 7, 10}), frozenset({0, 3, 5, 10})),
    "13": (frozenset({0, 2, 4, 5, 7, 9, 10}), frozenset({0, 4, 9, 10})),
    "sus2": (frozenset({0, 2, 7}), frozenset({0, 2})),
    "sus4": (frozenset({0, 5, 7}), frozenset({0, 5})),
    "add9": (frozenset({0, 2, 4, 7}), frozenset({0, 2, 4})),
    "mmaj7": (frozenset({0, 3, 7, 11}), frozenset({0, 3, 11})),
}


def sounding_intervals(frets: Sequence[int], root_pc: int, tuning: Sequence[int] = STANDARD_TUNING_MIDI) -> FrozenSet[int]:
    return frozenset(((int(tuning[string]) + int(fret)) - int(root_pc)) % 12 for string, fret in enumerate(frets) if int(fret) >= 0)


def voicing_tone_problems(
    frets: Sequence[int],
    root_pc: int,
    chord_type: str,
    bass_pc: Optional[int] = None,
) -> List[str]:
    """Empty list when the voicing plays `chord_type` on `root_pc`; otherwise human-readable problems.

    Unknown chord types are not judged (returns []), so callers decide whether to import them."""
    spec = CHORD_TYPE_TONES.get(chord_type)
    if spec is None:
        return []
    allowed, required = spec
    if bass_pc is not None:
        allowed = allowed | {(int(bass_pc) - int(root_pc)) % 12}
    intervals = sounding_intervals(frets, root_pc)
    problems: List[str] = []
    foreign = sorted(intervals - allowed)
    missing = sorted(required - intervals)
    if foreign:
        problems.append(f"plays non-chord tones (semitones above root: {foreign})")
    if missing:
        problems.append(f"lacks defining tones (semitones above root: {missing})")
    return problems
