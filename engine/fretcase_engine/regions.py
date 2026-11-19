"""Regions: how one track plays in one section (schema 2.0), and the generation that reads them.

Every track has exactly one region per section. ``play: false`` gives no notes. ``complexity`` is the x axis of the
GarageBand-Drummer-style pad (more notes, ornaments, fills) and ``intensity`` the y axis (velocity). ``style`` picks
the pattern (catalogue in docs/api.md). New FretCase code.

The sung line. The vocal track holds the sung line while it plays; when it does not, the melody track holds it (a
melody in style ``answer`` only answers while the vocal sings), and when neither plays the line is rebuilt from the
seed (the hummed motif, or the offline melody). ``section_line`` returns it; callers take it *before* they change
regions so that turning a track off and on again does not lose it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fretcase_engine import melody as M
from fretcase_engine.accompaniment import KICK, RIDE, bass_notes, drum_notes
from fretcase_engine.catalog import DEFAULT_STYLE
from fretcase_engine.chord_spelling import NAME_TO_PC
from fretcase_engine.common import TPQ, TRACKS, CannotApply, bar_ticks, is_locked, section_window
from fretcase_engine.harmony_reasoning import parse_symbol_root_and_quality
from fretcase_engine.rhythm import _string_pitches, choose_preset, presets_by_id, realise

Song = Dict[str, Any]
Note = Dict[str, Any]

BASS_RANGE = (28, 55)  # E1 .. G3
VOICED_RANGE = (55, 91)  # vocal and melody, G3 .. G6
GRACE_TICKS = 60


# ----------------------------------------------------------------------------------------------- basics


def velocity_scale(velocity: float, intensity: float) -> int:
    """Intensity 0.5 keeps the base velocity; 0 plays at 60 %, 1 at 140 %."""
    return int(max(1, min(127, round(velocity * (0.6 + 0.8 * intensity)))))


def default_intensity(index: int, count: int) -> float:
    if count <= 1:
        return 0.5
    if index == 0 or index == count - 1:
        return 0.4
    if count >= 3 and index == count - 2:
        return 0.75
    return 0.55


def make_region(section_id: str, style: str, complexity: float = 0.5, intensity: float = 0.5, play: bool = True) -> Dict[str, Any]:
    return {"section": section_id, "play": play, "complexity": round(float(complexity), 3), "intensity": round(float(intensity), 3), "style": style}


def region_of(song: Song, track: str, section_id: str) -> Dict[str, Any]:
    for region in song["tracks"][track]["regions"]:
        if region["section"] == section_id:
            return region
    raise CannotApply("Unknown section", {"section": section_id})


def section_by_id(song: Song, section_id: str) -> Dict[str, Any]:
    for section in song["sections"]:
        if section["id"] == section_id:
            return section
    raise CannotApply("Unknown section", {"section": section_id})


def sync_regions(song: Song) -> None:
    """Make every track have exactly one region per section, in section order. A new section copies the region
    of the old section that held its first bar."""
    sections = song["sections"]
    for track in TRACKS:
        old = song["tracks"][track].get("regions") or []
        by_id = {r["section"]: r for r in old}
        regions = []
        for i, section in enumerate(sections):
            if section["id"] in by_id:
                regions.append(by_id[section["id"]])
                continue
            template = old[min(i, len(old) - 1)] if old else make_region(section["id"], DEFAULT_STYLE[track])
            regions.append({**template, "section": section["id"]})
        song["tracks"][track]["regions"] = regions


# ----------------------------------------------------------------------------------------------- the sung line


def seed_key(song: Song) -> Dict[str, str]:
    return dict((song.get("seed") or {}).get("key") or song["key"])


def base_line(song: Song) -> List[Note]:
    """The line the song started from, rebuilt from the seed. Deterministic."""
    from fretcase_engine.generate import _seed_text, _variant

    seed = song.get("seed") or {}
    tempo = float(seed.get("tempo") or song["tempo"])
    if seed:
        return M.build_melody(seed, seed_key(song), song["meter"], tempo, song["bars"], song["sections"], variant=_variant(seed), seed_text=_seed_text(seed))
    return M.place_into_octave(M.offline_notes(song["key"], song["meter"], tempo, song["bars"], 0, song["id"]), song["key"])


def strip_graces(notes: Sequence[Note]) -> List[Note]:
    """Undo the ornaments ``add_graces`` makes, so a line read back from the melody track is clean."""
    ordered = sorted((dict(n) for n in notes), key=lambda n: (n["start"], n["pitch"]))
    out: List[Note] = []
    for i, n in enumerate(ordered):
        is_grace = n["duration"] == GRACE_TICKS and i + 1 < len(ordered) and n["start"] + GRACE_TICKS == ordered[i + 1]["start"]
        if is_grace:
            if out and out[-1]["start"] + out[-1]["duration"] == n["start"]:
                out[-1]["duration"] += GRACE_TICKS
            continue
        out.append(n)
    return out


def _plain(n: Note) -> Note:
    return {"start": int(n["start"]), "duration": int(n["duration"]), "pitch": int(n["pitch"])}


def section_line(song: Song, section: Dict[str, Any], base: Optional[Sequence[Note]] = None) -> List[Note]:
    start, end = section_window(song, section)
    vocal = sorted((n for n in song["tracks"]["vocal"]["notes"] if start <= n["start"] < end), key=lambda n: n["start"])
    if vocal:
        return [_plain(n) for n in vocal]
    melody = [n for n in song["tracks"]["melody"]["notes"] if start <= n["start"] < end]
    if melody:
        return [_plain(n) for n in strip_graces(melody)]
    if base is None:
        base = base_line(song)
    return [_plain(n) for n in base if start <= n["start"] < end]


def song_line(song: Song) -> List[Note]:
    """The sung line over the whole song: what the harmony is fitted to."""
    base: Optional[List[Note]] = None
    out: List[Note] = []
    for section in song["sections"]:
        start, end = section_window(song, section)
        has_own = any(start <= n["start"] < end for t in ("vocal", "melody") for n in song["tracks"][t]["notes"])
        if not has_own and base is None:
            base = base_line(song)
        out.extend(section_line(song, section, base))
    return out


def _line_ends(notes: Sequence[Note], bt: int) -> List[bool]:
    flags = []
    for i, n in enumerate(notes):
        if i == len(notes) - 1:
            flags.append(True)
            continue
        nxt = notes[i + 1]
        gap = nxt["start"] - (n["start"] + n["duration"])
        flags.append(gap >= TPQ or n["start"] // (2 * bt) != nxt["start"] // (2 * bt))
    return flags


def vocal_from_line(song: Song, line: Sequence[Note], old: Sequence[Note], intensity: float) -> List[Note]:
    """Vocal notes for a line. Lyrics are kept by position when the note count is unchanged; otherwise every note
    gets the placeholder syllable 啦 so the line can still be sung as a guide tone."""
    bt = bar_ticks(song["meter"])
    ordered = sorted(line, key=lambda n: n["start"])
    old_sorted = sorted(old, key=lambda n: n["start"])
    keep = len(old_sorted) == len(ordered) and any(o.get("lyric") for o in old_sorted)
    ends = _line_ends(ordered, bt)
    out = []
    for i, n in enumerate(ordered):
        note: Note = {**_plain(n), "velocity": velocity_scale(90, intensity)}
        if keep:
            note["lyric"] = old_sorted[i].get("lyric") or "啦"
            if old_sorted[i].get("lineEnd"):
                note["lineEnd"] = True
        else:
            note["lyric"] = "啦"
            if ends[i]:
                note["lineEnd"] = True
        out.append(note)
    return out


def add_graces(notes: Sequence[Note], key: Dict[str, str], complexity: float) -> List[Note]:
    """Ornaments for a complex melody: a short grace note a scale step below long notes."""
    if complexity < 0.67:
        return [dict(n) for n in notes]
    minimum = TPQ if complexity >= 0.85 else 2 * TPQ
    out: List[Note] = []
    for n in notes:
        n = dict(n)
        if n["duration"] >= minimum and n["start"] > 0:
            if out and out[-1]["start"] + out[-1]["duration"] == n["start"] and out[-1]["duration"] > 2 * GRACE_TICKS:
                out[-1]["duration"] -= GRACE_TICKS
                out.append({"start": n["start"] - GRACE_TICKS, "duration": GRACE_TICKS, "pitch": M.shift_diatonic([n], -1, key)[0]["pitch"], "velocity": n.get("velocity", 90)})
            elif not out or out[-1]["start"] + out[-1]["duration"] <= n["start"] - GRACE_TICKS:
                out.append({"start": n["start"] - GRACE_TICKS, "duration": GRACE_TICKS, "pitch": M.shift_diatonic([n], -1, key)[0]["pitch"], "velocity": n.get("velocity", 90)})
        out.append(n)
    return out


def answer_notes(line: Sequence[Note], key: Dict[str, str], start: int, end: int, bt: int) -> List[Note]:
    """Melody in style ``answer``: it comes in where the line rests, repeating the last notes a third higher."""
    ordered = sorted(line, key=lambda n: n["start"])
    out: List[Note] = []
    for i, n in enumerate(ordered):
        gap_start = n["start"] + n["duration"]
        gap_end = ordered[i + 1]["start"] if i + 1 < len(ordered) else end
        if gap_end - gap_start < TPQ // 2:
            continue
        echo = M.shift_diatonic(ordered[max(0, i - 1): i + 1], 2, key)
        share = (gap_end - gap_start) // len(echo)
        for k, e in enumerate(echo):
            out.append({"start": gap_start + k * share, "duration": max(1, min(e["duration"], share)), "pitch": e["pitch"], "velocity": 90})
    if not out:  # a line with no rests: answer in the last beat of every two bars
        step = 2 * bt
        for group in range(start, end, step):
            last_beat = min(group + step, end) - TPQ
            inside = [n for n in ordered if group <= n["start"] < group + step]
            for k, e in enumerate(M.shift_diatonic(inside[-2:], 2, key)):
                out.append({"start": last_beat + k * (TPQ // 2), "duration": TPQ // 2, "pitch": e["pitch"], "velocity": 90})
    return [n for n in out if n["start"] < end]


def melody_from_line(song: Song, line: Sequence[Note], region: Dict[str, Any], vocal_plays: bool, start: int, end: int) -> List[Note]:
    key = seed_key(song)
    bt = bar_ticks(song["meter"])
    if region["style"] == "answer" and vocal_plays:
        notes = answer_notes(line, key, start, end, bt)
    else:
        notes = [{**_plain(n), "velocity": 90} for n in line]
    notes = add_graces(notes, key, region["complexity"])
    for n in notes:
        n["velocity"] = velocity_scale(n.get("velocity", 90), region["intensity"])
        n["pitch"] = max(0, min(127, n["pitch"]))
    return sorted(notes, key=lambda n: (n["start"], n["pitch"]))


# ----------------------------------------------------------------------------------------------- guitar, bass, drums


def chords_in(song: Song, start: int, end: int) -> List[Dict[str, Any]]:
    return [e for e in song["harmony"] if start <= e["start"] < end]


def guitar_preset(song: Song, region: Dict[str, Any]) -> Dict[str, Any]:
    """The rhythm preset a guitar region uses. Strum and muted use strumming presets, arpeggio the arpeggio ones; the
    level comes from complexity (nearest level when the meter lacks it). The song's current preset is kept when it
    already fits the family and level, so ``setRhythm`` can choose among the presets of a level."""
    family = "arpeggio" if region["style"] == "arpeggio" else "strumming"
    chosen = choose_preset(song["meter"], region["complexity"], family)
    current = presets_by_id().get(song["tracks"]["guitar"]["rhythm"]["presetId"])
    if current and current["family"] == chosen["family"] and current["meter"] == chosen["meter"] and current["level"] == chosen["level"]:
        return current
    return chosen


def guitar_notes(song: Song, region: Dict[str, Any], start: int, end: int) -> List[Note]:
    capo = song.get("capo")
    capo_fret = capo["fret"] if capo else 0
    chords = chords_in(song, start, end)
    notes: List[Note] = []
    if region["style"] == "sustain":
        for chord in chords:
            voicing = chord.get("voicing")
            if not voicing:
                continue
            for pitch in [p for p in _string_pitches(voicing, capo_fret) if p is not None]:
                notes.append({"start": chord["start"], "duration": chord["duration"], "pitch": int(pitch), "velocity": 80})
    else:
        notes = realise(chords, guitar_preset(song, region), song["meter"], capo_fret)
        if region["style"] == "muted":
            notes = [{**n, "duration": min(n["duration"], 120), "velocity": int(n["velocity"] * 0.8)} for n in notes]
    for n in notes:
        n["velocity"] = velocity_scale(n["velocity"], region["intensity"])
    return sorted(notes, key=lambda n: (n["start"], n["pitch"]))


def _is_minor(symbol: str) -> bool:
    _, quality = parse_symbol_root_and_quality(symbol.split("/")[0])
    return quality.startswith("m") and not quality.startswith("maj")


def _root(symbol: str) -> int:
    root, _ = parse_symbol_root_and_quality(symbol.split("/")[0])
    return 36 + NAME_TO_PC.get(root, 0)


def fit_bass(pitch: int) -> int:
    lo, hi = BASS_RANGE
    while pitch > hi:
        pitch -= 12
    while pitch < lo:
        pitch += 12
    return pitch


def bass_region_notes(song: Song, region: Dict[str, Any], start: int, end: int, variation: int = 0) -> List[Note]:
    chords = chords_in(song, start, end)
    meter = song["meter"]
    bt = bar_ticks(meter)
    style = region["style"]
    notes: List[Note] = []
    if style == "sustain":
        for c in chords:
            notes.append({"start": c["start"], "duration": c["duration"], "pitch": _root(c["symbol"]), "velocity": 90})
    elif style == "walking":
        beats = max(1, bt // TPQ)
        for ci, c in enumerate(chords):
            root = _root(c["symbol"])
            third = root + (3 if _is_minor(c["symbol"]) else 4)
            nxt = _root(chords[ci + 1]["symbol"]) if ci + 1 < len(chords) else root
            cycle = [root, third, root + 7, third]
            for bar in range(c["start"] // bt, (c["start"] + c["duration"] - 1) // bt + 1):
                for b in range(beats):
                    pitch = cycle[b % 4]
                    if b == beats - 1 and beats >= 3:
                        pitch = nxt - 1 if nxt > root else nxt + 1  # approach the next root by a half step
                    t = bar * bt + b * TPQ
                    if c["start"] <= t < c["start"] + c["duration"]:
                        notes.append({"start": t, "duration": TPQ, "pitch": pitch, "velocity": 95 if b == 0 else 80})
    else:  # groove: milestone 1's pattern, level from complexity
        notes = bass_notes(chords, meter, region["complexity"])
        if variation:
            for i, n in enumerate(notes):
                if i % 2 == 1:
                    n["pitch"] += 7 if variation % 2 == 1 else 12
    for n in notes:
        n["pitch"] = fit_bass(n["pitch"])
        n["velocity"] = velocity_scale(n["velocity"], region["intensity"])
        n["duration"] = max(1, min(n["duration"], end - n["start"]))
    return sorted(notes, key=lambda n: (n["start"], n["pitch"]))


HAND_MAP = {36: 64, 38: 63, 42: 62, 46: 63, 51: 62}  # kick, snare, hats -> low conga, open hi conga, mute hi conga


def drum_region_notes(song: Song, region: Dict[str, Any], section: Dict[str, Any], variation: int = 0) -> List[Note]:
    complexity = region["complexity"]
    fills = True if complexity >= 0.67 else (False if complexity < 0.33 else None)  # None: every fourth bar, by take
    notes = drum_notes(section["startBar"], section["endBar"], song["meter"], complexity, variation=variation, fills=fills)
    out = []
    for n in notes:
        n = dict(n)
        v = n["velocity"]
        if region["style"] == "brush":
            if n["pitch"] != KICK:
                v = int(v * 0.65)
            else:
                v = int(v * 0.75)
            if n["pitch"] == 42:
                n["pitch"] = RIDE
        elif region["style"] == "hand":
            n["pitch"] = HAND_MAP.get(n["pitch"], 63)
            if n["pitch"] == 62:
                v = int(v * 0.8)
        n["velocity"] = velocity_scale(v, region["intensity"])
        out.append(n)
    return out


def ambience_asset(song: Song) -> Optional[str]:
    clips = song["tracks"]["ambience"].get("clips") or []
    if clips:
        return clips[0]["assetId"]
    known = {a["id"] for a in song.get("assets", [])}
    for item in (song.get("seed") or {}).get("inputs", []):
        if item.get("kind") == "sound" and item.get("assetId") in known:
            return item["assetId"]
    return None


def ambience_clips(song: Song, region: Dict[str, Any], section: Dict[str, Any], asset_id: Optional[str]) -> List[Dict[str, Any]]:
    if not region["play"] or not asset_id:
        return []
    start, end = section_window(song, section)
    gain = max(0.0, min(1.0, 0.4 + 0.8 * region["intensity"]))
    if region["style"] == "soft":
        gain *= 0.6
    return [{"assetId": asset_id, "start": start, "duration": end - start, "loop": True, "gain": round(gain, 3)}]


# ----------------------------------------------------------------------------------------------- regeneration


def _replace(notes: Sequence[Note], fresh: Sequence[Note], start: int, end: int) -> List[Note]:
    out = [n for n in notes if not start <= n["start"] < end] + [n for n in fresh if start <= n["start"] < end]
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    return out


def regenerate_region(song: Song, track: str, section_id: str, variation: int = 0, line: Optional[Sequence[Note]] = None) -> None:
    """Rebuild one track in one section from its region, in place. Locks are the caller's business."""
    section = section_by_id(song, section_id)
    region = region_of(song, track, section_id)
    start, end = section_window(song, section)
    tr = song["tracks"][track]
    play = bool(region["play"])
    if track == "ambience":
        tr["clips"] = [c for c in tr["clips"] if not start <= c["start"] < end] + ambience_clips(song, region, section, ambience_asset(song))
        tr["clips"].sort(key=lambda c: c["start"])
        return
    if track in ("vocal", "melody"):
        if line is None:
            line = section_line(song, section)
        line = M.clip_notes(line, start, end)
        if not play or not line:
            fresh: List[Note] = []
        elif track == "vocal":
            old = [n for n in tr["notes"] if start <= n["start"] < end]
            fresh = vocal_from_line(song, line, old, region["intensity"])
        else:
            vocal_region = region_of(song, "vocal", section_id)
            fresh = melody_from_line(song, line, region, bool(vocal_region["play"]), start, end)
    elif not play:
        fresh = []
    elif track == "guitar":
        fresh = guitar_notes(song, region, start, end)
    elif track == "bass":
        fresh = bass_region_notes(song, region, start, end, variation)
    else:
        fresh = drum_region_notes(song, region, section, variation)
    tr["notes"] = _replace(tr["notes"], fresh, start, end)


def refresh_rhythm(song: Song) -> None:
    """``guitar.rhythm`` names the preset of the first playing guitar region."""
    guitar = song["tracks"]["guitar"]
    for region in guitar["regions"]:
        if region["play"]:
            preset = guitar_preset(song, region) if region["style"] != "sustain" else None
            if preset:
                guitar["rhythm"] = {"family": preset["family"], "presetId": preset["id"]}
            return


def regenerate_all(
    song: Song,
    tracks: Optional[Sequence[str]] = None,
    sections: Optional[Sequence[str]] = None,
    only_unlocked: bool = True,
    variation: int = 0,
) -> None:
    """Regenerate ``tracks`` (default all) in ``sections`` (default all). With ``only_unlocked`` (the default) a
    track locked in a section is left alone."""
    tracks = list(tracks or TRACKS)
    base: Optional[List[Note]] = None
    lines: Dict[str, List[Note]] = {}
    for section in song["sections"]:
        if sections is not None and section["id"] not in sections:
            continue
        if "vocal" in tracks or "melody" in tracks:
            start, end = section_window(song, section)
            has_own = any(start <= n["start"] < end for t in ("vocal", "melody") for n in song["tracks"][t]["notes"])
            if not has_own and base is None:
                base = base_line(song)
            lines[section["id"]] = section_line(song, section, base)
    for section in song["sections"]:
        if sections is not None and section["id"] not in sections:
            continue
        for track in ("vocal", "melody", "guitar", "bass", "drums", "ambience"):
            if track not in tracks or (only_unlocked and is_locked(song, track, section["id"])):
                continue
            regenerate_region(song, track, section["id"], variation, lines.get(section["id"]))
    refresh_rhythm(song)


def write_line(song: Song, section_id: str, line: Sequence[Note], force: bool = False) -> List[str]:
    """Put a new sung line into the vocal and melody tracks of a section (those that play and, unless ``force``,
    are not locked). Returns the tracks written."""
    written = []
    for track in ("vocal", "melody"):
        if not region_of(song, track, section_id)["play"]:
            continue
        if not force and is_locked(song, track, section_id):
            continue
        written.append(track)
    # the vocal is written first: a melody in style answer reads the line, not the vocal notes
    for track in written:
        regenerate_region(song, track, section_id, line=line)
    return written


def clamp_unit(x: float) -> float:
    return max(0.0, min(1.0, x))


__all__ = [name for name in dir() if not name.startswith("_")]
