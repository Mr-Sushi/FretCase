"""The catalogue of sounds and playing styles that GET /api/catalog returns (docs/api.md).

Sounds (``mix.instrument``) and styles (``region.style``) are ids; the app shows only the labels.
"""
from __future__ import annotations

from typing import Dict, List

INSTRUMENTS: Dict[str, List[Dict[str, str]]] = {
    "vocal": [{"id": "synth-male", "label": "男声"}, {"id": "synth-female", "label": "女声"}, {"id": "synth-soft", "label": "轻声"}],
    "melody": [{"id": "harmonica", "label": "口琴"}, {"id": "piano", "label": "钢琴"}, {"id": "whistle", "label": "口哨"}, {"id": "flute", "label": "长笛"}],
    "guitar": [{"id": "steel", "label": "木吉他"}, {"id": "nylon", "label": "尼龙吉他"}, {"id": "electric-clean", "label": "电吉他（干净）"}, {"id": "ukulele", "label": "尤克里里"}],
    "bass": [{"id": "finger-bass", "label": "指弹贝斯"}, {"id": "upright-bass", "label": "低音提琴"}, {"id": "synth-bass", "label": "合成器贝斯"}],
    "drums": [{"id": "jazz-kit", "label": "爵士鼓"}, {"id": "pop-kit", "label": "流行鼓"}, {"id": "hand-drum", "label": "手鼓"}],
    "ambience": [{"id": "recording", "label": "原声"}],
}

STYLES: Dict[str, List[Dict[str, str]]] = {
    "vocal": [{"id": "plain", "label": "只唱主旋律"}, {"id": "harmony", "label": "加一层和声"}],
    "melody": [{"id": "follow", "label": "跟着人声"}, {"id": "answer", "label": "人声停时才出来"}],
    "guitar": [{"id": "strum", "label": "扫弦"}, {"id": "arpeggio", "label": "分解和弦"}, {"id": "muted", "label": "闷音扫弦"}, {"id": "sustain", "label": "只弹长音"}],
    "bass": [{"id": "sustain", "label": "长音"}, {"id": "groove", "label": "跟着鼓点"}, {"id": "walking", "label": "走动"}],
    "drums": [{"id": "brush", "label": "刷子"}, {"id": "sticks", "label": "鼓棒"}, {"id": "hand", "label": "只有手鼓"}],
    "ambience": [{"id": "recording", "label": "原声"}, {"id": "soft", "label": "柔和一点"}],
}

SPACES = [{"id": "dry", "label": "干净"}, {"id": "room", "label": "房间"}, {"id": "hall", "label": "大厅"}]
CARD_STYLES = ["ink", "comic", "xieyi", "original", "text"]

DEFAULT_STYLE = {"vocal": "plain", "melody": "follow", "guitar": "strum", "bass": "groove", "drums": "sticks", "ambience": "recording"}
DEFAULT_INSTRUMENT = {"vocal": "synth-female", "melody": "piano", "guitar": "steel", "bass": "finger-bass", "drums": "pop-kit", "ambience": "recording"}


def instrument_ids(track: str) -> List[str]:
    return [i["id"] for i in INSTRUMENTS[track]]


def style_ids(track: str) -> List[str]:
    return [s["id"] for s in STYLES[track]]


def instrument_label(track: str, instrument: str) -> str:
    return next((i["label"] for i in INSTRUMENTS[track] if i["id"] == instrument), instrument)


def style_label(track: str, style: str) -> str:
    return next((s["label"] for s in STYLES[track] if s["id"] == style), style)


def catalog() -> dict:
    """The body of GET /api/catalog without the rhythm presets (the server adds those)."""
    return {"instruments": INSTRUMENTS, "styles": STYLES, "spaces": SPACES, "cardStyles": CARD_STYLES}
