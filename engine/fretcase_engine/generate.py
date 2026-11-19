"""Song generation and regeneration (offline), as pure functions on song dictionaries.

A song dictionary follows ``shared/schema/song.schema.json``. Functions here never touch ``revision``,
``updatedAt`` or ``id`` handling beyond what they are given: the server owns those.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from fretcase_engine import harmonise as H
from fretcase_engine import melody as M
from fretcase_engine.accompaniment import bass_notes, drum_notes
from fretcase_engine.common import (
    ENGINE_VERSION,
    TPQ,
    TRACKS,
    bar_ticks,
    default_sections,
    is_locked,
    key_text,
    relative_key,
    section_window,
)
from fretcase_engine.rhythm import choose_preset, presets_by_id, realise

Song = Dict[str, Any]

DEFAULT_INSTRUMENTS = {"vocal": "synth-female", "melody": "piano", "guitar": "nylon", "bass": "finger-bass", "drums": "brush-kit", "ambience": "recording"}
DEFAULT_CONTROLS = {"brightness": 0.5, "complexity": 0.5, "density": 0.5}


class CannotApply(Exception):
    """A valid request that cannot be applied (HTTP 422 ``cannot_apply``)."""

    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


def default_bars(seed: Dict[str, Any], meter: Dict[str, int]) -> int:
    motif = seed.get("motif") or []
    if motif:
        end = max(n["start"] + n["duration"] for n in motif)
        if end < 4 * bar_ticks(meter):
            return 8
    return 16


def _seed_text(seed: Dict[str, Any]) -> str:
    parts = [str(i.get("text") or i.get("assetId") or "") for i in seed.get("inputs", [])]
    return "|".join(parts + [str(seed.get("mood", ""))])


def _variant(seed: Dict[str, Any]) -> int:
    return int(hashlib.sha256(_seed_text(seed).encode("utf-8")).hexdigest()[:4], 16) % 3


def song_title(seed: Dict[str, Any]) -> str:
    for item in seed.get("inputs", []):
        if item.get("kind") == "text" and str(item.get("text", "")).strip():
            first = str(item["text"]).strip().splitlines()[0]
            return first[:20]
    mood = str(seed.get("mood") or "").strip()
    return (mood + "的歌")[:80] if mood else "新歌"


def _capo_dict(song: Song) -> Optional[Dict[str, Any]]:
    capo = song.get("capo")
    if not capo:
        return None
    return {"fret": capo["fret"], "shape_key": capo["shapeKey"], "sounding_key": capo["soundingKey"], "reason": capo["reason"]}


def _preset_for(song: Song) -> Dict[str, Any]:
    return presets_by_id()[song["tracks"]["guitar"]["rhythm"]["presetId"]]


def _splice(song: Song, track: str, new_notes: Sequence[Dict[str, Any]], old_notes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Notes of ``track``: new ones in unlocked sections, old ones kept in locked sections (by start tick)."""
    out: List[Dict[str, Any]] = []
    for section in song["sections"]:
        s, e = section_window(song, section)
        source = old_notes if is_locked(song, track, section["id"]) else new_notes
        out.extend(n for n in source if s <= n["start"] < e)
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    return out


def _vocal_from_melody(melody: Sequence[Dict[str, Any]], old_vocal: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    lyrics = {n["start"]: (n.get("lyric"), n.get("lineEnd")) for n in old_vocal}
    out = []
    for n in melody:
        note = {"start": n["start"], "duration": n["duration"], "pitch": n["pitch"], "velocity": n.get("velocity", 90)}
        if n["start"] in lyrics and lyrics[n["start"]][0]:
            note["lyric"] = lyrics[n["start"]][0]
            if lyrics[n["start"]][1]:
                note["lineEnd"] = True
        out.append(note)
    return out


def realise_guitar(song: Song) -> List[Dict[str, Any]]:
    capo = song.get("capo")
    return realise(song["harmony"], _preset_for(song), song["meter"], capo["fret"] if capo else 0)


def generate_song(
    seed: Dict[str, Any],
    song_id: str,
    now: str,
    bars: Optional[int] = None,
    assets: Sequence[Dict[str, Any]] = (),
) -> Song:
    """A six-track song from a confirmed seed card. Deterministic for the same seed."""
    key = dict(seed["key"])
    meter = dict(seed.get("meter") or {"numerator": 4, "denominator": 4})
    tempo = float(seed["tempo"])
    bars = bars or default_bars(seed, meter)
    sections = default_sections(bars)
    controls = dict(DEFAULT_CONTROLS)
    notes = M.build_melody(seed, key, meter, tempo, bars, sections, variant=_variant(seed), seed_text=_seed_text(seed))
    lane = H.lane_for_complexity(controls["complexity"])
    capo, candidates = H.choose_capo(notes, key, meter, bars, lane, controls["brightness"])
    best = candidates[0]
    suggested = dict(seed.get("instruments") or {})
    instruments = {t: suggested.get(t) or DEFAULT_INSTRUMENTS[t] for t in TRACKS}
    preset = choose_preset(meter, controls["density"])
    song: Song = {
        "schemaVersion": "1.0",
        "id": song_id,
        "revision": 0,
        "createdAt": now,
        "updatedAt": now,
        "title": song_title(seed),
        "key": key,
        "meter": meter,
        "tempo": tempo,
        "bars": bars,
        "capo": H.capo_to_song(capo),
        "controls": controls,
        "seed": copy.deepcopy(seed),
        "sections": sections,
        "harmony": H.chord_events(best.picks, meter, 0),
        "tracks": {
            "vocal": {"instrument": instruments["vocal"], "volume": 0.8, "muted": False, "source": "none", "notes": _vocal_from_melody(notes)},
            "melody": {"instrument": instruments["melody"], "volume": 0.8, "muted": False, "notes": notes},
            "guitar": {"instrument": instruments["guitar"], "volume": 0.8, "muted": False, "rhythm": {"family": preset["family"], "presetId": preset["id"]}, "notes": []},
            "bass": {"instrument": instruments["bass"], "volume": 0.8, "muted": False, "notes": []},
            "drums": {"instrument": instruments["drums"], "volume": 0.8, "muted": False, "notes": []},
            "ambience": {"instrument": instruments["ambience"], "volume": 0.8, "muted": False, "clips": _ambience_clips(seed, assets, meter, bars)},
        },
        "locks": [],
        "assets": [copy.deepcopy(a) for a in assets if _asset_used(seed, a)],
        "provenance": {"engine": ENGINE_VERSION, **H.provenance()},
    }
    song["tracks"]["guitar"]["notes"] = realise_guitar(song)
    song["tracks"]["bass"]["notes"] = bass_notes(song["harmony"], meter, controls["density"])
    song["tracks"]["drums"]["notes"] = drum_notes(0, bars, meter, controls["density"])
    return song


def _asset_used(seed: Dict[str, Any], asset: Dict[str, Any]) -> bool:
    return any(i.get("assetId") == asset["id"] for i in seed.get("inputs", []))


def _ambience_clips(seed: Dict[str, Any], assets: Sequence[Dict[str, Any]], meter: Dict[str, int], bars: int) -> List[Dict[str, Any]]:
    length = bars * bar_ticks(meter)
    ids = [i["assetId"] for i in seed.get("inputs", []) if i.get("kind") == "sound" and i.get("assetId")]
    known = {a["id"] for a in assets}
    return [{"assetId": a, "start": 0, "duration": length, "loop": True, "gain": 0.8} for a in ids if a in known][:1]


# ----------------------------------------------------------------------------------------------- regeneration


def harmony_locked_sections(song: Song) -> Set[str]:
    """Sections whose chords must stay: the guitar or the bass is locked there, and both are realised from them."""
    return {s["id"] for s in song["sections"] if is_locked(song, "guitar", s["id"]) or is_locked(song, "bass", s["id"])}


def target_key(song: Song, brightness: float) -> Dict[str, str]:
    """The key's mode follows brightness only at the extremes, relative to the key the user confirmed on the seed card."""
    base = dict((song.get("seed") or {}).get("key") or song["key"])
    if brightness <= 0.1:
        return relative_key(base, "minor") if base["mode"] == "major" else base
    if brightness >= 0.9:
        return relative_key(base, "major") if base["mode"] == "minor" else base
    return base


def _merge_harmony(song: Song, new_events: Sequence[Dict[str, Any]], keep: Set[str]) -> List[Dict[str, Any]]:
    bt = bar_ticks(song["meter"])
    out = []
    old_by_start = {e["start"]: e for e in song["harmony"]}
    new_by_start = {e["start"]: e for e in new_events}
    for section in song["sections"]:
        for bar in range(section["startBar"], section["endBar"]):
            source = old_by_start if section["id"] in keep else new_by_start
            event = source.get(bar * bt) or old_by_start.get(bar * bt) or new_by_start.get(bar * bt)
            if event:
                out.append(event)
    return out


def reharmonise(song: Song) -> Song:
    """Re-harmonise every section whose guitar and bass are unlocked, then realise guitar and bass again."""
    s = copy.deepcopy(song)
    keep = harmony_locked_sections(s)
    controls = s["controls"]
    lane = H.lane_for_complexity(controls["complexity"])
    notes = s["tracks"]["melody"]["notes"]
    if not keep:
        key = target_key(s, controls["brightness"])
        capo, cands = H.choose_capo(notes, key, s["meter"], s["bars"], lane, controls["brightness"])
        s["key"], s["capo"] = key, H.capo_to_song(capo)
    else:
        cands = H.harmonise(notes, s["key"], s["meter"], s["bars"], lane=lane, brightness=controls["brightness"], capo=_capo_dict(s))
    new_events = H.chord_events(cands[0].picks, s["meter"], 0)
    s["harmony"] = _merge_harmony(s, new_events, keep)
    _realise_followers(s, song, harmony_changed=True)
    return s


def _realise_followers(s: Song, old: Song, harmony_changed: bool, guitar: bool = True, bass: bool = True, drums: bool = False) -> None:
    density = s["controls"]["density"]
    if guitar:
        s["tracks"]["guitar"]["notes"] = _splice(s, "guitar", realise_guitar(s), old["tracks"]["guitar"]["notes"])
    if bass:
        s["tracks"]["bass"]["notes"] = _splice(s, "bass", bass_notes(s["harmony"], s["meter"], density), old["tracks"]["bass"]["notes"])
    if drums:
        s["tracks"]["drums"]["notes"] = _splice(s, "drums", drum_notes(0, s["bars"], s["meter"], density), old["tracks"]["drums"]["notes"])


def apply_density(song: Song) -> Song:
    """Density turned: new guitar rhythm preset (same family where the meter has one), bass and drums."""
    s = copy.deepcopy(song)
    guitar = s["tracks"]["guitar"]
    family = guitar["rhythm"]["family"]
    preset = choose_preset(s["meter"], s["controls"]["density"], family)
    guitar["rhythm"] = {"family": preset["family"], "presetId": preset["id"]}
    _realise_followers(s, song, harmony_changed=False, drums=True)
    return s


def set_rhythm(song: Song, family: str, preset_id: str) -> Song:
    presets = presets_by_id()
    preset = presets.get(preset_id)
    meter = f"{song['meter']['numerator']}/{song['meter']['denominator']}"
    if preset is None or preset["family"] != family:
        raise CannotApply("Unknown rhythm preset for that family", {"presetId": preset_id})
    if preset["meter"] != meter:
        raise CannotApply(f"Preset {preset_id} is written for {preset['meter']}, the song is in {meter}", {"presetId": preset_id})
    s = copy.deepcopy(song)
    s["tracks"]["guitar"]["rhythm"] = {"family": family, "presetId": preset_id}
    _realise_followers(s, song, harmony_changed=False, bass=False)
    return s


# ----------------------------------------------------------------------------------------------- another take


def another_take(song: Song, section_id: str, track: Optional[str], state: Dict[str, Any]) -> Tuple[Song, Dict[str, Any]]:
    """Regenerate the unlocked content of one section. ``state`` is the take history of this section and track
    (JSON-serialisable, kept by the server) so that successive calls do not repeat a take until candidates run out."""
    section = next((x for x in song["sections"] if x["id"] == section_id), None)
    if section is None:
        raise CannotApply("Unknown section", {"section": section_id})
    if track == "ambience":
        raise CannotApply("The ambience track has no other takes", {"track": track})
    if track is not None and track not in TRACKS:
        raise CannotApply("Unknown track", {"track": track})
    s = copy.deepcopy(song)
    state = copy.deepcopy(state) if state else {}
    take_no = int(state.get("count", 0)) + 1
    state["count"] = take_no
    bt = bar_ticks(s["meter"])
    sb, eb = section["startBar"], section["endBar"]
    start, end = section_window(s, section)
    unlocked = lambda t: not is_locked(s, t, section_id)  # noqa: E731
    wanted = [track] if track else ["melody", "guitar", "bass", "drums"]
    if track == "vocal":
        wanted = ["melody"]  # the vocal line follows the melody
    changed = False

    has_motif = bool((s.get("seed") or {}).get("motif"))
    if "melody" in wanted and unlocked("melody"):
        if has_motif:
            if track in ("melody", "vocal"):
                raise CannotApply("The melody of this song comes from your hum; use re-hum to change it", {"track": track})
        else:
            variant = (take_no + 1) % 3
            fresh = M.place_into_octave(M.offline_notes(s["key"], s["meter"], s["tempo"], s["bars"], variant, f"{s['id']}|{section_id}|{take_no}"), s["key"])
            window = M.clip_notes(fresh, start, end)
            if window:
                old = s["tracks"]["melody"]["notes"]
                s["tracks"]["melody"]["notes"] = sorted([n for n in old if not start <= n["start"] < end] + window, key=lambda n: (n["start"], n["pitch"]))
                if unlocked("vocal"):
                    vocal = s["tracks"]["vocal"]["notes"]
                    keep = [n for n in vocal if not start <= n["start"] < end]
                    s["tracks"]["vocal"]["notes"] = sorted(keep + _vocal_from_melody(window), key=lambda n: n["start"])
                changed = True
    elif track in ("melody", "vocal") and not unlocked("melody"):
        raise CannotApply("That track is locked in this section", {"track": track, "section": section_id})

    cap = _capo_dict(s)
    lane = H.lane_for_complexity(s["controls"]["complexity"])
    g_free, b_free = unlocked("guitar"), unlocked("bass")
    new_harmony = False
    if track is None and g_free and b_free:
        cands = H.harmonise(s["tracks"]["melody"]["notes"], s["key"], s["meter"], s["bars"], sb, eb, lane, s["controls"]["brightness"], cap, top_n=12)
        used = {tuple(x) for x in state.get("signatures", [])}
        used.add(tuple(e["symbol"] for e in s["harmony"] if sb * bt <= e["start"] < eb * bt))
        fresh = [c for c in cands if c.signature not in used]
        if not fresh:  # candidates ran out: start a new round, only avoiding the current progression
            used = {tuple(e["symbol"] for e in s["harmony"] if sb * bt <= e["start"] < eb * bt)}
            state["signatures"] = []
            fresh = [c for c in cands if c.signature not in used] or cands
        if fresh:
            pick = fresh[0]
            state.setdefault("signatures", []).append(list(pick.signature))
            events = H.chord_events(pick.picks, s["meter"], sb)
            s["harmony"] = [e for e in s["harmony"] if not sb * bt <= e["start"] < eb * bt] + events
            s["harmony"].sort(key=lambda e: e["start"])
            new_harmony = True
            changed = True
    elif track == "guitar" and g_free:
        # same chords, another fingering: avoid the voicings already used in this section
        avoid: Dict[str, Set[Tuple[int, ...]]] = {}
        for name, frets_list in (state.get("voicings") or {}).items():
            avoid[name] = {tuple(f) for f in frets_list}
        shape_symbols = []
        for e in s["harmony"]:
            if sb * bt <= e["start"] < eb * bt:
                shape = e.get("shapeSymbol") or e["symbol"]
                shape_symbols.append(shape)
                avoid.setdefault(shape, set()).add(tuple(e["voicing"]["frets"]))
        cands = H.harmonise(s["tracks"]["melody"]["notes"], s["key"], s["meter"], s["bars"], sb, eb, lane, s["controls"]["brightness"], cap, top_n=1, avoid_voicings=avoid, fixed_symbols=shape_symbols)
        if cands:
            events = H.chord_events(cands[0].picks, s["meter"], sb)
            for old_e, new_e in zip([e for e in s["harmony"] if sb * bt <= e["start"] < eb * bt], events):
                old_e["voicing"] = new_e["voicing"]
            state["voicings"] = {k: [list(f) for f in v] for k, v in avoid.items()}
            new_harmony = True
            changed = True
    elif track in ("guitar", "bass") and not (g_free if track == "guitar" else b_free):
        raise CannotApply("That track is locked in this section", {"track": track, "section": section_id})

    density = s["controls"]["density"]
    if (new_harmony or track in (None, "guitar", "melody", "vocal")) and g_free and track != "bass":
        s["tracks"]["guitar"]["notes"] = _replace_window(s["tracks"]["guitar"]["notes"], realise_guitar(s), start, end)
    if (new_harmony or track in (None, "bass")) and b_free and track not in ("guitar", "drums"):
        fresh_bass = bass_notes(s["harmony"], s["meter"], density)
        if track == "bass":
            fresh_bass = _vary_bass(fresh_bass, take_no)
            changed = True
        s["tracks"]["bass"]["notes"] = _replace_window(s["tracks"]["bass"]["notes"], fresh_bass, start, end)
    if track in (None, "drums") and unlocked("drums"):
        fresh_drums = drum_notes(sb, eb, s["meter"], density, variation=take_no)
        s["tracks"]["drums"]["notes"] = _replace_window(s["tracks"]["drums"]["notes"], fresh_drums, start, end)
        changed = True
    elif track == "drums":
        raise CannotApply("That track is locked in this section", {"track": track, "section": section_id})
    if track is not None and not changed:
        raise CannotApply("Nothing to change for that track in this section", {"track": track, "section": section_id})
    return s, state


def _replace_window(old: Sequence[Dict[str, Any]], fresh: Sequence[Dict[str, Any]], start: int, end: int) -> List[Dict[str, Any]]:
    out = [n for n in old if not start <= n["start"] < end] + [n for n in fresh if start <= n["start"] < end]
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    return out


def _vary_bass(notes: Sequence[Dict[str, Any]], take_no: int) -> List[Dict[str, Any]]:
    out = []
    for i, n in enumerate(notes):
        m = dict(n)
        if take_no % 2 == 1 and i % 2 == 1:
            m["pitch"] = n["pitch"] + 7 if n["pitch"] + 7 <= 59 else n["pitch"]
        elif take_no % 2 == 0 and i % 2 == 1:
            m["pitch"] = n["pitch"] + 12 if n["pitch"] + 12 <= 59 else n["pitch"]
        out.append(m)
    return out


# ----------------------------------------------------------------------------------------------- re-hum


def rehum(song: Song, section_id: str, hum_notes: Sequence[Dict[str, Any]]) -> Song:
    section = next((x for x in song["sections"] if x["id"] == section_id), None)
    if section is None:
        raise CannotApply("Unknown section", {"section": section_id})
    if is_locked(song, "melody", section_id):
        raise CannotApply("The melody is locked in this section", {"track": "melody", "section": section_id})
    if not hum_notes:
        raise CannotApply("No notes could be found in that recording", {"assetId": None})
    s = copy.deepcopy(song)
    start, end = section_window(s, section)
    bt = bar_ticks(s["meter"])
    fitted = M.fit_hum_to_key(hum_notes, s["key"], end - start, bt)
    fitted = [{**n, "start": n["start"] + start} for n in fitted]
    mel = s["tracks"]["melody"]["notes"]
    s["tracks"]["melody"]["notes"] = sorted([n for n in mel if not start <= n["start"] < end] + fitted, key=lambda n: (n["start"], n["pitch"]))
    if not is_locked(s, "vocal", section_id):
        voc = s["tracks"]["vocal"]["notes"]
        old_in = [n for n in voc if start <= n["start"] < end]
        new_vocal = _vocal_from_melody(fitted, old_in if len(old_in) == len(fitted) else ())
        if len(old_in) == len(fitted):  # same number of notes: keep the lyrics by position
            for old_n, new_n in zip(old_in, new_vocal):
                if old_n.get("lyric"):
                    new_n["lyric"] = old_n["lyric"]
                    if old_n.get("lineEnd"):
                        new_n["lineEnd"] = True
        s["tracks"]["vocal"]["notes"] = sorted([n for n in voc if not start <= n["start"] < end] + new_vocal, key=lambda n: n["start"])
    if not (is_locked(s, "guitar", section_id) or is_locked(s, "bass", section_id)):
        lane = H.lane_for_complexity(s["controls"]["complexity"])
        cands = H.harmonise(s["tracks"]["melody"]["notes"], s["key"], s["meter"], s["bars"], section["startBar"], section["endBar"], lane, s["controls"]["brightness"], _capo_dict(s))
        if cands:
            events = H.chord_events(cands[0].picks, s["meter"], section["startBar"])
            s["harmony"] = sorted([e for e in s["harmony"] if not start <= e["start"] < end] + events, key=lambda e: e["start"])
            if not is_locked(s, "guitar", section_id):
                s["tracks"]["guitar"]["notes"] = _replace_window(s["tracks"]["guitar"]["notes"], realise_guitar(s), start, end)
            if not is_locked(s, "bass", section_id):
                s["tracks"]["bass"]["notes"] = _replace_window(s["tracks"]["bass"]["notes"], bass_notes(s["harmony"], s["meter"], s["controls"]["density"]), start, end)
    return s
