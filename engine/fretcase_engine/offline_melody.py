"""Rule-based melody drafts for offline mode (no language model).

The previous offline fallback cycled a fixed scale pattern with one rhythm per draft, so offline demos
sounded mechanical and many strong-beat notes clashed with any harmony (H5 warnings).  These drafts are
built the way beginner arranging books describe a simple song:

* **Form** — 4-bar phrases grouped into periods: an antecedent that ends on the dominant (half cadence)
  answered by a consequent that ends on the tonic; a contrasting third phrase that reaches the high point;
  a final phrase that returns to the opening motif and closes on the tonic.
* **Implied harmony** — each bar has an implied diatonic chord (e.g. I–IV–I–V | I–IV–V–I); notes on
  strong beats are chord tones of that chord, weak-beat notes are passing or neighbour tones, so any
  reasonable harmonisation supports the melody.
* **Motif** — the first bar of the piece (rhythm and contour) returns at the start of the answering
  phrases, which is what makes a tune memorable.
* **Beginner register** — roughly a tenth around the tonic, mostly stepwise, leaps resolved by step.

Three variants differ in implied progression, motif rhythm and contour (arch / pop loop / descending).
Supports 4/4, 3/4 and 6/8 with ``L:1/8``; output is a complete single-voice ABC tune.
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Dict, List, Optional, Tuple

LETTERS = ["C", "D", "E", "F", "G", "A", "B"]
NATURAL_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]
SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
# number of sharps (+) / flats (-) for major keys; minor keys use their relative major
MAJOR_SIGNATURES = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7, "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6}
RELATIVE_MAJOR = {"A": "C", "E": "G", "B": "D", "F#": "A", "C#": "E", "G#": "B", "D": "F", "G": "Bb", "C": "Eb", "F": "Ab", "Bb": "Db", "Eb": "Gb"}

# Implied chord roots (scale degrees, 0 = I) for the four phrase types of each variant.
# Phrase types: 0 = opening (antecedent, half cadence), 1 = answer (authentic cadence),
#               2 = contrast (climax, half cadence), 3 = return (authentic cadence).
PROGRESSIONS = {
    0: [[0, 3, 0, 4], [0, 3, 4, 0], [5, 3, 0, 4], [0, 3, 4, 0]],   # arch, classic period
    1: [[0, 5, 3, 4], [0, 5, 4, 0], [3, 0, 1, 4], [0, 5, 4, 0]],   # pop loop I-vi-IV-V
    2: [[0, 2, 3, 4], [0, 3, 4, 0], [5, 2, 3, 4], [0, 3, 4, 0]],   # descending ballad
}
# Bar-level contour targets (scale steps above the tonic) for each phrase type.
CONTOURS = {
    0: [[2, 4, 5, 4], [2, 3, 2, 0], [5, 7, 6, 4], [2, 3, 1, 0]],
    1: [[4, 5, 3, 4], [4, 5, 1, 0], [5, 7, 6, 4], [4, 2, 1, 0]],
    2: [[5, 4, 2, 4], [5, 4, 1, 0], [7, 8, 6, 4], [4, 3, 1, 0]],
}
# Rhythm cells in eighth-note units: motif, answer, cadence (half / final) per metre and variant.
RHYTHMS: Dict[str, Dict[int, Dict[str, List[List[int]]]]] = {
    "4/4": {
        0: {"motif": [[2, 2, 4]], "body": [[2, 2, 2, 2], [4, 2, 2], [2, 1, 1, 4]], "half": [[2, 2, 4], [4, 4]], "final": [[8]]},
        1: {"motif": [[3, 1, 2, 2]], "body": [[2, 2, 2, 2], [3, 1, 4]], "half": [[2, 2, 4], [4, 4]], "final": [[8]]},
        2: {"motif": [[4, 2, 2]], "body": [[2, 2, 4], [2, 2, 1, 1, 2], [4, 2, 2]], "half": [[4, 4], [6, 2]], "final": [[8]]},
    },
    "3/4": {
        0: {"motif": [[2, 2, 2]], "body": [[4, 2], [2, 2, 2]], "half": [[4, 2], [6]], "final": [[6]]},
        1: {"motif": [[3, 1, 2]], "body": [[2, 2, 2], [4, 2]], "half": [[4, 2]], "final": [[6]]},
        2: {"motif": [[4, 2]], "body": [[2, 2, 2], [2, 4]], "half": [[6]], "final": [[6]]},
    },
    "6/8": {
        0: {"motif": [[2, 1, 3]], "body": [[3, 3], [2, 1, 2, 1]], "half": [[3, 3], [6]], "final": [[6]]},
        1: {"motif": [[3, 2, 1]], "body": [[2, 1, 3], [3, 3]], "half": [[3, 3]], "final": [[6]]},
        2: {"motif": [[3, 3]], "body": [[2, 1, 2, 1], [3, 2, 1]], "half": [[6]], "final": [[6]]},
    },
}
STRONG_UNITS = {"4/4": {0, 4}, "3/4": {0}, "6/8": {0, 3}}
UNITS_PER_BAR = {"4/4": 8, "3/4": 6, "6/8": 6}


def parse_key(key: str) -> Tuple[str, bool]:
    raw = str(key or "C").strip()
    match = re.match(r"^([A-Ga-g])([#b]?)", raw)
    tonic = (match.group(1).upper() + match.group(2)) if match else "C"
    lowered = raw.lower()
    minor = lowered.endswith("m") or "min" in lowered or (len(raw) > len(tonic) and raw[len(tonic):].strip().lower().startswith("m") and not raw[len(tonic):].strip().lower().startswith("maj"))
    return tonic, minor


def key_signature(tonic: str, minor: bool) -> Dict[str, int]:
    """Letter -> accidental (+1 sharp, -1 flat) implied by the key signature."""
    major_tonic = RELATIVE_MAJOR.get(tonic, "C") if minor else tonic
    count = MAJOR_SIGNATURES.get(major_tonic, 0)
    signature = {letter: 0 for letter in LETTERS}
    if count > 0:
        for letter in SHARP_ORDER[:count]:
            signature[letter] = 1
    elif count < 0:
        for letter in FLAT_ORDER[: -count]:
            signature[letter] = -1
    return signature


class _Speller:
    """Turns scale-step numbers (0 = tonic) into ABC notes relative to the key signature."""

    def __init__(self, tonic: str, minor: bool):
        self.tonic = tonic
        self.minor = minor
        self.scale = MINOR if minor else MAJOR
        self.signature = key_signature(tonic, minor)
        self.letter_index = LETTERS.index(tonic[0])
        # tonic octave: C and D in octave 4 (C4 = middle C), E..B in octave 3, keeping the line in a beginner register
        self.tonic_octave = 4 if self.letter_index <= 1 else 3
        tonic_pc = (NATURAL_PC[tonic[0]] + (1 if tonic.endswith("#") else -1 if tonic.endswith("b") else 0)) % 12
        self.tonic_midi = 12 * (self.tonic_octave + 1) + tonic_pc

    def midi(self, step: int, leading_tone: bool = False) -> int:
        octave, degree = divmod(step, 7)
        value = self.tonic_midi + 12 * octave + self.scale[degree]
        if leading_tone and self.minor and degree == 6:
            value += 1
        return value

    def abc(self, step: int, units: int, leading_tone: bool = False) -> str:
        total = self.letter_index + step
        letter = LETTERS[total % 7]
        octave = self.tonic_octave + total // 7
        midi = self.midi(step, leading_tone)
        natural_midi = 12 * (octave + 1) + NATURAL_PC[letter]
        alteration = midi - natural_midi
        accidental = ""
        if alteration != self.signature[letter]:
            accidental = {-2: "__", -1: "_", 0: "=", 1: "^", 2: "^^"}.get(alteration, "")
        if octave >= 5:
            name = letter.lower() + "'" * (octave - 5)
        else:
            name = letter + "," * max(0, 4 - octave)
        length = "" if units == 1 else str(units)
        return f"{accidental}{name}{length}"


def _chord_tones(root: int) -> List[int]:
    return [root, root + 2, root + 4]


def _nearest_chord_tone(root: int, target: int, low: int, high: int) -> int:
    options = []
    for octave in (-7, 0, 7, 14):
        for tone in _chord_tones(root):
            step = tone + octave
            if low <= step <= high:
                options.append(step)
    return min(options, key=lambda s: (abs(s - target), s)) if options else max(low, min(high, target))


def _best_tone(root: int, target: int, prev: int, low: int, high: int, max_leap: int = 4) -> int:
    """Chord tone of ``root`` close to the contour target and to the previous note (leap <= a fifth)."""
    options = []
    for octave in (-7, 0, 7, 14):
        for tone in _chord_tones(root):
            step = tone + octave
            if low <= step <= high:
                options.append(step)
    if not options:
        return max(low, min(high, target))
    near = [step for step in options if abs(step - prev) <= max_leap] or options
    return min(near, key=lambda step: (abs(step - target) + 1.0 * abs(step - prev), step))


def _fill_between(start: int, end: int, count: int, rng: random.Random) -> List[int]:
    """``count`` weak-beat notes leading from ``start`` towards ``end`` by step (passing / neighbour tones)."""
    notes: List[int] = []
    current = start
    for index in range(count):
        remaining = count - index
        gap = end - current
        if gap == 0:
            current += rng.choice([1, -1]) if index == 0 else (-1 if notes and notes[-1] > end else 1)
        elif abs(gap) > remaining:
            current += 2 if gap > 0 else -2
        else:
            current += 1 if gap > 0 else -1
        notes.append(current)
    return notes


def _phrase_types(length: int) -> List[int]:
    phrases = max(1, (length + 3) // 4)
    types: List[int] = []
    for index in range(phrases):
        if index == phrases - 1:
            types.append(3 if phrases > 2 else 1)
        else:
            types.append([0, 1, 2, 1][index % 4])
    if phrases >= 2:
        types[0] = 0
    return types


def generate_offline_melody(
    key: str = "C",
    meter: str = "4/4",
    tempo: int = 80,
    length: int = 16,
    variant: int = 0,
    seed_text: str = "",
    title: Optional[str] = None,
) -> str:
    meter = meter if meter in UNITS_PER_BAR else "4/4"
    units = UNITS_PER_BAR[meter]
    strong = STRONG_UNITS[meter]
    variant = int(variant) % 3
    tonic, minor = parse_key(key)
    speller = _Speller(tonic, minor)
    rng = random.Random(int(hashlib.sha256(f"{seed_text}|{key}|{meter}|{length}|{variant}".encode()).hexdigest()[:8], 16))
    rhythms = RHYTHMS[meter][variant]
    low, high = -2, 9

    bars: List[str] = []
    motif: Optional[Tuple[List[int], List[int]]] = None  # (rhythm, steps) of bar 1
    previous = 2
    phrase_types = _phrase_types(length)
    bar_number = 0
    for phrase_index, phrase_type in enumerate(phrase_types):
        progression = PROGRESSIONS[variant][phrase_type]
        contour = CONTOURS[variant][phrase_type]
        for position in range(4):
            bar_number += 1
            if bar_number > length:
                break
            last_of_piece = bar_number == length
            phrase_end = position == 3 or last_of_piece
            root = 0 if last_of_piece else progression[position]
            if last_of_piece and len(bars) >= 1:
                pass
            # rhythm
            if last_of_piece:
                rhythm = rng.choice(rhythms["final"])
            elif phrase_end and phrase_type in (0, 2):
                rhythm = rng.choice(rhythms["half"])
            elif phrase_end:
                rhythm = [units // 2, units - units // 2] if meter == "4/4" else rng.choice(rhythms["half"])
            elif position == 0 and motif is not None and phrase_type in (1, 3):
                rhythm = list(motif[0])
            elif position == 0:
                rhythm = rng.choice(rhythms["motif"])
            else:
                rhythm = rng.choice(rhythms["body"])
            onsets = [sum(rhythm[:i]) for i in range(len(rhythm))]

            # pitches: forward pass; strong beats take chord tones near both the contour target and the
            # previous note (leaps capped at a fifth), weak beats move by step towards the target
            if position == 0 and motif is not None and phrase_type in (1, 3) and rhythm == motif[0]:
                steps = list(motif[1])
            else:
                target = contour[position] + rng.choice([0, 0, 1, -1])
                steps = []
                prev = previous
                for i, onset in enumerate(onsets):
                    final_note = phrase_end and i == len(onsets) - 1
                    if final_note and (last_of_piece or phrase_type in (1, 3)):
                        step = 0 if abs(prev - 0) <= abs(prev - 7) else 7
                    elif final_note:
                        # half cadence on a dominant chord tone, placed near the note the next phrase
                        # (which repeats the opening motif) starts on, so the return is not a big leap
                        resume = motif[1][0] if motif is not None else prev
                        step = _best_tone(4, resume, prev, low, high)
                    elif onset in strong or i == 0:
                        local_target = target if onset == 0 else target + (1 if position < 2 else -1)
                        step = _best_tone(root, local_target, prev, low, high)
                    else:
                        direction = 1 if target > prev else -1 if target < prev else rng.choice([1, -1])
                        step = max(low, min(high, prev + direction))
                    steps.append(step)
                    prev = step
            tokens = []
            for i, (step, dur) in enumerate(zip(steps, rhythm)):
                lead = minor and root == 4 and step % 7 == 6
                tokens.append(speller.abc(step, dur, leading_tone=lead))
            bars.append(" ".join(tokens))
            previous = steps[-1]
            if bar_number == 1:
                motif = (list(rhythm), list(steps))
        if bar_number >= length:
            break

    key_field = f"{tonic}m" if minor else tonic
    lines = [f"{' '.join(bars[i:i + 4])}" for i in range(0, len(bars), 4)]
    body = " |\n".join(" | ".join(bars[i:i + 4]) for i in range(0, len(bars), 4)) + " |]"
    del lines
    return "\n".join([
        "X:1",
        f"T:{title or 'Offline Draft'}",
        f"M:{meter}",
        "L:1/8",
        f"Q:1/4={int(tempo)}",
        f"K:{key_field}",
        "V:1",
        body,
    ]) + "\n"
