"""Request bodies for the HTTP API (docs/api.md). Responses are plain dictionaries validated against the song model."""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fretcase_engine.song_model import Section, SeedCard, SeedInput

TrackName = Literal["vocal", "melody", "guitar", "bass", "drums", "ambience"]
Unit = Annotated[float, Field(ge=0, le=1)]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetControl(_Op):
    op: Literal["setControl"]
    control: Literal["brightness", "complexity", "density"]
    value: Unit


class SetTempo(_Op):
    op: Literal["setTempo"]
    tempo: Annotated[float, Field(ge=40, le=220)]


class SetTrackVolume(_Op):
    op: Literal["setTrackVolume"]
    track: TrackName
    volume: Unit


class SetTrackMute(_Op):
    op: Literal["setTrackMute"]
    track: TrackName
    muted: bool


class SetInstrument(_Op):
    op: Literal["setInstrument"]
    track: TrackName
    instrument: str


class ReplaceNotes(_Op):
    op: Literal["replaceNotes"]
    track: TrackName
    from_: Annotated[int, Field(ge=0, alias="from")]
    to: Annotated[int, Field(ge=0)]
    notes: List[Dict[str, Any]]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SetLyrics(_Op):
    op: Literal["setLyrics"]
    section: str
    text: str


class SetRhythm(_Op):
    op: Literal["setRhythm"]
    family: Literal["strumming", "arpeggio"]
    presetId: str


class Lock(_Op):
    op: Literal["lock"]
    track: Optional[TrackName] = None
    section: Optional[str] = None

    @model_validator(mode="after")
    def _needs_a_target(self):
        # The schema's lock has minProperties: 1, so an empty one is a malformed request (400).
        if self.track is None and self.section is None:
            raise ValueError("lock needs a track, a section, or both")
        return self


class Unlock(_Op):
    op: Literal["unlock"]
    track: Optional[TrackName] = None
    section: Optional[str] = None

    @model_validator(mode="after")
    def _needs_a_target(self):
        # The schema's lock has minProperties: 1, so an empty one is a malformed request (400).
        if self.track is None and self.section is None:
            raise ValueError("unlock needs a track, a section, or both")
        return self


class SetSections(_Op):
    op: Literal["setSections"]
    sections: List[Section]


class SetTitle(_Op):
    op: Literal["setTitle"]
    title: Annotated[str, Field(max_length=80)]


class SetCard(_Op):
    op: Literal["setCard"]
    style: Optional[Literal["ink", "comic", "xieyi", "original", "text"]] = None
    line: Optional[Annotated[str, Field(max_length=60)]] = None
    message: Optional[Annotated[str, Field(max_length=500)]] = None
    photoAssetId: Optional[str] = None
    showPhoto: Optional[bool] = None
    city: Optional[Annotated[str, Field(max_length=60)]] = None
    showCity: Optional[bool] = None


class SetVocalTake(_Op):
    op: Literal["setVocalTake"]
    assetId: str


Op = Annotated[
    Union[SetControl, SetTempo, SetTrackVolume, SetTrackMute, SetInstrument, ReplaceNotes, SetLyrics, SetRhythm, Lock, Unlock, SetSections, SetTitle, SetCard, SetVocalTake],
    Field(discriminator="op"),
]


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseRevision: Annotated[int, Field(ge=0)]
    ops: Annotated[List[Op], Field(min_length=1)]


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseRevision: Annotated[int, Field(ge=0)]


class AnotherRequest(RevisionRequest):
    section: str
    track: Optional[TrackName] = None


class RehumRequest(RevisionRequest):
    section: str
    assetId: str


class CreateSongRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: SeedCard
    bars: Optional[Annotated[int, Field(ge=1, le=64)]] = None


class SeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: Annotated[List[SeedInput], Field(min_length=1)]


class LocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: Annotated[str, Field(min_length=1, max_length=60)]


class StudyEvent(BaseModel):
    at: str
    type: str
    detail: Any = None  # any JSON value; docs/api.md gives it no type


class StudyLogRequest(BaseModel):
    events: List[StudyEvent]
