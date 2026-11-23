"""Song generation and regeneration (offline), as pure functions on song dictionaries.

A song dictionary follows ``shared/schema/song.schema.json``. Functions here never touch ``revision``,
``updatedAt`` or ``id`` handling beyond what they are given: the server owns those.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from fretcase_engine import harmonise as H
from fretcase_engine import melody as M
from fretcase_engine import regions as R
from fretcase_engine.catalog import DEFAULT_INSTRUMENT, DEFAULT_STYLE, instrument_ids, style_ids
from fretcase_engine.common import (
    CannotApply,
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

__all__ = ["CannotApply"]

Song = Dict[str, Any]

DEFAULT_CONTROLS = {"brightness": 0.5, "complexity": 0.5, "density": 0.5}


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


def _clip_words(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut or text[:limit]


def song_title(seed: Dict[str, Any]) -> str:
    for item in seed.get("inputs", []):
        if item.get("kind") == "text" and str(item.get("text", "")).strip():
            # The first clause, without punctuation: "Seaside at dusk, very windy" -> "Seaside at dusk".
            first = re.split(r"[，。！？；、,.!?;:：\n]+", str(item["text"]).strip())
            first = next((c.strip() for c in first if c.strip()), "")
            if first:
                return _clip_words(first, 32)
    mood = str(seed.get("mood") or "").strip()
    return f"A {mood} song"[:80] if mood else "New song"


def _capo_dict(song: Song) -> Optional[Dict[str, Any]]:
    capo = song.get("capo")
    if not capo:
        return None
    return {"fret": capo["fret"], "shape_key": capo["shapeKey"], "sounding_key": capo["soundingKey"], "reason": capo["reason"]}



def _preset_for(song: Song) -> Dict[str, Any]:
    return presets_by_id()[song["tracks"]["guitar"]["rhythm"]["presetId"]]


def realise_guitar(song: Song) -> List[Dict[str, Any]]:
    """The whole guitar part with the song's current rhythm preset, ignoring regions (kept for tools and tests)."""
    capo = song.get("capo")
    return realise(song["harmony"], _preset_for(song), song["meter"], capo["fret"] if capo else 0)


def _asset_used(seed: Dict[str, Any], asset: Dict[str, Any]) -> bool:
    return any(i.get("assetId") == asset["id"] for i in seed.get("inputs", []))


def build_regions(sections: Sequence[Dict[str, Any]], track: str, style: str, complexity: float, plan: Dict[str, Any], has_ambience: bool) -> List[Dict[str, Any]]:
    play = (plan.get("play") or {}).get(track)
    shift = float(plan.get("intensityShift", 0.0))
    out = []
    for i, section in enumerate(sections):
        on = bool(play[min(i, len(play) - 1)]) if play else True
        if track == "ambience" and not has_ambience:
            on = False
        intensity = R.clamp_unit(R.default_intensity(i, len(sections)) + shift)
        out.append(R.make_region(section["id"], style, complexity, intensity, on))
    return out


def generate_song(
    seed: Dict[str, Any],
    song_id: str,
    now: str,
    bars: Optional[int] = None,
    assets: Sequence[Dict[str, Any]] = (),
    plan: Optional[Dict[str, Any]] = None,
) -> Song:
    """A six-track song from a confirmed seed card. Deterministic for the same seed and plan.

    ``plan`` (used by the candidates) may hold ``controls``, ``tempo``, ``instruments`` and ``styles`` (per track),
    ``complexity`` (per track), ``play`` (per track, a list of booleans by section index) and ``intensityShift``."""
    plan = plan or {}
    key = dict(seed["key"])
    meter = dict(seed.get("meter") or {"numerator": 4, "denominator": 4})
    seed_tempo = float(seed["tempo"])
    tempo = max(40.0, min(220.0, float(plan.get("tempo") or seed_tempo)))
    bars = bars or default_bars(seed, meter)
    sections = default_sections(bars)
    controls = {**DEFAULT_CONTROLS, **(plan.get("controls") or {})}
    notes = M.build_melody(seed, key, meter, seed_tempo, bars, sections, variant=_variant(seed), seed_text=_seed_text(seed))
    lane = H.lane_for_complexity(controls["complexity"])
    capo, candidates = H.choose_capo(notes, key, meter, bars, lane, controls["brightness"])
    best = candidates[0]
    suggested = {t: v for t, v in (seed.get("instruments") or {}).items() if t in TRACKS and v in instrument_ids(t)}
    instruments = {t: (plan.get("instruments") or {}).get(t) or suggested.get(t) or DEFAULT_INSTRUMENT[t] for t in TRACKS}
    styles = {t: (plan.get("styles") or {}).get(t) or DEFAULT_STYLE[t] for t in TRACKS}
    for t in TRACKS:
        if styles[t] not in style_ids(t):
            styles[t] = DEFAULT_STYLE[t]
    kept_assets = [copy.deepcopy(a) for a in assets if _asset_used(seed, a)]
    has_ambience = any(i.get("kind") == "sound" and i.get("assetId") in {a["id"] for a in kept_assets} for i in seed.get("inputs", []))
    family = "arpeggio" if styles["guitar"] == "arpeggio" else "strumming"
    preset = choose_preset(meter, controls["density"], family)
    complexity = {t: (plan.get("complexity") or {}).get(t, controls["density"] if t in ("guitar", "bass", "drums") else 0.5) for t in TRACKS}

    def mix(track: str, **extra: Any) -> Dict[str, Any]:
        return {"instrument": instruments[track], "volume": 0.8, "muted": False, "regions": build_regions(sections, track, styles[track], complexity[track], plan, has_ambience), **extra}

    song: Song = {
        "schemaVersion": "2.0",
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
            "vocal": mix("vocal", source="none", notes=[]),
            "melody": mix("melody", notes=[]),
            "guitar": mix("guitar", rhythm={"family": preset["family"], "presetId": preset["id"]}, notes=[]),
            "bass": mix("bass", notes=[]),
            "drums": mix("drums", notes=[]),
            "ambience": mix("ambience", clips=[]),
        },
        "locks": [],
        "assets": kept_assets,
        "master": {"volume": 0.8, "space": "room"},
        "provenance": {"engine": ENGINE_VERSION, **H.provenance()},
    }
    R.regenerate_all(song, only_unlocked=False)
    return song


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
    """Re-harmonise every section whose guitar and bass are unlocked, then play guitar and bass again."""
    s = copy.deepcopy(song)
    keep = harmony_locked_sections(s)
    controls = s["controls"]
    lane = H.lane_for_complexity(controls["complexity"])
    notes = R.song_line(s)
    if not keep:
        key = target_key(s, controls["brightness"])
        capo, cands = H.choose_capo(notes, key, s["meter"], s["bars"], lane, controls["brightness"])
        s["key"], s["capo"] = key, H.capo_to_song(capo)
    else:
        cands = H.harmonise(notes, s["key"], s["meter"], s["bars"], lane=lane, brightness=controls["brightness"], capo=_capo_dict(s))
    new_events = H.chord_events(cands[0].picks, s["meter"], 0)
    s["harmony"] = _merge_harmony(s, new_events, keep)
    R.regenerate_all(s, tracks=("guitar", "bass"), only_unlocked=True)
    return s


LEVEL_MIDDLE = {"start": 1 / 6, "next": 0.5, "challenge": 5 / 6}


def apply_density(song: Song) -> Song:
    """Density turned: the complexity of every unlocked guitar, bass and drums region follows it."""
    s = copy.deepcopy(song)
    density = s["controls"]["density"]
    for track in ("guitar", "bass", "drums"):
        for region in s["tracks"][track]["regions"]:
            if not is_locked(s, track, region["section"]):
                region["complexity"] = round(density, 3)
    # turning density takes back a preset chosen by hand (setRhythm)
    first = next((r for r in s["tracks"]["guitar"]["regions"] if r["play"]), s["tracks"]["guitar"]["regions"][0])
    preset = choose_preset(s["meter"], density, "arpeggio" if first["style"] == "arpeggio" else "strumming")
    s["tracks"]["guitar"]["rhythm"] = {"family": preset["family"], "presetId": preset["id"]}
    R.regenerate_all(s, tracks=("guitar", "bass", "drums"), only_unlocked=True)
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
    for region in s["tracks"]["guitar"]["regions"]:
        if is_locked(s, "guitar", region["section"]):
            continue
        if family == "arpeggio":
            region["style"] = "arpeggio"
        elif region["style"] not in ("strum", "muted"):
            region["style"] = "strum"
        region["complexity"] = round(LEVEL_MIDDLE[preset["level"]], 3)
    R.regenerate_all(s, tracks=("guitar",), only_unlocked=True)
    return s


# ----------------------------------------------------------------------------------------------- another take


def another_take(song: Song, section_id: str, track: Optional[str], state: Dict[str, Any]) -> Tuple[Song, Dict[str, Any]]:
    """Regenerate the unlocked content of one section. ``state`` is the take history of this section and track
    (JSON-serialisable, kept by the server) so that successive calls do not repeat a take until candidates run out.
    Each region keeps its ``play``, ``complexity``, ``intensity`` and ``style``."""
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
            if window and R.write_line(s, section_id, window):
                changed = True
    elif track in ("melody", "vocal") and not unlocked("melody"):
        raise CannotApply("That track is locked in this section", {"track": track, "section": section_id})

    cap = _capo_dict(s)
    lane = H.lane_for_complexity(s["controls"]["complexity"])
    g_free, b_free = unlocked("guitar"), unlocked("bass")
    new_harmony = False
    line = R.song_line(s)
    if track is None and g_free and b_free:
        cands = H.harmonise(line, s["key"], s["meter"], s["bars"], sb, eb, lane, s["controls"]["brightness"], cap, top_n=12)
        used = {tuple(x) for x in state.get("signatures", [])}
        used.add(tuple(e["symbol"] for e in s["harmony"] if sb * bt <= e["start"] < eb * bt))
        fresh_c = [c for c in cands if c.signature not in used]
        if not fresh_c:  # candidates ran out: start a new round, only avoiding the current progression
            used = {tuple(e["symbol"] for e in s["harmony"] if sb * bt <= e["start"] < eb * bt)}
            state["signatures"] = []
            fresh_c = [c for c in cands if c.signature not in used] or cands
        if fresh_c:
            pick = fresh_c[0]
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
        cands = H.harmonise(line, s["key"], s["meter"], s["bars"], sb, eb, lane, s["controls"]["brightness"], cap, top_n=1, avoid_voicings=avoid, fixed_symbols=shape_symbols)
        if cands:
            events = H.chord_events(cands[0].picks, s["meter"], sb)
            for old_e, new_e in zip([e for e in s["harmony"] if sb * bt <= e["start"] < eb * bt], events):
                old_e["voicing"] = new_e["voicing"]
            state["voicings"] = {k: [list(f) for f in v] for k, v in avoid.items()}
            new_harmony = True
            changed = True
    elif track in ("guitar", "bass") and not (g_free if track == "guitar" else b_free):
        raise CannotApply("That track is locked in this section", {"track": track, "section": section_id})

    if new_harmony and g_free and track != "bass":
        R.regenerate_region(s, "guitar", section_id)
    if b_free and track not in ("guitar", "drums") and (new_harmony or track == "bass"):
        R.regenerate_region(s, "bass", section_id, variation=take_no if track == "bass" else 0)
        changed = changed or track == "bass"
    if track in (None, "drums") and unlocked("drums"):
        R.regenerate_region(s, "drums", section_id, variation=take_no)
        changed = True
    elif track == "drums":
        raise CannotApply("That track is locked in this section", {"track": track, "section": section_id})
    if track is not None and not changed:
        raise CannotApply("Nothing to change for that track in this section", {"track": track, "section": section_id})
    R.refresh_rhythm(s)
    return s, state


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
    fitted = [{**n, "start": n["start"] + start} for n in M.fit_hum_to_key(hum_notes, s["key"], end - start, bt)]
    R.write_line(s, section_id, fitted)
    reharmonise_section(s, section)
    return s


def reharmonise_section(s: Song, section: Dict[str, Any]) -> None:
    """Fit the chords of one section to its line again (in place) unless the guitar or the bass is locked there."""
    section_id = section["id"]
    start, end = section_window(s, section)
    if is_locked(s, "guitar", section_id) or is_locked(s, "bass", section_id):
        return
    lane = H.lane_for_complexity(s["controls"]["complexity"])
    cands = H.harmonise(R.song_line(s), s["key"], s["meter"], s["bars"], section["startBar"], section["endBar"], lane, s["controls"]["brightness"], _capo_dict(s))
    if cands:
        events = H.chord_events(cands[0].picks, s["meter"], section["startBar"])
        s["harmony"] = sorted([e for e in s["harmony"] if not start <= e["start"] < end] + events, key=lambda e: e["start"])
        R.regenerate_all(s, tracks=("guitar", "bass"), sections=[section_id], only_unlocked=True)
