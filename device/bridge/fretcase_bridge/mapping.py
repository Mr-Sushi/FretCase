"""MIDI mapping: controller messages -> raw panel events, and lights -> SysEx."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Union

import mido

TRACKS = ("vocal", "melody", "guitar", "bass", "drums", "ambience")
KNOBS = ("brightness", "complexity", "density", "tempo")
KEYS = (
    "capture",
    "play",
    "undo",
    "another",
    "track.vocal",
    "track.melody",
    "track.guitar",
    "track.bass",
    "track.drums",
    "track.ambience",
)
KEY_MODES = ("off", "on", "blink", "pulse")
RING_PIXELS = 16


@dataclass(frozen=True)
class PlatterTurn:
    delta: int


@dataclass(frozen=True)
class KnobTurn:
    knob: str
    delta: int


@dataclass(frozen=True)
class FaderValue:
    track: str
    value: float


@dataclass(frozen=True)
class KeyChange:
    id: str
    action: Literal["down", "up"]


@dataclass(frozen=True)
class FirmwareVersion:
    version: str


RawEvent = Union[PlatterTurn, KnobTurn, FaderValue, KeyChange, FirmwareVersion]


class MappingError(ValueError):
    pass


def decode_relative(value: int) -> int:
    """Two's complement 7 bit: 1..63 is positive, 65..127 is negative, 0 and 64 are no change."""
    if value >= 64:
        value -= 128
    return value


def _color7(hex_color: str | None) -> tuple[int, int, int]:
    if hex_color is None:
        return (0, 0, 0)
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return tuple(round(c * 127 / 255) for c in (r, g, b))  # type: ignore[return-value]


class Mapping:
    def __init__(self, data: dict[str, Any]):
        try:
            self.channel: int = int(data["channel"])
            self.platter_cc: int = int(data["platter"]["cc"])
            self.knob_cc: dict[str, int] = {k: int(data["knobs"][k]) for k in KNOBS}
            self.fader_cc: dict[str, int] = {t: int(data["faders"][t]) for t in TRACKS}
            self.key_note: dict[str, int] = {k: int(data["keys"][k]) for k in KEYS}
            self.fader_default: float = float(data.get("fader_default", 0.8))
            sx = data["sysex"]
            self.sysex_prefix: list[int] = [int(b) for b in sx["prefix"]]
            self.sx_ring = int(sx["ring"])
            self.sx_key_light = int(sx["key_light"])
            self.sx_dump_request = int(sx["dump_request"])
            self.sx_version = int(sx["version"])
            self.key_modes: dict[str, int] = {m: int(sx["key_modes"][m]) for m in KEY_MODES}
        except (KeyError, TypeError, ValueError) as e:
            raise MappingError(f"bad mapping file: {e!r}") from e
        if not 1 <= self.channel <= 16:
            raise MappingError("channel must be 1-16")
        ccs = [self.platter_cc, *self.knob_cc.values(), *self.fader_cc.values()]
        if len(set(ccs)) != len(ccs):
            raise MappingError("CC numbers must be unique")
        notes = list(self.key_note.values())
        if len(set(notes)) != len(notes):
            raise MappingError("key note numbers must be unique")
        for n in (*ccs, *notes, *self.sysex_prefix):
            if not 0 <= n <= 127:
                raise MappingError(f"value out of 7-bit range: {n}")
        self._cc_to_event: dict[int, tuple[str, str | None]] = {self.platter_cc: ("platter", None)}
        self._cc_to_event.update({cc: ("knob", k) for k, cc in self.knob_cc.items()})
        self._cc_to_event.update({cc: ("fader", t) for t, cc in self.fader_cc.items()})
        self._note_to_key = {n: k for k, n in self.key_note.items()}

    # ---- loading -------------------------------------------------------------------------

    @classmethod
    def default(cls) -> "Mapping":
        text = (
            resources.files("fretcase_bridge")
            .joinpath("mapping.default.json")
            .read_text(encoding="utf-8")
        )
        return cls(json.loads(text))

    @classmethod
    def load(cls, path: Path | str | None) -> "Mapping":
        if path is None:
            return cls.default()
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- controller -> panel -------------------------------------------------------------

    def decode(self, msg: mido.Message) -> RawEvent | None:
        """Turn one MIDI message from the controller into a raw event, or None to ignore it."""
        if msg.type == "control_change" and msg.channel == self.channel - 1:
            kind = self._cc_to_event.get(msg.control)
            if kind is None:
                return None
            what, name = kind
            if what == "fader":
                return FaderValue(name, round(msg.value / 127, 4))  # type: ignore[arg-type]
            delta = decode_relative(msg.value)
            if delta == 0:
                return None
            if what == "platter":
                return PlatterTurn(delta)
            return KnobTurn(name, delta)  # type: ignore[arg-type]
        if msg.type in ("note_on", "note_off") and msg.channel == self.channel - 1:
            key = self._note_to_key.get(msg.note)
            if key is None:
                return None
            down = msg.type == "note_on" and msg.velocity > 0
            return KeyChange(key, "down" if down else "up")
        if msg.type == "sysex":
            data = list(msg.data)
            n = len(self.sysex_prefix)
            if data[:n] == self.sysex_prefix and len(data) >= n + 4 and data[n] == self.sx_version:
                return FirmwareVersion(".".join(str(b) for b in data[n + 1 : n + 4]))
        return None

    # ---- panel -> controller -------------------------------------------------------------

    def encode_ring(self, pixels: list[str | None], brightness: float = 0.6) -> mido.Message:
        if len(pixels) != RING_PIXELS:
            raise ValueError("ring needs 16 pixels")
        data = [*self.sysex_prefix, self.sx_ring, round(max(0.0, min(1.0, brightness)) * 127)]
        for p in pixels:
            data.extend(_color7(p))
        return mido.Message("sysex", data=data)

    def encode_key_light(self, key: str, mode: str, color: str | None = None) -> mido.Message:
        data = [
            *self.sysex_prefix,
            self.sx_key_light,
            self.key_note[key],
            self.key_modes[mode],
            0 if color is None else 1,
            *_color7(color),
        ]
        return mido.Message("sysex", data=data)

    def encode_dump_request(self) -> mido.Message:
        return mido.Message("sysex", data=[*self.sysex_prefix, self.sx_dump_request])
