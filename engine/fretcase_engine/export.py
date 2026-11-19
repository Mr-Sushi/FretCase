"""Song file export: MIDI (all six tracks), ABC and MusicXML (melody, lyrics, chord symbols, guitar diagrams).

New FretCase code, written against the song model (FretStudio's exporters work on ABC strings).
"""
from __future__ import annotations

import struct
from typing import Any, Dict, List, Sequence, Tuple
from xml.sax.saxutils import escape

from fretcase_engine.chord_spelling import NAME_TO_PC, spell_pc
from fretcase_engine.common import TPQ, bar_ticks, key_text, meter_text
from fretcase_engine.music_representation import key_signature_alterations

Song = Dict[str, Any]
PROGRAMS = {"piano": 0, "nylon-lead": 24, "nylon": 24, "steel": 25, "finger-bass": 33, "synth-female": 54, "synth-male": 52}


# ------------------------------------------------------------------------------------------------- MIDI


def _vlq(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _track(events: List[Tuple[int, int, bytes]]) -> bytes:
    """events: (tick, order, raw message). Returns an MTrk chunk."""
    data = b""
    last = 0
    for tick, _, raw in sorted(events, key=lambda e: (e[0], e[1])):
        data += _vlq(tick - last) + raw
        last = tick
    data += _vlq(0) + b"\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + data


def to_midi(song: Song) -> bytes:
    meter = song["meter"]
    den_pow = {2: 1, 4: 2, 8: 3}[meter["denominator"]]
    micros = int(round(60_000_000 / float(song["tempo"])))
    conductor: List[Tuple[int, int, bytes]] = [
        (0, 0, b"\xff\x51\x03" + micros.to_bytes(3, "big")),
        (0, 0, b"\xff\x58\x04" + bytes([meter["numerator"], den_pow, 24, 8])),
        (0, 0, b"\xff\x03" + bytes([len(song["title"].encode("utf-8")[:60])]) + song["title"].encode("utf-8")[:60]),
    ]
    tracks = [_track(conductor)]
    channel = 0
    for name in ("vocal", "melody", "guitar", "bass", "drums"):
        track = song["tracks"][name]
        is_drums = name == "drums"
        ch = 9 if is_drums else channel
        events: List[Tuple[int, int, bytes]] = [(0, 0, b"\xff\x03" + bytes([len(name)]) + name.encode())]
        if not is_drums:
            events.append((0, 1, bytes([0xC0 | ch, PROGRAMS.get(track["instrument"], 0)])))
            channel += 1
        for note in track["notes"]:
            if name == "vocal" and note.get("lyric"):
                text = note["lyric"].encode("utf-8")
                events.append((note["start"], 2, b"\xff\x05" + _vlq(len(text)) + text))
            vel = int(note.get("velocity", 90))
            events.append((note["start"], 3, bytes([0x90 | ch, note["pitch"], vel])))
            events.append((note["start"] + note["duration"], 2, bytes([0x80 | ch, note["pitch"], 0])))
        tracks.append(_track(events))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TPQ)
    return header + b"".join(tracks)


# ------------------------------------------------------------------------------------------------- shared note layout


def _mono(notes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Melody as a single line: later notes cut earlier overlapping ones."""
    out: List[Dict[str, Any]] = []
    for n in sorted(notes, key=lambda x: (x["start"], -x["pitch"])):
        if out and out[-1]["start"] + out[-1]["duration"] > n["start"]:
            if out[-1]["start"] == n["start"]:
                continue
            out[-1] = {**out[-1], "duration": n["start"] - out[-1]["start"]}
        out.append(dict(n))
    return out


def _split_at_bars(notes: Sequence[Dict[str, Any]], bt: int, length: int) -> List[Dict[str, Any]]:
    """Melody and rests as events in bar-sized pieces: {start, duration, pitch|None, tie, lyric}."""
    events: List[Dict[str, Any]] = []
    position = 0

    def add(start: int, duration: int, pitch, **extra) -> None:
        while duration > 0:
            room = bt - (start % bt)
            piece = min(duration, room)
            events.append({"start": start, "duration": piece, "pitch": pitch, "tie_next": piece < duration and pitch is not None, "tie_prev": extra.get("first") is False, "lyric": extra.get("lyric") if extra.get("first", True) else None, "lineEnd": extra.get("lineEnd") if extra.get("first", True) else None})
            start += piece
            duration -= piece
            extra = {**extra, "first": False}

    for n in _mono(notes):
        if n["start"] > position:
            add(position, n["start"] - position, None)
        add(n["start"], n["duration"], n["pitch"], lyric=n.get("lyric"), lineEnd=n.get("lineEnd"), first=True)
        position = n["start"] + n["duration"]
    if position < length:
        add(position, length - position, None)
    return events


def _chords_by_bar(song: Song) -> Dict[int, Dict[str, Any]]:
    bt = bar_ticks(song["meter"])
    return {c["start"] // bt: c for c in song["harmony"]}


# ------------------------------------------------------------------------------------------------- ABC


def _abc_pitch(pitch: int, key: Dict[str, str], signature: Dict[str, int]) -> str:
    name = spell_pc(pitch % 12, key["tonic"], key["mode"])
    letter = name[0]
    alter = 1 if name.endswith("#") else (-1 if name.endswith("b") else 0)
    octave = pitch // 12 - 1  # C4 = 60 -> 4
    # a pitch spelled B# or Cb belongs to the neighbouring octave
    if letter == "C" and alter == -1:
        octave += 1
    if letter == "B" and alter == 1:
        octave -= 1
    prefix = ""
    if alter != signature.get(letter, 0):
        prefix = {1: "^", -1: "_", 0: "="}[alter]
    if octave >= 5:
        return prefix + letter.lower() + "'" * (octave - 5)
    return prefix + letter + "," * (4 - octave)


def _abc_len(units: int) -> str:
    return "" if units == 1 else str(units)


def to_abc(song: Song) -> str:
    """Melody with chord symbols and lyrics. L:1/16 so that every 120-tick unit is representable."""
    key, meter = song["key"], song["meter"]
    bt = bar_ticks(meter)
    signature = key_signature_alterations(key["tonic"], key["mode"])
    chords = _chords_by_bar(song)
    events = _split_at_bars(song["tracks"]["melody"]["notes"], bt, song["bars"] * bt)
    lyric_notes = {n["start"]: n for n in song["tracks"]["vocal"]["notes"]}
    lines = [
        "X:1",
        f"T:{song['title']}",
        f"M:{meter_text(meter)}",
        "L:1/16",
        f"Q:1/4={int(round(song['tempo']))}",
        f"K:{key_text(key)}",
    ]
    if song.get("capo"):
        lines.insert(3, f"% Capo {song['capo']['fret']} ({song['capo']['shapeKey']} shapes)")
    body: List[str] = []
    lyric_line: List[str] = []
    bar_tokens: List[str] = []
    current_bar = 0
    first_in_bar = True

    def flush() -> None:
        nonlocal bar_tokens
        body.append(" ".join(bar_tokens) + " |")
        bar_tokens = []

    for ev in events:
        bar = ev["start"] // bt
        if bar != current_bar:
            flush()
            current_bar = bar
            first_in_bar = True
        token = ""
        if first_in_bar and bar in chords:
            sym = chords[bar]["symbol"].replace('"', "")
            token += f'"{sym}"'
        first_in_bar = False
        units = max(1, round(ev["duration"] / 120))
        if ev["pitch"] is None:
            token += "z" + _abc_len(units)
        else:
            token += _abc_pitch(ev["pitch"], key, signature) + _abc_len(units) + ("-" if ev["tie_next"] else "")
            lyr = lyric_notes.get(ev["start"], {}).get("lyric") if not ev["tie_prev"] else None
            lyric_line.append(lyr if lyr else "*")
        bar_tokens.append(token)
    flush()
    lines.extend(body)
    if any(x != "*" for x in lyric_line):
        lines.append("w: " + " ".join(lyric_line))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------- MusicXML

_KINDS = [
    ("maj7", "major-seventh"), ("m7", "minor-seventh"), ("dim", "diminished"), ("sus4", "suspended-fourth"), ("sus2", "suspended-second"),
    ("m", "minor"), ("7", "dominant"), ("6", "major-sixth"), ("9", "dominant-ninth"), ("add9", "major"), ("", "major"),
]


def _chord_xml(symbol: str, voicing: Dict[str, Any]) -> str:
    root = symbol[:2] if len(symbol) > 1 and symbol[1] in "#b" else symbol[:1]
    suffix = symbol[len(root):].split("/")[0]
    kind = next((k for s, k in _KINDS if suffix == s), "other")
    alter = {"#": "<root-alter>1</root-alter>", "b": "<root-alter>-1</root-alter>"}.get(root[1:], "")
    xml = f'<harmony><root><root-step>{root[0]}</root-step>{alter}</root><kind text="{escape(suffix)}">{kind}</kind>'
    if voicing:
        xml += f'<frame><frame-strings>6</frame-strings><frame-frets>4</frame-frets><first-fret>{max(1, voicing["baseFret"])}</first-fret>'
        for idx, fret in enumerate(voicing["frets"]):
            if fret >= 0:
                xml += f"<frame-note><string>{6 - idx}</string><fret>{fret}</fret></frame-note>"
        xml += "</frame>"
    return xml + "</harmony>"


def _fifths(key: Dict[str, str]) -> int:
    from fretcase_engine.chord_spelling import key_fifths

    value = key_fifths(key["tonic"], key["mode"])
    return int(value) if value is not None else 0


def to_musicxml(song: Song) -> str:
    key, meter = song["key"], song["meter"]
    bt = bar_ticks(meter)
    chords = _chords_by_bar(song)
    events = _split_at_bars(song["tracks"]["melody"]["notes"], bt, song["bars"] * bt)
    by_bar: Dict[int, List[Dict[str, Any]]] = {}
    for ev in events:
        by_bar.setdefault(ev["start"] // bt, []).append(ev)
    lyric_notes = {n["start"]: n for n in song["tracks"]["vocal"]["notes"]}
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<score-partwise version="3.1"><work><work-title>' + escape(song["title"]) + "</work-title></work>",
        '<part-list><score-part id="P1"><part-name>Melody</part-name></score-part></part-list><part id="P1">',
    ]
    for bar in range(song["bars"]):
        out.append(f'<measure number="{bar + 1}">')
        if bar == 0:
            out.append(
                f"<attributes><divisions>{TPQ}</divisions><key><fifths>{_fifths(key)}</fifths><mode>{key['mode']}</mode></key>"
                f"<time><beats>{meter['numerator']}</beats><beat-type>{meter['denominator']}</beat-type></time>"
                '<clef><sign>G</sign><line>2</line></clef></attributes>'
                f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>{int(round(song["tempo"]))}</per-minute></metronome></direction-type><sound tempo="{song["tempo"]}"/></direction>'
            )
        if bar in chords:
            out.append(_chord_xml(chords[bar]["symbol"], chords[bar].get("voicing") or {}))
        for ev in by_bar.get(bar, []):
            if ev["pitch"] is None:
                out.append(f'<note><rest/><duration>{ev["duration"]}</duration></note>')
                continue
            name = spell_pc(ev["pitch"] % 12, key["tonic"], key["mode"])
            alter = 1 if name.endswith("#") else (-1 if name.endswith("b") else 0)
            octave = ev["pitch"] // 12 - 1 + (1 if name[0] == "C" and alter == -1 else 0) - (1 if name[0] == "B" and alter == 1 else 0)
            alter_xml = f"<alter>{alter}</alter>" if alter else ""
            ties = ("<tie type=\"stop\"/>" if ev["tie_prev"] else "") + ("<tie type=\"start\"/>" if ev["tie_next"] else "")
            lyric = lyric_notes.get(ev["start"], {}).get("lyric") if not ev["tie_prev"] else None
            lyric_xml = f"<lyric><syllabic>single</syllabic><text>{escape(lyric)}</text></lyric>" if lyric else ""
            out.append(f'<note><pitch><step>{name[0]}</step>{alter_xml}<octave>{octave}</octave></pitch><duration>{ev["duration"]}</duration>{ties}{lyric_xml}</note>')
        out.append("</measure>")
    out.append("</part></score-partwise>")
    return "".join(out)
