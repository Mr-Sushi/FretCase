"""Shared constants and small helpers for song dictionaries (ticks, meters, keys, locks, sections)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from fretcase_engine.chord_spelling import NAME_TO_PC, spell_pc

TPQ = 480  # ticks per quarter note
TRACKS = ("vocal", "melody", "guitar", "bass", "drums", "ambience")
ENGINE_VERSION = "0.1.0"

DEFAULT_SECTION_LABELS = [("s-intro", "Intro"), ("s-verse", "Verse"), ("s-chorus", "Chorus"), ("s-outro", "Outro")]

Song = Dict[str, Any]


class CannotApply(Exception):
    """A valid request that cannot be applied (HTTP 422 ``cannot_apply``)."""

    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


def bar_ticks(meter: Dict[str, int]) -> int:
    return int(meter["numerator"]) * TPQ * 4 // int(meter["denominator"])


def meter_text(meter: Dict[str, int]) -> str:
    return f"{int(meter['numerator'])}/{int(meter['denominator'])}"


def beats_per_bar(meter: Dict[str, int]) -> float:
    """Quarter notes per bar (6/8 is 3.0)."""
    return int(meter["numerator"]) * 4.0 / int(meter["denominator"])


def key_text(key: Dict[str, str]) -> str:
    return f"{key['tonic']}m" if key["mode"] == "minor" else key["tonic"]


def parse_key_dict(text: str) -> Dict[str, str]:
    from fretcase_engine.chord_spelling import parse_key

    tonic, mode = parse_key(text)
    return {"tonic": tonic, "mode": mode}


def relative_key(key: Dict[str, str], target_mode: str) -> Dict[str, str]:
    """Relative minor or major of a key (C major <-> A minor)."""
    if key["mode"] == target_mode:
        return dict(key)
    pc = (NAME_TO_PC[key["tonic"]] + (-3 if target_mode == "minor" else 3)) % 12
    names = _MINOR_TONICS if target_mode == "minor" else _MAJOR_TONICS
    return {"tonic": names[pc], "mode": target_mode}


_MINOR_TONICS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
_MAJOR_TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def song_length(song: Song) -> int:
    return int(song["bars"]) * bar_ticks(song["meter"])


def section_of_bar(song: Song, bar: int) -> Optional[Dict[str, Any]]:
    for section in song["sections"]:
        if section["startBar"] <= bar < section["endBar"]:
            return section
    return None


def section_window(song: Song, section: Dict[str, Any]) -> Tuple[int, int]:
    bt = bar_ticks(song["meter"])
    return section["startBar"] * bt, section["endBar"] * bt


def sections_touching(song: Song, start: int, end: int) -> List[Dict[str, Any]]:
    """Sections that overlap the tick range [start, end). An empty range touches the section holding `start`."""
    out = []
    for section in song["sections"]:
        s, e = section_window(song, section)
        if (start < e and end > s) or (start == end and s <= start < e):
            out.append(section)
    return out


def is_locked(song: Song, track: str, section_id: str) -> bool:
    for lock in song.get("locks", []):
        lt, ls = lock.get("track"), lock.get("section")
        if lt is not None and ls is not None:
            if lt == track and ls == section_id:
                return True
        elif lt is not None:
            if lt == track:
                return True
        elif ls is not None:
            if ls == section_id:
                return True
    return False


def default_sections(bars: int) -> List[Dict[str, Any]]:
    """Up to four sections (Intro, Verse, Chorus, Outro) of near-equal length."""
    count = min(4, max(1, bars))
    base, extra = divmod(bars, count)
    labels = DEFAULT_SECTION_LABELS
    if count < 4:
        labels = [labels[0]] + labels[1:count - 1] + [labels[3]] if count >= 2 else [labels[0]]
        labels = labels[:count]
    out, start = [], 0
    for i in range(count):
        length = base + (1 if i < extra else 0)
        out.append({"id": labels[i][0], "label": labels[i][1], "startBar": start, "endBar": start + length})
        start += length
    return out


def notes_in_window(notes: Iterable[Dict[str, Any]], start: int, end: int) -> List[Dict[str, Any]]:
    return [n for n in notes if start <= n["start"] < end]
