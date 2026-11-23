"""The studio version: the whole song sung and played by a music model (``POST /api/songs/{id}/render``).

The editable song stays the source of truth. A render is a recording made from it at one revision: this module
turns the song into a prompt for the model (lyrics by section, timestamps, tempo, key, who plays, the voice) and
picks the cover photo to send with it. Renders run as jobs because the model takes a minute or more.
"""
from __future__ import annotations

import io
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from fretcase_engine import catalog
from fretcase_server import lyrics

VOICE = {
    "synth-male": "a warm male lead vocal",
    "synth-female": "a gentle female lead vocal",
    "synth-soft": "a soft, breathy lead vocal",
}
TRACK_ORDER = ["vocal", "melody", "guitar", "bass", "drums", "ambience"]


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def bar_seconds(song: Dict[str, Any]) -> float:
    meter = song["meter"]
    return meter["numerator"] * (4 / meter["denominator"]) * 60.0 / float(song["tempo"])


def lyrics_snapshot(song: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The lyric lines of every section, as the song page shows them."""
    out = []
    for section in song["sections"]:
        lines = [lyrics.line_text(l) for l in lyrics.lyric_lines(song, section)]
        lines = [t for t in lines if t and set(t.replace(" ", "").lower()) != {"l", "a"}]  # an unwritten "la la la" line is not a lyric
        if lines:
            out.append({"section": section["label"], "lines": lines})
    return out


def _playing(song: Dict[str, Any], section_id: str) -> List[str]:
    names = []
    for track in TRACK_ORDER:
        tr = song["tracks"][track]
        region = next((r for r in tr.get("regions", []) if r["section"] == section_id), None)
        if not region or not region.get("play", True) or tr.get("muted"):
            continue
        if track == "vocal":
            names.append("lead vocal")
        elif track == "ambience":
            names.append("the recorded background sound")
        else:
            label = catalog.instrument_label(track, tr["instrument"]).lower()
            style = region.get("style")
            names.append(f"{label} ({catalog.style_label(track, style).lower()})" if style and track in ("guitar", "bass", "drums") else label)
    return names


def build_prompt(song: Dict[str, Any]) -> str:
    """A prompt that asks for this song: same structure and timing, these exact lyrics, these instruments."""
    per_bar = bar_seconds(song)
    total = song["bars"] * per_bar
    key = song["key"]
    meter = song["meter"]
    mood = ((song.get("seed") or {}).get("mood") or "").strip()
    cand = song.get("candidate") or {}
    feel = ", ".join(t for t in (cand.get("tags") or []) if t)
    voice = VOICE.get(song["tracks"]["vocal"]["instrument"], "a gentle lead vocal")
    words = lyrics_snapshot(song)
    lines = [
        f"Create a {round(total)}-second acoustic singer-songwriter song titled \"{song['title']}\".",
        f"Tempo {song['tempo']} BPM, {meter['numerator']}/{meter['denominator']} time, key of {key['tonic']} {key['mode']}." + (f" Mood: {mood}." if mood else "") + (f" Feel: {feel}." if feel else ""),
        f"Sung by {voice}, clear and intelligible, in English.",
        "",
        "Structure (follow these timestamps):",
    ]
    for section in song["sections"]:
        start, end = section["startBar"] * per_bar, section["endBar"] * per_bar
        who = _playing(song, section["id"])
        lead = section.get("lead")
        lead_txt = f" The {catalog.instrument_label(lead, song['tracks'][lead]['instrument']).lower() if lead != 'vocal' else 'voice'} leads." if lead else ""
        lines.append(f"[{_clock(start)} - {_clock(end)}] {section['label']}: " + (", ".join(who) if who else "silence") + "." + lead_txt)
    lines += ["", "Lyrics (sing exactly these words, one line per phrase, and nothing else):", ""]
    sung = {w["section"]: w["lines"] for w in words}
    for section in song["sections"]:
        lines.append(f"[{section['label']}]")
        lines += sung.get(section["label"], ["(instrumental)"])
        lines.append("")
    lines.append("Keep it short and simple, without a long intro or fade, and end when the last section ends.")
    return "\n".join(lines).strip() + "\n"


def cover_image(song: Dict[str, Any], read: Callable[[str], Tuple[bytes, str]]) -> List[Tuple[str, bytes]]:
    """The card's cover photo (or the first photo), scaled to at most 1024 px, as (mime, bytes); empty when there is none."""
    card = song.get("card") or {}
    asset_id = card.get("coverAssetId") or next(iter(card.get("photoAssetIds") or []), None)
    if not asset_id:
        asset_id = next((a["id"] for a in song.get("assets", []) if a.get("role") == "photo"), None)
    if not asset_id:
        return []
    try:
        data, mime = read(asset_id)
    except Exception:  # noqa: BLE001 (a missing photo only makes the prompt plainer)
        return []
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((1024, 1024))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=85)
            return [("image/jpeg", out.getvalue())]
    except Exception:  # noqa: BLE001 (not an image Pillow can read: send it as it is if it is small)
        return [(mime, data)] if len(data) < 4_000_000 and mime.startswith("image/") else []


class Jobs:
    """Background jobs with the shape of ``GET /api/jobs/{id}``. Kept in memory: a restart forgets running jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, key: str, work: Callable[[], Dict[str, Any]], on_error: Callable[[BaseException], Dict[str, Any]]) -> Dict[str, Any]:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = {"id": job_id, "kind": kind, "key": key, "state": "running"}
        with self._lock:
            self._jobs[job_id] = job

        def run() -> None:
            try:
                result = work()
                update = {"state": "done", "result": result}
            except BaseException as exc:  # noqa: BLE001 (the job reports every failure)
                update = {"state": "failed", "error": on_error(exc)}
            with self._lock:
                self._jobs[job_id] = {**self._jobs[job_id], **update}

        threading.Thread(target=run, name=job_id, daemon=True).start()
        return dict(job)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def running(self, kind: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((dict(j) for j in self._jobs.values() if j["state"] == "running" and j.get("kind") == kind and j.get("key") == key), None)
