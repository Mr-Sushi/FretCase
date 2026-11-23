"""The catalogue of sounds and playing styles that GET /api/catalog returns (docs/api.md).

Sounds (``mix.instrument``) and styles (``region.style``) are ids; the app shows only the labels.
"""
from __future__ import annotations

from typing import Dict, List

INSTRUMENTS: Dict[str, List[Dict[str, str]]] = {
    "vocal": [{"id": "synth-male", "label": "Male voice"}, {"id": "synth-female", "label": "Female voice"}, {"id": "synth-soft", "label": "Soft voice"}],
    "melody": [{"id": "harmonica", "label": "Harmonica"}, {"id": "piano", "label": "Piano"}, {"id": "whistle", "label": "Whistle"}, {"id": "flute", "label": "Flute"}],
    "guitar": [{"id": "steel", "label": "Steel-string guitar"}, {"id": "nylon", "label": "Nylon guitar"}, {"id": "electric-clean", "label": "Electric guitar (clean)"}, {"id": "ukulele", "label": "Ukulele"}],
    "bass": [{"id": "finger-bass", "label": "Finger bass"}, {"id": "upright-bass", "label": "Upright bass"}, {"id": "synth-bass", "label": "Synth bass"}],
    "drums": [{"id": "jazz-kit", "label": "Jazz kit"}, {"id": "pop-kit", "label": "Pop kit"}, {"id": "hand-drum", "label": "Hand drum"}],
    "ambience": [{"id": "recording", "label": "As recorded"}],
}

STYLES: Dict[str, List[Dict[str, str]]] = {
    "vocal": [{"id": "plain", "label": "Melody only"}, {"id": "harmony", "label": "Add a harmony"}],
    "melody": [{"id": "follow", "label": "Follow the voice"}, {"id": "answer", "label": "Answer when the voice rests"}],
    "guitar": [{"id": "strum", "label": "Strum"}, {"id": "arpeggio", "label": "Picked chords"}, {"id": "muted", "label": "Muted strum"}, {"id": "sustain", "label": "Long notes only"}],
    "bass": [{"id": "sustain", "label": "Long notes"}, {"id": "groove", "label": "With the drums"}, {"id": "walking", "label": "Walking"}],
    "drums": [{"id": "brush", "label": "Brushes"}, {"id": "sticks", "label": "Sticks"}, {"id": "hand", "label": "Hand drum only"}],
    "ambience": [{"id": "recording", "label": "As recorded"}, {"id": "soft", "label": "Softer"}],
}

SPACES = [{"id": "dry", "label": "Dry"}, {"id": "room", "label": "Room"}, {"id": "hall", "label": "Hall"}]
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
