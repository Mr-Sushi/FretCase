"""Pure edit operations on song dictionaries: notes, lyrics, sections, locks. New FretCase code."""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Sequence

from fretcase_engine import melody as M
from fretcase_engine import regions as R
from fretcase_engine.catalog import style_ids
from fretcase_engine.common import TRACKS, CannotApply, bar_ticks, is_locked, section_window, sections_touching, song_length

Song = Dict[str, Any]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_LINE_BREAKS = re.compile(r"[\n\r]+")
_PUNCTUATION = re.compile(r"[\s,，。、；;:：!！?？\"“”‘’'（）()《》〈〉【】\[\]—…~～·\-]+")


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
    """Lines of syllables: one per Chinese character, one per word for other scripts. Only line breaks start a new
    line; punctuation and spaces are ignored."""
    lines = []
    for raw in _LINE_BREAKS.split(text):
        syllables: List[str] = []
        for token in _PUNCTUATION.split(raw):
            buf = ""
            for ch in token:
                if _CJK.match(ch):
                    if buf:
                        syllables.append(buf)
                        buf = ""
                    syllables.append(ch)
                else:
                    buf += ch
            if buf:
                syllables.append(buf)
        if syllables:
            lines.append(syllables)
    return lines


def vocal_notes_in(song: Song, section: Dict[str, Any]) -> List[Dict[str, Any]]:
    start, end = section_window(song, section)
    return sorted((n for n in song["tracks"]["vocal"]["notes"] if start <= n["start"] < end), key=lambda n: n["start"])


def lyric_lines(notes: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """The notes of a section grouped into lyric lines (a line ends at a note with ``lineEnd``)."""
    lines: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for n in notes:
        current.append(n)
        if n.get("lineEnd"):
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def set_lyrics(song: Song, section_id: str, text: str) -> Song:
    section = next((x for x in song["sections"] if x["id"] == section_id), None)
    if section is None:
        raise CannotApply("Unknown section", {"section": section_id})
    s = copy.deepcopy(song)
    notes = vocal_notes_in(s, section)
    lines = split_syllables(text)
    count = sum(len(line) for line in lines)
    if len(lines) > 1:  # line by line: each text line fits one lyric line of the section
        existing = lyric_lines(notes)
        bad = []
        for i in range(max(len(existing), len(lines))):
            note_count = len(existing[i]) if i < len(existing) else 0
            syllable_count = len(lines[i]) if i < len(lines) else 0
            if note_count != syllable_count:
                bad.append({"index": i, "noteCount": note_count, "syllableCount": syllable_count})
        if bad:
            raise CannotApply("Some lines do not fit the notes of their line", {"lines": bad, "noteCount": len(notes), "syllableCount": count})
        for line_notes, line in zip(existing, lines):
            for note, syllable in zip(line_notes, line):
                note["lyric"] = syllable[:12]
        return s
    if count != len(notes):
        raise CannotApply("The number of syllables does not match the number of vocal notes", {"noteCount": len(notes), "syllableCount": count})
    flat = [syllable for line in lines for syllable in line]
    for note, syllable in zip(notes, flat):
        note["lyric"] = syllable[:12]
    if notes and not any(n.get("lineEnd") for n in notes):
        notes[-1]["lineEnd"] = True
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
    R.sync_regions(s)
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
    section_ids = [x["id"] for x in secs]
    for track_id, track in song["tracks"].items():
        if [r["section"] for r in track.get("regions", [])] != section_ids:
            problems.append(f"{track_id} does not have exactly one region per section")
            continue
        for region, section in zip(track["regions"], secs):
            if region["play"]:
                continue
            start, end = section_window(song, section)
            if any(start <= n["start"] < end for n in track.get("notes", [])) or any(start <= c["start"] < end for c in track.get("clips", [])):
                problems.append(f"{track_id} has notes in {section['id']} where play is false")
    return problems


# ----------------------------------------------------------------------------------------------- regions (M2)


def _fields(**values: Any) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def set_region(song: Song, track: str, section_id: str, play: Any = None, complexity: Any = None, intensity: Any = None, style: Any = None) -> Song:
    """How one track plays in one section. Regenerates that track there even when it is locked, then locks it."""
    if track not in TRACKS:
        raise CannotApply("Unknown track", {"track": track})
    fields = _fields(play=play, complexity=complexity, intensity=intensity, style=style)
    if not fields:
        raise CannotApply("setRegion needs at least one of play, complexity, intensity, style")
    if style is not None and style not in style_ids(track):
        raise CannotApply(f"{style!r} is not a style of the {track} track", {"track": track, "style": style})
    s = copy.deepcopy(song)
    section = R.section_by_id(s, section_id)
    line = R.section_line(s, section) if track in ("vocal", "melody") else None
    region = R.region_of(s, track, section_id)
    play_changed = "play" in fields and fields["play"] != region["play"]
    region.update(fields)
    R.regenerate_region(s, track, section_id, line=line)
    melody_answers = R.region_of(s, "melody", section_id)["style"] == "answer"
    if track == "vocal" and play_changed and (melody_answers or not is_locked(s, "melody", section_id)):
        R.regenerate_region(s, "melody", section_id, line=line)  # a melody that answers the vocal depends on it
    add_lock(s, track, section_id)
    R.refresh_rhythm(s)
    return s


def copy_region(song: Song, track: str, section_id: str) -> Song:
    """"每一段都这样": the region's complexity, intensity and style go to every section of the track."""
    if track not in TRACKS:
        raise CannotApply("Unknown track", {"track": track})
    s = copy.deepcopy(song)
    R.section_by_id(s, section_id)
    source = R.region_of(s, track, section_id)
    for region in s["tracks"][track]["regions"]:
        region.update(complexity=source["complexity"], intensity=source["intensity"], style=source["style"])
    R.regenerate_all(s, tracks=[track], only_unlocked=False)
    add_lock(s, track)
    return s


LEAD_TRACKS = ("vocal", "melody", "guitar")


def set_lead(song: Song, section_id: str, track: Any, state: Dict[str, Any]) -> tuple:
    """Who carries a section. ``state`` (kept by the server) remembers the regions' values from before so that
    ``null`` or another lead restores them. Locked regions are left alone."""
    if track is not None and track not in LEAD_TRACKS:
        raise CannotApply("The lead must be vocal, melody, guitar or null", {"track": track})
    s = copy.deepcopy(song)
    state = copy.deepcopy(state) if state else {}
    section = R.section_by_id(s, section_id)
    touched = set()
    for t, saved in ((state.pop(section_id, None) or {}).get("regions") or {}).items():
        if not is_locked(s, t, section_id):
            R.region_of(s, t, section_id).update(saved)
            touched.add(t)
    section.pop("lead", None)
    if track is not None:
        section["lead"] = track
        saved_all = {}
        for t in TRACKS:
            if t == "ambience" or is_locked(s, t, section_id):
                continue
            region = R.region_of(s, t, section_id)
            saved_all[t] = {"intensity": region["intensity"], "style": region["style"]}
            region["intensity"] = round(R.clamp_unit(region["intensity"] + (0.15 if t == track else -0.1)), 3)
            touched.add(t)
        if track == "vocal" and "melody" in saved_all:
            R.region_of(s, "melody", section_id)["style"] = "answer"
        state[section_id] = {"regions": saved_all}
    R.regenerate_all(s, tracks=sorted(touched), sections=[section_id], only_unlocked=True)
    return s, state


def shift_register(song: Song, track: str, section_id: str, direction: str) -> Song:
    """"高一点 / 低一点". Vocal and melody move one scale step, guitar the next voicing up or down the neck, bass one octave."""
    from fretcase_engine.arrangement_solver import voicing_candidates_for_symbol
    from fretcase_engine.harmonise import voicing_to_song

    if track in ("drums", "ambience"):
        raise CannotApply("This track has no register to move", {"track": track})
    if track not in TRACKS:
        raise CannotApply("Unknown track", {"track": track})
    if direction not in ("up", "down"):
        raise CannotApply("direction must be up or down", {"direction": direction})
    s = copy.deepcopy(song)
    section = R.section_by_id(s, section_id)
    start, end = section_window(s, section)
    if not R.region_of(s, track, section_id)["play"]:
        raise CannotApply("Nothing plays on this track in this section", {"track": track, "section": section_id})
    sign = 1 if direction == "up" else -1
    if track in ("vocal", "melody"):
        notes = [n for n in s["tracks"][track]["notes"] if start <= n["start"] < end]
        if not notes:
            raise CannotApply("There are no notes to move", {"track": track, "section": section_id})
        moved = M.shift_diatonic(notes, sign, s["key"])
        low, high = R.VOICED_RANGE
        if min(n["pitch"] for n in moved) < low or max(n["pitch"] for n in moved) > high:
            raise CannotApply("That would leave the range of this instrument", {"track": track, "direction": direction})
        for old, new in zip(notes, moved):
            old["pitch"] = new["pitch"]
    elif track == "bass":
        notes = [n for n in s["tracks"]["bass"]["notes"] if start <= n["start"] < end]
        if not notes:
            raise CannotApply("There are no notes to move", {"track": track, "section": section_id})
        low, high = R.BASS_RANGE
        if min(n["pitch"] for n in notes) + 12 * sign < low or max(n["pitch"] for n in notes) + 12 * sign > high:
            raise CannotApply("That would leave the range of this instrument", {"track": track, "direction": direction})
        for n in notes:
            n["pitch"] += 12 * sign
    else:  # guitar
        moved_any = False
        for chord in R.chords_in(s, start, end):
            voicing = chord.get("voicing")
            if not voicing:
                continue
            current = voicing["baseFret"]
            options = [v for v in voicing_candidates_for_symbol(chord.get("shapeSymbol") or chord["symbol"]) if max(v.frets) <= 12]
            options = [v for v in options if (v.base_fret > current if sign > 0 else v.base_fret < current)]
            if not options:
                continue
            pick = min(options, key=lambda v: (v.base_fret, v.difficulty)) if sign > 0 else min(options, key=lambda v: (-v.base_fret, v.difficulty))
            chord["voicing"] = voicing_to_song(pick)
            moved_any = True
        if not moved_any:
            raise CannotApply("That would leave the range of this instrument", {"track": track, "direction": direction})
        R.regenerate_region(s, "guitar", section_id)
    add_lock(s, track, section_id)
    return s


def revert_melody(song: Song, section_id: str) -> Song:
    """"用回我哼的": the section's sung line goes back to the seed motif (lyrics stay where the note count is unchanged)."""
    from fretcase_engine.generate import reharmonise_section

    if not (song.get("seed") or {}).get("motif"):
        raise CannotApply("This song has no hummed melody to go back to", {"reason": "no_motif"})
    s = copy.deepcopy(song)
    section = R.section_by_id(s, section_id)
    start, end = section_window(s, section)
    line = [n for n in R.base_line(s) if start <= n["start"] < end]
    R.write_line(s, section_id, line, force=True)
    reharmonise_section(s, section)
    return s


def set_master(song: Song, volume: Any = None, space: Any = None) -> Song:
    if volume is None and space is None:
        raise CannotApply("setMaster needs volume or space")
    if space is not None and space not in ("dry", "room", "hall"):
        raise CannotApply("space must be dry, room or hall", {"space": space})
    s = copy.deepcopy(song)
    if volume is not None:
        s["master"]["volume"] = volume
    if space is not None:
        s["master"]["space"] = space
    return s
