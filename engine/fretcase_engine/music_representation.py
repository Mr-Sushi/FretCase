from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple
import re

try:
    from fretcase_engine.chord_spelling import spell_pc
except ImportError:  # script-mode import
    from chord_spelling import spell_pc


DEFAULT_METER = "4/4"
DEFAULT_TEMPO = 100
DEFAULT_NOTE_LENGTH = "1/8"


@dataclass(frozen=True)
class NoteEvent:
    pitch: str
    midi: Optional[int]
    start_beat: float
    duration_beats: float
    bar: int
    is_rest: bool = False


@dataclass(frozen=True)
class ChordEvent:
    symbol: str
    notes: List[str]
    start_beat: float
    duration_beats: float
    bar: int
    function: Optional[str] = None
    category: Optional[str] = None


@dataclass
class LeadSheetGraph:
    meter: str
    tempo: int
    key: Dict[str, object]
    melody: List[NoteEvent] = field(default_factory=list)
    harmony: List[ChordEvent] = field(default_factory=list)
    rhythm: Dict[str, object] = field(default_factory=dict)
    ornament: Dict[str, object] = field(default_factory=dict)


_NOTE_BASE_MIDI = {
    "C": 60,
    "D": 62,
    "E": 64,
    "F": 65,
    "G": 67,
    "A": 69,
    "B": 71,
}

_PC_TO_NAME_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NAME_TO_PC = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


_SHARP_ORDER = "FCGDAEB"
_FLAT_ORDER = "BEADGCF"
_MAJOR_SIGNATURE_COUNT = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
                          "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}
_RELATIVE_MAJOR = {"A": "C", "E": "G", "B": "D", "F#": "A", "C#": "E", "G#": "B", "D#": "F#", "A#": "C#",
                   "D": "F", "G": "Bb", "C": "Eb", "F": "Ab", "Bb": "Db", "Eb": "Gb", "Ab": "Cb"}
_NATURAL_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def key_signature_alterations(tonic: str, mode: str = "major") -> Dict[str, int]:
    """Letter -> alteration (+1 sharp, -1 flat, 0 natural) implied by an ABC ``K:`` field."""
    name = (tonic or "C").strip()
    name = name[:1].upper() + name[1:]
    major = _RELATIVE_MAJOR.get(name, "C") if str(mode).lower() == "minor" else name
    count = _MAJOR_SIGNATURE_COUNT.get(major, 0)
    signature = {letter: 0 for letter in "CDEFGAB"}
    if count > 0:
        for letter in _SHARP_ORDER[:count]:
            signature[letter] = 1
    elif count < 0:
        for letter in _FLAT_ORDER[: -count]:
            signature[letter] = -1
    return signature


def parse_abc_to_graph(
    abc: str,
    key_source: str = "prompt",
    key_confidence: float = 0.8,
) -> LeadSheetGraph:
    meter = _extract_header_value(abc, r"^M:\s*([0-9]+/[0-9]+)", DEFAULT_METER)
    tempo = int(_extract_header_value(abc, r"^Q:\s*(?:1/4\s*=\s*)?([0-9]+)", str(DEFAULT_TEMPO)))
    note_length = _extract_header_value(abc, r"^L:\s*([0-9]+/[0-9]+)", DEFAULT_NOTE_LENGTH)
    key_raw = _extract_header_value(abc, r"^K:\s*([A-Ga-g][#b]?(?:m|min)?)", "C")

    tonic, mode = _parse_key_signature(key_raw)

    key = {
        "tonic": tonic,
        "mode": mode,
        "confidence": float(key_confidence),
        "source": key_source,
    }

    melody_text = _extract_voice_text(abc, "1")
    harmony_text = _extract_voice_text(abc, "2")

    default_len_beats = _note_length_to_beats(note_length, meter)

    signature = key_signature_alterations(tonic, mode)
    melody_events = _parse_voice_notes(melody_text, default_len_beats, signature)
    harmony_events = _parse_voice_chords(harmony_text, default_len_beats, signature, tonic=tonic, mode=mode)

    return LeadSheetGraph(
        meter=meter,
        tempo=tempo,
        key=key,
        melody=melody_events,
        harmony=harmony_events,
        rhythm={},
        ornament={},
    )


def graph_to_abc(graph: LeadSheetGraph) -> str:
    meter = graph.meter or DEFAULT_METER
    tempo = graph.tempo or DEFAULT_TEMPO
    key = graph.key.get("tonic", "C")
    mode = graph.key.get("mode", "major")
    key_str = f"{key}m" if mode == "minor" and not key.endswith("m") else key

    header = [
        "X:1",
        "T:LeadSheetGraph Export",
        f"M:{meter}",
        f"L:{DEFAULT_NOTE_LENGTH}",
        f"Q:1/4={tempo}",
        f"K:{key_str}",
        "%%staves [1 2]",
    ]

    signature = key_signature_alterations(key, mode)
    melody_body = _events_to_abc_lines(graph.melody, DEFAULT_NOTE_LENGTH, meter, voice="1", signature=signature)
    harmony_body = _chords_to_abc_lines(graph.harmony, DEFAULT_NOTE_LENGTH, meter, voice="2", signature=signature)

    return "\n".join(header + melody_body + harmony_body).strip() + "\n"


def _extract_header_value(abc: str, pattern: str, default: str) -> str:
    for line in abc.splitlines():
        if re.match(pattern, line.strip()):
            match = re.match(pattern, line.strip())
            if match:
                return match.group(1)
    return default


def _parse_key_signature(key_raw: str) -> Tuple[str, str]:
    key_raw = key_raw.strip()
    if not key_raw:
        return "C", "major"

    key_clean = key_raw[0].upper() + key_raw[1:]
    if key_clean.endswith(("m", "min")):
        tonic = key_clean.replace("min", "").replace("m", "")
        return tonic, "minor"
    return key_clean, "major"


def _extract_voice_text(abc: str, voice: str) -> str:
    lines = abc.splitlines()
    current_voice = None
    collected: List[str] = []
    unvoiced_body: List[str] = []
    saw_any_voice = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("V:"):
            saw_any_voice = True
            parts = stripped.split(None, 1)
            current_voice = parts[0].replace("V:", "")
            if current_voice == voice and len(parts) > 1:
                # voice properties (name="Melody", clef=treble, nm=..., %%MIDI ...) are not music
                remainder = re.sub(r'\b[A-Za-z]+\s*=\s*("[^"]*"|\S+)', " ", parts[1])
                remainder = re.sub(r"%.*", "", remainder).strip()
                if remainder:
                    collected.append(remainder)
            continue
        if stripped.startswith(("X:", "T:", "M:", "L:", "Q:", "K:", "%%")):
            continue
        if not saw_any_voice and stripped:
            unvoiced_body.append(stripped)
        if current_voice == voice:
            collected.append(stripped)

    if not collected and not saw_any_voice and voice == "1":
        collected = unvoiced_body

    # Preserve line boundaries so that comment stripping (%...) doesn't
    # accidentally remove subsequent musical content when we later join/clean.
    return "\n".join(collected)


def _strip_annotations(text: str) -> str:
    text = re.sub(r"\"[^\"]*\"", "", text)
    text = re.sub(r"%.*", "", text)
    return text


def _parse_voice_notes(text: str, default_len_beats: float, signature: Optional[Dict[str, int]] = None) -> List[NoteEvent]:
    cleaned = _strip_annotations(text)
    bars = re.split(r"\|+", cleaned)
    events: List[NoteEvent] = []

    for bar_index, bar in enumerate(bars, start=1):
        bar = bar.strip()
        if not bar:
            continue
        cursor = 0.0
        bar_accidentals: Dict[Tuple[str, int], int] = {}  # explicit accidentals last until the bar line
        for token in _tokenize_music(bar):
            note_info = _parse_note_token(token, default_len_beats, signature, bar_accidentals)
            if note_info is None:
                continue
            pitch, midi, duration, is_rest = note_info
            events.append(
                NoteEvent(
                    pitch=pitch,
                    midi=midi,
                    start_beat=cursor,
                    duration_beats=duration,
                    bar=bar_index,
                    is_rest=is_rest,
                )
            )
            cursor += duration
    return events


def _parse_voice_chords(
    text: str,
    default_len_beats: float,
    signature: Optional[Dict[str, int]] = None,
    tonic: Optional[str] = None,
    mode: Optional[str] = None,
) -> List[ChordEvent]:
    cleaned = _strip_annotations(text)
    bars = re.split(r"\|+", cleaned)
    events: List[ChordEvent] = []

    for bar_index, bar in enumerate(bars, start=1):
        bar = bar.strip()
        if not bar:
            continue
        cursor = 0.0
        bar_accidentals: Dict[Tuple[str, int], int] = {}
        for token in _tokenize_music(bar):
            if not token.startswith("["):
                # Ignore non-chord tokens in harmony voice
                continue
            notes, duration = _parse_chord_token(token, default_len_beats, signature, bar_accidentals)
            if not notes or duration is None:
                continue
            symbol = detect_chord_symbol(notes, tonic=tonic, mode=mode)
            events.append(
                ChordEvent(
                    symbol=symbol,
                    notes=notes,
                    start_beat=cursor,
                    duration_beats=duration,
                    bar=bar_index,
                )
            )
            cursor += duration
    return events


def _tokenize_music(bar_text: str) -> List[str]:
    pattern = re.compile(
        r"\[[^\]]+\][0-9]*/?[0-9]*"
        r"|[_=^]?[A-Ga-gz][,']*(?:\d+/?\d*|/\d+)?"
    )
    return pattern.findall(bar_text)


def _abc_note_to_midi_in_key(
    accidental: str,
    note: str,
    octave_marks: str,
    signature: Optional[Dict[str, int]],
    bar_accidentals: Optional[Dict[Tuple[str, int], int]],
) -> int:
    """MIDI pitch of an ABC note with standard semantics: an explicit accidental (^ _ =) wins and lasts
    for that letter and octave until the bar line; otherwise an earlier accidental in the bar, otherwise
    the key signature applies."""
    letter = note.upper()
    octave = (5 if note.islower() else 4) + octave_marks.count("'") - octave_marks.count(",")
    key = (letter, octave)
    if accidental:
        alteration = accidental.count("^") - accidental.count("_")
        if bar_accidentals is not None:
            bar_accidentals[key] = alteration
    elif bar_accidentals is not None and key in bar_accidentals:
        alteration = bar_accidentals[key]
    else:
        alteration = (signature or {}).get(letter, 0)
    return 12 * (octave + 1) + _NATURAL_PC[letter] + alteration


def _parse_note_token(
    token: str,
    default_len_beats: float,
    signature: Optional[Dict[str, int]] = None,
    bar_accidentals: Optional[Dict[Tuple[str, int], int]] = None,
) -> Optional[Tuple[str, Optional[int], float, bool]]:
    match = re.match(r"(?P<acc>[_=^]*)(?P<note>[A-Ga-gz])(?P<oct>[,']*)(?P<dur>.*)", token)
    if not match:
        return None

    acc = match.group("acc") or ""
    note = match.group("note")
    octaves = match.group("oct") or ""
    dur = match.group("dur") or ""

    duration_beats = _duration_to_beats(dur, default_len_beats)

    if note.lower() == "z":
        return ("rest", None, duration_beats, True)

    midi = _abc_note_to_midi_in_key(acc, note, octaves, signature, bar_accidentals)
    pitch_name = _midi_to_note_name(midi)
    return (pitch_name, midi, duration_beats, False)


def _parse_chord_token(
    token: str,
    default_len_beats: float,
    signature: Optional[Dict[str, int]] = None,
    bar_accidentals: Optional[Dict[Tuple[str, int], int]] = None,
) -> Tuple[List[str], Optional[float]]:
    match = re.match(r"\[(?P<notes>[^\]]+)\](?P<dur>.*)", token)
    if not match:
        return ([], None)
    notes_raw = match.group("notes")
    dur = match.group("dur") or ""
    duration_beats = _duration_to_beats(dur, default_len_beats)

    note_tokens = re.findall(r"[_=^]?[A-Ga-g][,']*", notes_raw)
    notes: List[str] = []
    for nt in note_tokens:
        note_match = re.match(r"(?P<acc>[_=^]*)(?P<note>[A-Ga-g])(?P<oct>[,']*)", nt)
        if not note_match:
            continue
        midi = _abc_note_to_midi_in_key(
            note_match.group("acc") or "",
            note_match.group("note"),
            note_match.group("oct") or "",
            signature,
            bar_accidentals,
        )
        notes.append(_midi_to_note_name(midi))
    return notes, duration_beats


def _duration_to_beats(duration_str: str, default_len_beats: float) -> float:
    duration_str = duration_str.strip()
    if not duration_str:
        multiplier = Fraction(1, 1)
    elif duration_str.startswith("/"):
        denom = int(duration_str[1:]) if duration_str[1:] else 2
        multiplier = Fraction(1, denom)
    elif "/" in duration_str:
        num, denom = duration_str.split("/")
        multiplier = Fraction(int(num), int(denom))
    else:
        multiplier = Fraction(int(duration_str), 1)
    return float(multiplier * Fraction.from_float(default_len_beats))


def _note_length_to_beats(note_length: str, meter: str) -> float:
    # Meter is 4/4, so a whole note is 4 beats.
    try:
        num, denom = note_length.split("/")
        fraction = Fraction(int(num), int(denom))
    except ValueError:
        fraction = Fraction(1, 8)
    beats_per_whole = 4.0
    return float(fraction * beats_per_whole)


def _abc_note_to_midi(accidental: str, note: str, octave_marks: str) -> int:
    base = _NOTE_BASE_MIDI[note.upper()]
    if note.islower():
        base += 12
    octave_shift = 12 * (octave_marks.count("'") - octave_marks.count(","))
    acc_shift = accidental.count("^") - accidental.count("_")
    return base + octave_shift + acc_shift


def _midi_to_note_name(midi: int) -> str:
    pc = midi % 12
    return _PC_TO_NAME_SHARP[pc]


def _spelling(midi: int, signature: Dict[str, int]) -> Tuple[str, int, int]:
    """(letter, alteration, octave) for a pitch: diatonic letters as such, black keys as sharps (flats in flat keys)."""
    pc = midi % 12
    flat_key = sum(signature.values()) < 0
    if pc in _NATURAL_PC.values():
        letter = next(l for l, v in _NATURAL_PC.items() if v == pc)
        alteration = 0
    else:
        in_key = [l for l, v in _NATURAL_PC.items() if (v + signature.get(l, 0)) % 12 == pc]
        if in_key:
            letter = in_key[0]
            alteration = signature[letter]
        elif flat_key:
            letter = next(l for l, v in _NATURAL_PC.items() if (v - 1) % 12 == pc)
            alteration = -1
        else:
            letter = next(l for l, v in _NATURAL_PC.items() if (v + 1) % 12 == pc)
            alteration = 1
    natural_midi = midi - alteration
    octave = natural_midi // 12 - 1
    return letter, alteration, octave


def _abc_name(letter: str, octave: int) -> str:
    if octave >= 5:
        return letter.lower() + "'" * (octave - 5)
    return letter + "," * max(0, 4 - octave)


class BarSpeller:
    """Spells pitches within one bar with the fewest accidentals that still read correctly.

    Tracks accidentals already written in the bar (they last until the bar line in ABC), so a D natural
    after a D flat gets ``=D`` while a repeated D flat needs no second sign.  Create one per bar."""

    def __init__(self, signature: Optional[Dict[str, int]], explicit: bool = False):
        self.signature = dict(signature or {l: 0 for l in "CDEFGAB"})
        self.explicit = explicit
        self.state: Dict[Tuple[str, int], int] = {}

    def spell(self, midi: int) -> str:
        """``explicit=True`` (chord voice): every sharp/flat is written and a natural gets ``=`` whenever the
        key signature or an earlier accidental would alter it — unambiguous for readers that apply ABC
        rules (abcjs) and for simple readers that ignore the key signature (the editor's slot parser)."""
        letter, alteration, octave = _spelling(int(midi), self.signature)
        assumed = self.state.get((letter, octave), self.signature.get(letter, 0))
        accidental = ""
        if alteration != assumed or (self.explicit and alteration != 0):
            accidental = {-1: "_", 0: "=", 1: "^", -2: "__", 2: "^^"}[alteration]
        self.state[(letter, octave)] = alteration
        return f"{accidental}{_abc_name(letter, octave)}"


def spell_bar_tokens(
    token_midis: Sequence[Sequence[int]],
    signature: Optional[Dict[str, int]],
    explicit: bool = False,
) -> List[List[str]]:
    """Spell a bar given as a list of tokens (each a list of simultaneous MIDI pitches), left to right."""
    speller = BarSpeller(signature, explicit=explicit)
    return [[speller.spell(m) for m in token] for token in token_midis]


def midi_to_abc(midi: int, signature: Optional[Dict[str, int]] = None) -> str:
    """ABC spelling of a MIDI pitch.

    Without ``signature`` (legacy): sharps for black keys, plain letters otherwise.  With the key
    signature of the tune, the spelling is unambiguous whatever accidentals precede it in the bar:
    black-key notes always carry an explicit accidental (flats in flat keys), and a natural note whose
    letter the signature alters gets ``=`` (e.g. F natural in G major is written ``=F``, which a reader
    would otherwise play as F sharp)."""
    pc = midi % 12
    if signature is not None:
        letter, alteration, octave = _spelling(int(midi), signature)
        if alteration != 0:
            accidental = "^" if alteration > 0 else "_"  # explicit: safe whatever precedes it in the bar
        else:
            accidental = "=" if signature.get(letter, 0) != 0 else ""
        return f"{accidental}{_abc_name(letter, octave)}"

    name = _PC_TO_NAME_SHARP[pc]

    letter = name[0]
    accidental = ""
    if len(name) > 1:
        accidental = "^"

    octave_offset = (midi - 60) // 12
    if octave_offset >= 1:
        letter = letter.lower()
        octave_marks = "'" * (octave_offset - 1)
    elif octave_offset == 0:
        octave_marks = ""
    else:
        octave_marks = "," * abs(octave_offset)

    return f"{accidental}{letter}{octave_marks}"


def detect_chord_symbol(notes: List[str], tonic: Optional[str] = None, mode: Optional[str] = None) -> str:
    """Chord symbol for a set of note names; the root is spelled for the key when it is known."""
    if not notes:
        return "N.C."
    pcs = sorted({ _NAME_TO_PC.get(n, 0) for n in notes })
    for root_pc in pcs:
        rel = sorted(((pc - root_pc) % 12) for pc in pcs)
        rel_set = set(rel)
        root_name = spell_pc(root_pc, tonic, mode) if tonic else _PC_TO_NAME_SHARP[root_pc]
        if rel_set == {0, 4, 7}:
            return root_name
        if rel_set == {0, 3, 7}:
            return f"{root_name}m"
        if rel_set == {0, 3, 6}:
            return f"{root_name}dim"
        if rel_set == {0, 4, 8}:
            return f"{root_name}aug"
        if rel_set == {0, 4, 7, 10}:
            return f"{root_name}7"
        if rel_set == {0, 4, 7, 11}:
            return f"{root_name}maj7"
        if rel_set == {0, 3, 7, 10}:
            return f"{root_name}m7"
    return spell_pc(pcs[0], tonic, mode) if tonic else _PC_TO_NAME_SHARP[pcs[0]]


def _events_to_abc_lines(
    events: List[NoteEvent],
    default_note_length: str,
    meter: str,
    voice: str,
    signature: Optional[Dict[str, int]] = None,
) -> List[str]:
    header = [f"V:{voice} name=\"Melody\""]
    if not events:
        return header + ["z8 |"]

    bars: Dict[int, List[NoteEvent]] = {}
    for event in events:
        bars.setdefault(event.bar, []).append(event)

    bar_count = max(bars.keys())
    body_lines: List[str] = []
    for bar in range(1, bar_count + 1):
        tokens: List[str] = []
        speller = BarSpeller(signature) if signature is not None else None
        for event in sorted(bars.get(bar, []), key=lambda e: e.start_beat):
            duration_str = _beats_to_duration(event.duration_beats, default_note_length)
            if event.is_rest or event.midi is None:
                tokens.append(f"z{duration_str}")
            else:
                name = speller.spell(event.midi) if speller else midi_to_abc(event.midi)
                tokens.append(f"{name}{duration_str}")
        body_lines.append(" ".join(tokens) + " |")
    return header + body_lines


def _chords_to_abc_lines(
    events: List[ChordEvent],
    default_note_length: str,
    meter: str,
    voice: str,
    signature: Optional[Dict[str, int]] = None,
) -> List[str]:
    header = [f"V:{voice} name=\"Guitar Accompaniment\" %%MIDI program 25"]
    if not events:
        return header + ["[C E G]8 |"]

    bars: Dict[int, List[ChordEvent]] = {}
    for event in events:
        bars.setdefault(event.bar, []).append(event)

    bar_count = max(bars.keys())
    body_lines: List[str] = []
    for bar in range(1, bar_count + 1):
        tokens: List[str] = []
        speller = BarSpeller(signature, explicit=True) if signature is not None else None
        for event in sorted(bars.get(bar, []), key=lambda e: e.start_beat):
            duration_str = _beats_to_duration(event.duration_beats, default_note_length)
            if event.notes:
                if speller:
                    chord_notes = " ".join(speller.spell(60 + _NAME_TO_PC.get(n, 0)) for n in event.notes)
                else:
                    chord_notes = " ".join(_note_name_to_abc(n, event) for n in event.notes)
                tokens.append(f"[{chord_notes}]{duration_str}")
        body_lines.append(" ".join(tokens) + " |")
    return header + body_lines


def _beats_to_duration(duration_beats: float, default_note_length: str) -> str:
    default_beats = _note_length_to_beats(default_note_length, DEFAULT_METER)
    if default_beats == 0:
        return ""
    ratio = Fraction(duration_beats / default_beats).limit_denominator(8)
    if ratio == 1:
        return ""
    if ratio.numerator == 1 and ratio.denominator != 1:
        return f"/{ratio.denominator}"
    if ratio.denominator == 1:
        return f"{ratio.numerator}"
    return f"{ratio.numerator}/{ratio.denominator}"


def _note_name_to_abc(note_name: str, event: ChordEvent, signature: Optional[Dict[str, int]] = None) -> str:
    pc = _NAME_TO_PC.get(note_name, 0)
    midi = 60 + (pc - 0)
    return midi_to_abc(midi, signature)
