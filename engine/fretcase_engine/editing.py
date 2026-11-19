"""Pure edit operations on song dictionaries: notes, lyrics, sections, locks. New FretCase code."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Sequence

from fretcase_engine.common import TRACKS, bar_ticks, section_window, sections_touching, song_length
from fretcase_engine.generate import CannotApply

Song = Dict[str, Any]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_LINE_BREAKS = re.compile(r"[\n\r;；。！？!?,，、]+")


def add_lock(song: Song, track: str = None, section: str = None) -> None:
    lock = {k: v for k, v in (("track", track), ("section", section)) if v is not None}
    if lock and lock not in song["locks"]:
        song["locks"].append(lock)


def lock(song: Song, track: str = None, section: str = None) -> Song:
    if track is None and section is None:
        raise CannotApply("A lock needs a track, a section, or both")
    if track is not None and track not in TRACKS:
        raise CannotApply("Unknown track", {"track": track})
    if section is not None and section not in {s["id"] for s in song["sections"]}:
        raise CannotApply("Unknown section", {"section": section})
    s = copy.deepcopy(song)
    add_lock(s, track, section)
    return s


def unlock(song: Song, track: str = None, section: str = None) -> Song:
    if track is None and section is None:
        raise CannotApply("An unlock needs a track, a section, or both")
    target = {k: v for k, v in (("track", track), ("section", section)) if v is not None}
    s = copy.deepcopy(song)
    if target not in s["locks"]:
        raise CannotApply("There is no such lock", target)
    s["locks"].remove(target)
    return s


def replace_notes(song: Song, track: str, start: int, end: int, notes: Sequence[Dict[str, Any]]) -> Song:
    if track == "ambience":
        raise CannotApply("Notes cannot be edited on the ambience track", {"track": track})
    if track not in TRACKS:
        raise CannotApply("Unknown track", {"track": track})
    if end < start:
        raise CannotApply("'to' must not be before 'from'", {"from": start, "to": end})
    length = song_length(song)
    if end > length:
        raise CannotApply("The range reaches past the end of the song", {"to": end, "length": length})
    cleaned: List[Dict[str, Any]] = []
    for note in notes:
        n = dict(note)
        if not start <= n["start"] < max(end, start + 1) or n["start"] >= end:
            raise CannotApply("Every new note must start inside [from, to)", {"note": note})
        if n["start"] + n["duration"] > length:
            raise CannotApply("A note reaches past the end of the song", {"note": note})
        cleaned.append(n)
    s = copy.deepcopy(song)
    old = s["tracks"][track]["notes"]
    s["tracks"][track]["notes"] = sorted([n for n in old if not start <= n["start"] < end] + cleaned, key=lambda n: (n["start"], n["pitch"]))
    for section in sections_touching(s, start, end):
        add_lock(s, track, section["id"])
    return s


def split_syllables(text: str) -> List[List[str]]:
    """Lines of syllables: one per Chinese character, one per word for other scripts."""
    lines = []
    for raw in _LINE_BREAKS.split(text):
        syllables: List[str] = []
        for token in re.split(r"\s+", raw.strip()):
            if not token:
                continue
            buf = ""
            for ch in token:
                if _CJK.match(ch):
                    if buf:
                        syllables.append(buf)
                        buf = ""
                    syllables.append(ch)
                elif ch in "-·":
                    if buf:
                        syllables.append(buf)
                        buf = ""
                else:
                    buf += ch
            if buf:
                syllables.append(buf)
        if syllables:
            lines.append(syllables)
    return lines


def set_lyrics(song: Song, section_id: str, text: str) -> Song:
    section = next((x for x in song["sections"] if x["id"] == section_id), None)
    if section is None:
        raise CannotApply("Unknown section", {"section": section_id})
    start, end = section_window(song, section)
    s = copy.deepcopy(song)
    notes = [n for n in s["tracks"]["vocal"]["notes"] if start <= n["start"] < end]
    notes.sort(key=lambda n: n["start"])
    lines = split_syllables(text)
    count = sum(len(line) for line in lines)
    if count != len(notes):
        raise CannotApply("The number of syllables does not match the number of vocal notes", {"noteCount": len(notes), "syllableCount": count})
    index = 0
    for line in lines:
        for pos, syllable in enumerate(line):
            note = notes[index]
            note["lyric"] = syllable[:12]
            if pos == len(line) - 1:
                note["lineEnd"] = True
            else:
                note.pop("lineEnd", None)
            index += 1
    return s


def set_sections(song: Song, sections: Sequence[Dict[str, Any]]) -> Song:
    if not sections:
        raise CannotApply("There must be at least one section")
    ids = [x["id"] for x in sections]
    if len(set(ids)) != len(ids):
        raise CannotApply("Section ids must be unique")
    position = 0
    for x in sections:
        if not ID_RE.match(x["id"]):
            raise CannotApply("Invalid section id", {"section": x["id"]})
        if x["startBar"] != position or x["endBar"] <= x["startBar"]:
            raise CannotApply("Sections must be contiguous and in order", {"section": x["id"]})
        position = x["endBar"]
    if position != song["bars"]:
        raise CannotApply("Sections must cover every bar", {"bars": song["bars"], "covered": position})
    s = copy.deepcopy(song)
    s["sections"] = [dict(x) for x in sections]
    s["locks"] = [lk for lk in s["locks"] if "section" not in lk or lk["section"] in set(ids)]
    return s


def check_consistency(song: Song) -> List[str]:
    """Rules the JSON schema cannot express (mirrors shared/schema/tests/test_schemas.py)."""
    problems: List[str] = []
    length = song_length(song)
    secs = song["sections"]
    if secs[0]["startBar"] != 0 or secs[-1]["endBar"] != song["bars"]:
        problems.append("sections do not cover the song")
    for a, b in zip(secs, secs[1:]):
        if a["endBar"] != b["startBar"]:
            problems.append("sections not contiguous")
    position = 0
    for chord in song["harmony"]:
        if chord["start"] < position:
            problems.append("chords overlap")
        position = chord["start"] + chord["duration"]
    if position > length:
        problems.append("harmony past the end")
    for track_id, track in song["tracks"].items():
        for n in track.get("notes", []):
            if n["start"] + n["duration"] > length:
                problems.append(f"{track_id} note past the end")
        for clip in track.get("clips", []):
            if clip["start"] + clip["duration"] > length:
                problems.append("clip past the end")
    ids = {x["id"] for x in secs}
    for lk in song["locks"]:
        if "section" in lk and lk["section"] not in ids:
            problems.append("lock refers to a missing section")
    asset_ids = {a["id"] for a in song["assets"]}
    for clip in song["tracks"]["ambience"]["clips"]:
        if clip["assetId"] not in asset_ids:
            problems.append("clip refers to a missing asset")
    return problems
