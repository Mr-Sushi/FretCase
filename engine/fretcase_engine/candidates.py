"""Three different arrangements of one seed card for the pick screen (POST /api/candidates). New FretCase code.

The three share the melody (from the hummed motif, or the offline melody) and differ in instruments, playing styles,
harmony colour (the complexity knob, which picks the chord lane), which sections each track plays in, and who leads.
Names, tags and the one-sentence reason are written by rules, in short plain Chinese with no jargon.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fretcase_engine import regions as R
from fretcase_engine.catalog import instrument_label
from fretcase_engine.common import TRACKS
from fretcase_engine.generate import _seed_text, generate_song
from fretcase_engine.editing import set_lead

Song = Dict[str, Any]

# sections are given as four flags: opening, verse, chorus, ending
ARCHETYPES: List[Dict[str, Any]] = [
    {
        "id": "dusk-folk", "name": "黄昏民谣", "tags": ["温暖", "慢一点"], "lane": 0.5, "lead": "vocal", "shift": -0.05,
        "time": {"day": 1, "dusk": 3, "night": 1},
        "inst": {"vocal": "synth-female", "melody": "piano", "guitar": "nylon", "bass": "finger-bass", "drums": "jazz-kit"},
        "style": {"vocal": "plain", "melody": "follow", "guitar": "arpeggio", "bass": "sustain", "drums": "brush"},
        "play": {"vocal": "0111", "melody": "1001", "guitar": "1111", "bass": "0111", "drums": "0011", "ambience": "1111"},
    },
    {
        "id": "bright-strum", "name": "轻快扫弦", "tags": ["轻快", "木吉他"], "lane": 0.2, "lead": "guitar", "shift": 0.1,
        "time": {"day": 3, "dusk": 1, "night": 0},
        "inst": {"vocal": "synth-male", "melody": "harmonica", "guitar": "steel", "bass": "finger-bass", "drums": "pop-kit"},
        "style": {"vocal": "plain", "melody": "follow", "guitar": "strum", "bass": "groove", "drums": "sticks"},
        "play": {"vocal": "0111", "melody": "1010", "guitar": "1111", "bass": "0111", "drums": "0111", "ambience": "1111"},
    },
    {
        "id": "quiet-piano", "name": "安静钢琴", "tags": ["安静", "很轻"], "lane": 0.8, "lead": "melody", "shift": -0.2,
        "time": {"day": 0, "dusk": 1, "night": 3},
        "inst": {"vocal": "synth-soft", "melody": "piano", "guitar": "nylon", "bass": "upright-bass", "drums": "jazz-kit"},
        "style": {"vocal": "plain", "melody": "follow", "guitar": "sustain", "bass": "sustain", "drums": "brush"},
        "play": {"vocal": "0111", "melody": "1111", "guitar": "0111", "bass": "0011", "drums": "0000", "ambience": "1111"},
    },
    {
        "id": "campfire", "name": "手鼓篝火", "tags": ["热闹", "围坐"], "lane": 0.5, "lead": "vocal", "shift": 0.05,
        "time": {"day": 2, "dusk": 2, "night": 1},
        "inst": {"vocal": "synth-male", "melody": "whistle", "guitar": "ukulele", "bass": "upright-bass", "drums": "hand-drum"},
        "style": {"vocal": "harmony", "melody": "answer", "guitar": "muted", "bass": "groove", "drums": "hand"},
        "play": {"vocal": "0111", "melody": "0111", "guitar": "1111", "bass": "0111", "drums": "0111", "ambience": "1111"},
    },
    {
        "id": "night-electric", "name": "夜色电吉他", "tags": ["深夜", "悠长"], "lane": 0.8, "lead": "guitar", "shift": -0.1,
        "time": {"day": 0, "dusk": 1, "night": 3},
        "inst": {"vocal": "synth-soft", "melody": "flute", "guitar": "electric-clean", "bass": "synth-bass", "drums": "pop-kit"},
        "style": {"vocal": "plain", "melody": "follow", "guitar": "arpeggio", "bass": "sustain", "drums": "brush"},
        "play": {"vocal": "0111", "melody": "1001", "guitar": "1111", "bass": "0111", "drums": "0011", "ambience": "1111"},
    },
    {
        "id": "long-flute", "name": "悠长长笛", "tags": ["安静", "开阔"], "lane": 0.2, "lead": "melody", "shift": -0.05,
        "time": {"day": 1, "dusk": 2, "night": 2},
        "inst": {"vocal": "synth-female", "melody": "flute", "guitar": "steel", "bass": "upright-bass", "drums": "jazz-kit"},
        "style": {"vocal": "plain", "melody": "follow", "guitar": "sustain", "bass": "walking", "drums": "brush"},
        "play": {"vocal": "0011", "melody": "1111", "guitar": "1111", "bass": "0111", "drums": "0011", "ambience": "1111"},
    },
    {
        "id": "cafe-jazz", "name": "小酒馆", "tags": ["慵懒", "有点爵士"], "lane": 0.8, "lead": "guitar", "shift": 0.0,
        "time": {"day": 1, "dusk": 1, "night": 2},
        "inst": {"vocal": "synth-male", "melody": "piano", "guitar": "electric-clean", "bass": "upright-bass", "drums": "jazz-kit"},
        "style": {"vocal": "plain", "melody": "answer", "guitar": "muted", "bass": "walking", "drums": "brush"},
        "play": {"vocal": "0111", "melody": "0111", "guitar": "1111", "bass": "1111", "drums": "0111", "ambience": "1111"},
    },
    {
        "id": "whistle-walk", "name": "口哨散步", "tags": ["轻松", "明亮"], "lane": 0.2, "lead": "melody", "shift": 0.1,
        "time": {"day": 3, "dusk": 1, "night": 0},
        "inst": {"vocal": "synth-female", "melody": "whistle", "guitar": "ukulele", "bass": "finger-bass", "drums": "hand-drum"},
        "style": {"vocal": "plain", "melody": "follow", "guitar": "strum", "bass": "groove", "drums": "hand"},
        "play": {"vocal": "0011", "melody": "1111", "guitar": "1111", "bass": "0011", "drums": "0111", "ambience": "1111"},
    },
]

TIME_SETTINGS = {
    "day": {"brightness": 0.65, "tempo": 1.12, "shift": 0.05, "tag": "明亮"},
    "dusk": {"brightness": 0.5, "tempo": 1.0, "shift": 0.0, "tag": "温柔"},
    "night": {"brightness": 0.3, "tempo": 0.85, "shift": -0.1, "tag": "安静"},
}
NEUTRAL = {"brightness": 0.5, "tempo": 1.0, "shift": 0.0, "tag": None}
LEAD_TAG = {"vocal": "人声在前", "melody": "旋律在前", "guitar": "吉他在前"}
SHORT = {
    "guitar": {"strum": "扫弦", "arpeggio": "分解", "muted": "闷音", "sustain": "长音"},
    "bass": {"sustain": "长音", "groove": "跟鼓", "walking": "走动"},
    "drums": {"brush": "刷子", "sticks": "鼓棒", "hand": ""},
}


def signature(guitar: Tuple[str, str], melody: str, drums: Tuple[str, str]) -> Tuple[Any, ...]:
    return (guitar, melody, drums)


def archetype_signature(a: Dict[str, Any]) -> Tuple[Any, ...]:
    return signature((a["inst"]["guitar"], a["style"]["guitar"]), a["inst"]["melody"], (a["inst"]["drums"], a["style"]["drums"]))


def song_signature(song: Song) -> Tuple[Any, ...]:
    t = song["tracks"]
    first = lambda tr: next((r["style"] for r in t[tr]["regions"]), "")  # noqa: E731
    return signature((t["guitar"]["instrument"], first("guitar")), t["melody"]["instrument"], (t["drums"]["instrument"], first("drums")))


def _noise(seed: Dict[str, Any], key: str) -> float:
    return int(hashlib.sha256((_seed_text(seed) + "|" + key).encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF


def _distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    d = 0.0
    for track in ("guitar", "melody", "drums", "bass"):
        d += a["inst"][track] != b["inst"][track]
        d += a["style"][track] != b["style"][track]
    d += 2.0 * (a["lane"] != b["lane"])
    return d


def choose_archetypes(seed: Dict[str, Any], time_of_day: Optional[str], avoid: Sequence[Tuple[Any, ...]]) -> List[Dict[str, Any]]:
    pool = [a for a in ARCHETYPES if archetype_signature(a) not in set(avoid)]
    if len(pool) < 3:
        pool = list(ARCHETYPES)
    weight = lambda a: (a["time"][time_of_day] if time_of_day else 1.5) + _noise(seed, a["id"])  # noqa: E731
    chosen = [max(pool, key=weight)]
    while len(chosen) < 3:
        rest = [a for a in pool if a not in chosen]
        fresh_lane = [a for a in rest if a["lane"] not in {c["lane"] for c in chosen}]
        rest = fresh_lane or rest  # three different harmony colours whenever the pool allows
        chosen.append(max(rest, key=lambda a: weight(a) + 0.8 * min(_distance(a, c) for c in chosen)))
    return chosen


def _flags(pattern: str, count: int) -> List[bool]:
    """Four flags (opening, verse, chorus, ending) spread over however many sections the song has."""
    if count == 1:
        return [pattern[2] == "1"]
    out = []
    for i in range(count):
        role = 0 if i == 0 else (3 if i == count - 1 else (2 if i == count - 2 and count >= 3 else 1))
        out.append(pattern[role] == "1")
    return out


def sound_label(track: str, instrument: str, style: str, plays: bool, has_ambience: bool = True) -> str:
    if track == "ambience":
        return "环境声" if has_ambience else "无"
    if not plays:
        return "不演奏"
    base = instrument_label(track, instrument)
    if track == "vocal":
        return base + ("加和声" if style == "harmony" else "")
    if track == "melody":
        return base + ("应答" if style == "answer" else "")
    return base + SHORT[track].get(style, "")


def _why(seed: Dict[str, Any], a: Dict[str, Any], lead: str) -> str:
    inputs = {i["kind"] for i in seed.get("inputs", [])}
    reason_text = " ".join(r.get("text", "") for r in seed.get("reasons", []))
    clauses = []
    if "photo" in inputs:
        clauses.append("照片偏暖" if "偏暖" in reason_text else ("照片偏冷" if "偏冷" in reason_text else "照片的颜色"))
    if "text" in inputs:
        clauses.append("你写的话")
    if "sound" in inputs:
        clauses.append("你录的声音")
    if not clauses and seed.get("mood"):
        clauses.append(f"心情是{seed['mood']}")
    start = "、".join(clauses[:2]) if clauses else "这些素材"
    guitar = instrument_label("guitar", a["inst"]["guitar"]) + SHORT["guitar"].get(a["style"]["guitar"], "")
    tail = {"vocal": "副歌让人声唱在前面", "melody": "副歌让旋律走在前面", "guitar": "副歌让吉他走在前面"}[lead]
    text = f"{start}，配上{guitar}；{tail}。"
    if seed.get("motif"):
        text = f"{start}，配上{guitar}；副歌用你哼的那句。"
    return text[:80]


def make_candidates(
    seed: Dict[str, Any],
    song_ids: Sequence[str],
    group_id: str,
    now: str,
    bars: Optional[int] = None,
    time_of_day: Optional[str] = None,
    avoid: Sequence[Tuple[Any, ...]] = (),
    assets: Sequence[Dict[str, Any]] = (),
) -> List[Tuple[Song, Dict[str, Any]]]:
    """Three draft songs, each with its ``candidate`` block, and the lead state to keep next to each (for setLead)."""
    time_cfg = TIME_SETTINGS.get(time_of_day or "", NEUTRAL)
    out = []
    for index, a in enumerate(choose_archetypes(seed, time_of_day, avoid)):
        base_tempo = float(seed["tempo"]) * time_cfg["tempo"]
        plan = {
            "controls": {"brightness": time_cfg["brightness"], "complexity": a["lane"], "density": max(0.1, min(0.9, 0.5 + 0.2 * (a["lane"] - 0.5) + (0.1 if time_of_day == "day" else -0.1 if time_of_day == "night" else 0.0)))},
            "tempo": round(base_tempo),
            "instruments": dict(a["inst"]),
            "styles": dict(a["style"]),
            "intensityShift": a["shift"] + time_cfg["shift"],
        }
        song = _build(seed, song_ids[index], now, bars, assets, plan, a)
        count = len(song["sections"])
        lead_state: Dict[str, Any] = {}
        lead = a["lead"]
        chorus = song["sections"][max(0, count - 2) if count >= 3 else count - 1]["id"]
        if not R.region_of(song, lead if lead != "guitar" else "guitar", chorus)["play"]:
            lead = "melody"
        song, lead_state = set_lead(song, chorus, lead, {})
        song["candidate"] = _candidate_block(song, seed, a, index, group_id, time_of_day, lead, time_cfg)
        out.append((song, lead_state))
    return out


def _build(seed: Dict[str, Any], song_id: str, now: str, bars: Optional[int], assets: Sequence[Dict[str, Any]], plan: Dict[str, Any], a: Dict[str, Any]) -> Song:
    from fretcase_engine.generate import default_bars
    from fretcase_engine.common import default_sections

    meter = seed.get("meter") or {"numerator": 4, "denominator": 4}
    count = len(default_sections(bars or default_bars(seed, meter)))
    plan["play"] = {t: _flags(a["play"][t], count) for t in TRACKS}
    return generate_song(seed, song_id, now, bars=bars, assets=assets, plan=plan)


def _candidate_block(song: Song, seed: Dict[str, Any], a: Dict[str, Any], index: int, group_id: str, time_of_day: Optional[str], lead: str, time_cfg: Dict[str, Any]) -> Dict[str, Any]:
    parts = {}
    for track in TRACKS:
        regions = song["tracks"][track]["regions"]
        level = sum((0.35 + 0.65 * r["intensity"]) if r["play"] else 0.0 for r in regions) / max(1, len(regions))
        first = next((r for r in regions if r["play"]), regions[0])
        has_ambience = bool(song["tracks"]["ambience"]["clips"])
        parts[track] = {"level": round(min(1.0, level), 2), "sound": sound_label(track, song["tracks"][track]["instrument"], first["style"], any(r["play"] for r in regions), has_ambience)[:16]}
    tags: List[str] = []
    for tag in list(a["tags"]) + [time_cfg["tag"], LEAD_TAG[lead]]:
        if tag and tag not in tags:
            tags.append(tag[:8])
    block: Dict[str, Any] = {"groupId": group_id, "index": index, "name": a["name"][:12], "tags": tags[:4], "why": _why(seed, a, lead), "parts": parts, "chosen": False}
    if time_of_day:
        block["timeOfDay"] = time_of_day
    return block
