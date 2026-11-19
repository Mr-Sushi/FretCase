"""Key-aware spelling of chord roots and note names.

Chord symbols and note names shown to learners must follow the key: IV in F major is Bb (not A#), iii in
D major is F#m (not Gbm), the leading tone in A minor is G#.  A pitch class is spelled from the letter of
its scale degree; chromatic intervals use the usual degree inflections (b2, b3, #4, b6, b7).  Spellings
that would need E#, B#, Cb, Fb or a double accidental fall back to the plain enharmonic name in the key's
direction (sharps for sharp keys, flats for flat keys and for C major / A minor, whose borrowed chords
are bVII, bVI and bIII).

This module has no project imports so every layer (ABC parsing, HRE, planners, explanations) can use it.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

LETTERS = "CDEFGAB"
LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
NAME_TO_PC = {
    letter + accidental: (pc + delta) % 12
    for letter, pc in LETTER_PC.items()
    for accidental, delta in (("", 0), ("#", 1), ("b", -1))
}
AWKWARD_NAMES = {"E#", "B#", "Cb", "Fb"}
# interval above the tonic (semitones) -> scale-degree index (0 = the tonic's letter)
DEGREE_INDEX = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 5, 9: 5, 10: 6, 11: 6}
MAJOR_FIFTHS = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
                "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}
_ROOT_RE = re.compile(r"^([A-Ga-g])([#b]?)(.*)$")


def normalize_tonic(name: Optional[str]) -> str:
    raw = str(name or "C").strip()
    if not raw or raw[0].upper() not in LETTER_PC:
        return "C"
    accidental = raw[1] if len(raw) > 1 and raw[1] in {"#", "b"} else ""
    return raw[0].upper() + accidental


def parse_key(key_text: Optional[str]) -> Tuple[str, str]:
    """'Bb' -> ('Bb', 'major'); 'Gm', 'Gmin', 'G minor' -> ('G', 'minor'); 'F#m' -> ('F#', 'minor')."""
    raw = str(key_text or "").strip()
    match = re.match(r"^([A-Ga-g][#b]?)\s*(.*)$", raw)
    if not match:
        return "C", "major"
    tonic = normalize_tonic(match.group(1))
    rest = match.group(2).strip().lower()
    mode = "minor" if rest in {"m", "min", "minor", "aeolian"} or rest.startswith("min") else "major"
    return tonic, mode


def _resolve_mode(mode: Optional[str]) -> str:
    return "minor" if str(mode or "").strip().lower() in {"minor", "min", "m", "aeolian"} else "major"


def key_fifths(tonic: str, mode: str = "major") -> Optional[int]:
    """Number of sharps (> 0) or flats (< 0) in the key signature; None for keys outside the circle."""
    name = normalize_tonic(tonic)
    if _resolve_mode(mode) == "minor":
        name = spell_relative(name, 3, 2)
    return MAJOR_FIFTHS.get(name)


def spell_relative(tonic: str, semitones: int, letter_steps: int) -> str:
    """The note `letter_steps` letters and `semitones` semitones above `tonic` (e.g. relative major)."""
    name = normalize_tonic(tonic)
    letter = LETTERS[(LETTERS.index(name[0]) + letter_steps) % 7]
    target = (NAME_TO_PC[name] + semitones) % 12
    alteration = (target - LETTER_PC[letter] + 6) % 12 - 6
    return letter + {-1: "b", 0: "", 1: "#"}.get(alteration, "?" if alteration else "")


def prefers_flats(tonic: str, mode: str = "major") -> bool:
    fifths = key_fifths(tonic, mode)
    if fifths is None:
        return "b" in normalize_tonic(tonic)
    return fifths <= 0


def spell_pc(pc: int, tonic: Optional[str] = "C", mode: Optional[str] = "major") -> str:
    """Name of pitch class `pc` in the key of `tonic` `mode` (see module docstring)."""
    pc = int(pc) % 12
    name = normalize_tonic(tonic)
    resolved_mode = _resolve_mode(mode)
    interval = (pc - NAME_TO_PC[name]) % 12
    letter = LETTERS[(LETTERS.index(name[0]) + DEGREE_INDEX[interval]) % 7]
    alteration = (pc - LETTER_PC[letter] + 6) % 12 - 6
    if alteration in (-1, 0, 1):
        spelled = letter + {-1: "b", 0: "", 1: "#"}[alteration]
        if spelled not in AWKWARD_NAMES:
            return spelled
    return (FLAT_NAMES if prefers_flats(name, resolved_mode) else SHARP_NAMES)[pc]


def root_pc(symbol: str) -> Optional[int]:
    match = _ROOT_RE.match(str(symbol or "").strip())
    if not match:
        return None
    return NAME_TO_PC.get(match.group(1).upper() + match.group(2))


def respell_symbol(symbol: str, tonic: Optional[str] = "C", mode: Optional[str] = "major") -> str:
    """Same chord with its root (and slash bass) spelled for the key: 'A#maj7' in F -> 'Bbmaj7'."""
    raw = str(symbol or "").strip()
    match = _ROOT_RE.match(raw)
    if not match:
        return raw
    root = match.group(1).upper() + match.group(2)
    suffix = match.group(3)
    if root not in NAME_TO_PC:
        return raw
    bass = ""
    if "/" in suffix:
        suffix, _, bass_text = suffix.partition("/")
        bass_match = _ROOT_RE.match(bass_text.strip())
        if bass_match and (bass_match.group(1).upper() + bass_match.group(2)) in NAME_TO_PC:
            bass_name = bass_match.group(1).upper() + bass_match.group(2)
            bass = "/" + spell_pc(NAME_TO_PC[bass_name], tonic, mode) + bass_match.group(3)
        else:
            bass = "/" + bass_text
    return spell_pc(NAME_TO_PC[root], tonic, mode) + suffix + bass


def enharmonic_key(symbol: str) -> str:
    """Spelling-independent identity of a chord symbol: 'A#m7' and 'Bbm7' -> '10:m7'."""
    raw = str(symbol or "").strip()
    match = _ROOT_RE.match(raw)
    if not match or (match.group(1).upper() + match.group(2)) not in NAME_TO_PC:
        return raw
    return f"{NAME_TO_PC[match.group(1).upper() + match.group(2)]}:{match.group(3)}"


class ChordSet(frozenset):
    """Set of chord symbols whose membership test ignores enharmonic spelling ('A#m' in {'Bbm'} is True).

    Learner profiles and scores may spell the same chord differently (a chord marked known in one key,
    met again in another); "is this chord known?" must not depend on the spelling."""

    def __new__(cls, symbols=()):
        items = [str(symbol) for symbol in symbols if str(symbol).strip()]
        obj = super().__new__(cls, items)
        obj._keys = frozenset(enharmonic_key(symbol) for symbol in items)
        return obj

    def __contains__(self, symbol) -> bool:  # type: ignore[override]
        return enharmonic_key(str(symbol)) in self._keys

    def __reduce__(self):
        return (ChordSet, (list(self),))


TONE_LETTER_STEPS = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6, 11: 6}


def spell_chord_tones(symbol: str, pcs, tonic: Optional[str] = "C", mode: Optional[str] = "major") -> dict:
    """pc -> name for a chord's tones, spelled in thirds from its key-spelled root (E7 in C: E G# B D)."""
    respelled = respell_symbol(symbol, tonic, mode)
    match = _ROOT_RE.match(respelled)
    names = {}
    if not match:
        return {int(pc) % 12: spell_pc(pc, tonic, mode) for pc in pcs}
    root_name = match.group(1).upper() + match.group(2)
    root = NAME_TO_PC[root_name]
    for pc in pcs:
        pc = int(pc) % 12
        interval = (pc - root) % 12
        letter = LETTERS[(LETTERS.index(root_name[0]) + TONE_LETTER_STEPS[interval]) % 7]
        alteration = (pc - LETTER_PC[letter] + 6) % 12 - 6
        spelled = letter + {-1: "b", 0: "", 1: "#"}.get(alteration, "") if alteration in (-1, 0, 1) else ""
        names[pc] = spelled if spelled and spelled not in AWKWARD_NAMES else spell_pc(pc, tonic, mode)
    return names
