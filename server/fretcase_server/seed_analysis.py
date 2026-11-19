"""Offline seed card: colour statistics for photos, keywords for text, beat and loudness for sounds, notes for hums."""
from __future__ import annotations

import colorsys
import io
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from fretcase_server import hum

# keyword -> (mood label, mode, tempo delta, hint)  Chinese and English
KEYWORDS: List[Tuple[Tuple[str, ...], str, str, int]] = [
    (("雨", "夜", "孤", "想念", "思念", "伤", "难过", "安静", "rain", "night", "alone", "miss", "quiet", "sad", "blue"), "安静偏冷", "minor", -12),
    (("海", "风", "傍晚", "黄昏", "夕阳", "温柔", "平静", "sea", "wind", "sunset", "evening", "calm", "gentle"), "平静偏暖", "major", -6),
    (("笑", "开心", "快乐", "阳光", "春", "朋友", "节日", "happy", "sun", "spring", "friend", "party", "joy", "dance"), "明亮轻快", "major", 14),
    (("路", "旅", "出发", "远方", "山", "road", "travel", "journey", "mountain", "away"), "开阔向前", "major", 6),
]
KEY_FOR_MOOD = {
    ("major", "warm"): {"tonic": "G", "mode": "major"},
    ("major", "cool"): {"tonic": "D", "mode": "major"},
    ("minor", "warm"): {"tonic": "A", "mode": "minor"},
    ("minor", "cool"): {"tonic": "E", "mode": "minor"},
}


def analyse_text(text: str) -> Dict[str, Any]:
    low = text.lower()
    scores: Dict[str, int] = {}
    chosen: Optional[Tuple[str, str, int]] = None
    for words, mood, mode, delta in KEYWORDS:
        hits = [w for w in words if w in low]
        if hits:
            scores[mood] = len(hits)
            if chosen is None or len(hits) > scores.get(chosen[0], 0):
                chosen = (mood, mode, delta)
    if chosen is None:
        return {"mood": None, "mode": None, "tempo_delta": 0, "reason": "没有找到情绪关键词，沿用默认"}
    return {"mood": chosen[0], "mode": chosen[1], "tempo_delta": chosen[2], "reason": f"文字里的词指向“{chosen[0]}”"}


def analyse_photo(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((96, 96))
        arr = np.asarray(img, dtype=np.float32) / 255.0
    except Exception:
        return None
    r, g, b = arr[..., 0].mean(), arr[..., 1].mean(), arr[..., 2].mean()
    h, s, v = colorsys.rgb_to_hsv(float(r), float(g), float(b))
    warmth = float(r - b)
    return {"brightness": float(v), "saturation": float(s), "warmth": warmth, "size": img.size}


def analyse_sound(path: Path) -> Optional[Dict[str, Any]]:
    samples = hum.load_samples(path, 11025)
    if samples is None or len(samples) < 11025:
        return None
    rms = float(np.sqrt(np.mean(samples**2)))
    # onset envelope from frame energy, tempo from its autocorrelation
    frame = 512
    n = len(samples) // frame
    env = np.sqrt((samples[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
    flux = np.maximum(np.diff(env), 0)
    tempo = None
    if len(flux) > 40 and flux.std() > 1e-6:
        flux = flux - flux.mean()
        ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
        fps = 11025 / frame
        lo, hi = int(fps * 60 / 140), int(fps * 60 / 60)
        if hi < len(ac) and ac[0] > 0:
            lag = lo + int(np.argmax(ac[lo:hi]))
            if ac[lag] / ac[0] > 0.25:
                tempo = 60.0 * fps / lag
    return {"rms": rms, "tempo": tempo}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_seed(
    inputs: Sequence[Dict[str, Any]],
    asset_loader: Callable[[str], Tuple[Dict[str, Any], Path]],
    transcribe: Callable[[Path, Optional[float]], Optional[Dict[str, Any]]] = hum.transcribe,
) -> Dict[str, Any]:
    """Seed card from the captured inputs. ``asset_loader(assetId) -> (info, path)``."""
    reasons: List[Dict[str, str]] = []
    tempo_votes: List[float] = []
    mode_votes: List[Tuple[str, float]] = []
    mood: Optional[str] = None
    warm = 0.0
    instruments: Dict[str, str] = {}
    motif: List[Dict[str, Any]] = []
    hum_key: Optional[Dict[str, str]] = None
    hum_tempo: Optional[float] = None
    hum_missing = False

    sound_tempo: Optional[float] = None
    for item in inputs:
        kind = item["kind"]
        if kind == "text":
            t = analyse_text(item.get("text", ""))
            if t["mood"]:
                mood = mood or t["mood"]
                mode_votes.append((t["mode"], 1.0))
                tempo_votes.append(88 + t["tempo_delta"])
            reasons.append({"field": "mood", "text": t["reason"][:120]})
        elif kind == "photo":
            info, path = asset_loader(item["assetId"])
            stats = analyse_photo(path.read_bytes())
            if stats:
                warm += stats["warmth"]
                bright = stats["brightness"]
                mode_votes.append(("major" if bright >= 0.45 else "minor", 1.0 + abs(bright - 0.45)))
                tempo_votes.append(70 + 40 * stats["saturation"] * (0.5 + bright))
                if mood is None:
                    mood = ("明亮" if bright >= 0.55 else "安静") + ("偏暖" if stats["warmth"] > 0 else "偏冷")
                reasons.append({"field": "mood", "text": f"照片{'偏亮' if bright >= 0.55 else '偏暗'}、{'偏暖' if stats['warmth'] > 0 else '偏冷'}，饱和度{stats['saturation']:.2f}"})
                instruments["guitar"] = "nylon" if stats["warmth"] > 0 else "steel"
            else:
                reasons.append({"field": "mood", "text": "照片无法读取，没有用它"})
        elif kind == "sound":
            info, path = asset_loader(item["assetId"])
            stats = analyse_sound(path)
            if stats and stats["tempo"]:
                sound_tempo = clamp(stats["tempo"], 60, 120)
                reasons.append({"field": "tempo", "text": f"声音里有大约每分钟 {sound_tempo:.0f} 拍的节拍"})
            elif stats:
                tempo_votes.append(76 if stats["rms"] < 0.08 else 96)
                reasons.append({"field": "tempo", "text": "声音没有清楚的节拍，按响度定速度"})
            instruments["ambience"] = "recording"
        elif kind == "hum":
            info, path = asset_loader(item["assetId"])
            result = transcribe(path, None)
            if result is None:
                hum_missing = True
                reasons.append({"field": "motif", "text": "这台设备上无法转写哼唱，先不带旋律"})
            elif not result["motif"]:
                reasons.append({"field": "motif", "text": "没有听到清楚的音高，先不带旋律"})
            else:
                motif = result["motif"]
                hum_key = result["key"]
                hum_tempo = result["tempo"] if result["tempoFromHum"] else None
                reasons.append({"field": "motif", "text": f"从哼唱转写出 {result['noteCount']} 个音"})
    # tempo: sound beat > hum > votes > default
    if sound_tempo:
        tempo = sound_tempo
    elif hum_tempo:
        tempo = hum_tempo
        reasons.append({"field": "tempo", "text": f"按哼唱的节奏定为每分钟 {tempo:.0f} 拍"})
    elif tempo_votes:
        tempo = clamp(sum(tempo_votes) / len(tempo_votes), 60, 120)
        reasons.append({"field": "tempo", "text": f"由情绪定为每分钟 {tempo:.0f} 拍"})
    else:
        tempo = 90.0
        reasons.append({"field": "tempo", "text": "没有线索，用默认的每分钟 90 拍"})
    tempo = float(round(tempo))
    # key: hum > mood
    if hum_key:
        key = hum_key
        reasons.append({"field": "key", "text": f"哼唱落在 {key['tonic']}{'小调' if key['mode'] == 'minor' else '大调'}"})
    else:
        mode = "major"
        if mode_votes:
            weight = {"major": 0.0, "minor": 0.0}
            for m, w in mode_votes:
                weight[m] += w
            mode = "minor" if weight["minor"] > weight["major"] else "major"
        key = KEY_FOR_MOOD[(mode, "warm" if warm >= 0 else "cool")]
        reasons.append({"field": "key", "text": f"由情绪定为 {key['tonic']}{'小调' if mode == 'minor' else '大调'}"})
    if mood is None:
        mood = "安静偏暖" if key["mode"] == "major" else "安静偏冷"
    reasons.append({"field": "meter", "text": "默认 4/4"})
    if instruments:
        reasons.append({"field": "instruments", "text": "按照片冷暖和声音选乐器"})
    del hum_missing
    seed: Dict[str, Any] = {
        "inputs": [dict(i) for i in inputs],
        "key": key,
        "tempo": tempo,
        "meter": {"numerator": 4, "denominator": 4},
        "mood": mood[:24],
        "reasons": [{"field": r["field"], "text": r["text"][:120]} for r in reasons],
        "source": "offline",
    }
    if motif:
        seed["motif"] = motif
    if instruments:
        seed["instruments"] = instruments
    return seed
