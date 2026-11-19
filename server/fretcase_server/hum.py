"""Hum transcription: Basic Pitch (ONNX) behind a small interface, with quantisation to ticks.

If Basic Pitch or ffmpeg is missing, ``transcribe`` returns ``None`` and the caller makes a seed card without a motif.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)
TPQ = 480
GRID = TPQ // 2  # eighth notes
MAX_MOTIF_BARS = 4


def decode_to_wav(path: Path, sample_rate: int = 22050) -> Optional[Path]:
    """Decode any audio file ffmpeg understands to a mono WAV in a temporary file."""
    try:
        out = Path(tempfile.mkstemp(suffix=".wav")[1])
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(sample_rate), str(out)],
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0 or out.stat().st_size < 100:
            out.unlink(missing_ok=True)
            return None
        return out
    except (OSError, subprocess.SubprocessError):
        return None


def load_samples(path: Path, sample_rate: int = 22050) -> Optional[np.ndarray]:
    wav = decode_to_wav(path, sample_rate)
    if wav is None:
        return None
    try:
        import wave

        with wave.open(str(wav), "rb") as w:
            raw = w.readframes(w.getnframes())
            width = w.getsampwidth()
        if width != 2:
            return None
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    finally:
        wav.unlink(missing_ok=True)


def basic_pitch_notes(path: Path) -> Optional[List[Tuple[float, float, int, float]]]:
    """(start s, end s, midi pitch, amplitude) from Basic Pitch, or None if it cannot run here."""
    try:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        from basic_pitch.inference import predict  # noqa: WPS433
    except Exception as exc:  # not installed
        log.info("Basic Pitch unavailable: %s", exc)
        return None
    wav = decode_to_wav(path)
    source = wav or path
    try:
        _, _, events = predict(str(source), onset_threshold=0.5, frame_threshold=0.3, minimum_note_length=80)
    except Exception as exc:
        log.info("Basic Pitch failed: %s", exc)
        return None
    finally:
        if wav:
            wav.unlink(missing_ok=True)
    return [(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in events]


def monophonic(events: List[Tuple[float, float, int, float]]) -> List[Tuple[float, float, int]]:
    """A hummed line has one note at a time: keep the strongest note where several overlap."""
    kept: List[Tuple[float, float, int, float]] = []
    for ev in sorted(events, key=lambda e: (e[0], -e[3])):
        if kept and ev[0] < kept[-1][1] - 0.03:
            if ev[3] > kept[-1][3] * 1.3 and ev[0] - kept[-1][0] > 0.08:
                kept[-1] = (kept[-1][0], ev[0], kept[-1][2], kept[-1][3])
                kept.append(ev)
            continue
        kept.append(ev)
    return [(s, e, p) for s, e, p, _ in kept if e - s >= 0.06]


def estimate_tempo(onsets: List[float], lo: float = 60.0, hi: float = 120.0) -> Optional[float]:
    """Tempo from inter-onset intervals: the most supported beat length in [lo, hi] BPM, else None."""
    if len(onsets) < 4:
        return None
    iois = np.diff(sorted(onsets))
    iois = iois[(iois > 0.12) & (iois < 2.0)]
    if len(iois) < 3:
        return None
    best, best_score = None, 0.0
    for bpm in np.arange(lo, hi + 1, 1.0):
        beat = 60.0 / bpm
        score = 0.0
        for ioi in iois:
            ratio = ioi / (beat / 2)  # eighth-note grid
            score += max(0.0, 1.0 - abs(ratio - round(ratio)) * 2) if round(ratio) >= 1 else 0.0
        if score > best_score:
            best, best_score = float(bpm), score
    return best


def quantise(notes: List[Tuple[float, float, int]], tempo: float) -> List[Dict[str, Any]]:
    """Notes in seconds to ticks on an eighth-note grid, first note at tick 0, at most MAX_MOTIF_BARS bars of 4/4."""
    if not notes:
        return []
    t0 = notes[0][0]
    per_sec = tempo / 60.0 * TPQ
    out: List[Dict[str, Any]] = []
    limit = MAX_MOTIF_BARS * 4 * TPQ
    for start, end, pitch in notes:
        a = round((start - t0) * per_sec / GRID) * GRID
        b = max(a + GRID, round((end - t0) * per_sec / GRID) * GRID)
        if a >= limit:
            break
        if out and a < out[-1]["start"] + out[-1]["duration"]:
            out[-1]["duration"] = max(GRID, a - out[-1]["start"])
            if a <= out[-1]["start"]:
                out.pop()
        out.append({"start": int(a), "duration": int(min(b - a, limit - a)), "pitch": int(pitch), "velocity": 90})
    return out


def detect_key(pitches: List[Tuple[int, float]]) -> Tuple[Dict[str, str], float]:
    """Krumhansl-Schmuckler key estimate from (pitch, duration) pairs. Returns (key, correlation)."""
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    hist = np.zeros(12)
    for p, d in pitches:
        hist[p % 12] += d
    if hist.sum() == 0:
        return {"tonic": "C", "mode": "major"}, 0.0
    best = (-2.0, 0, "major")
    for pc in range(12):
        for mode, prof in (("major", major), ("minor", minor)):
            r = float(np.corrcoef(hist, np.roll(prof, pc))[0, 1])
            if r > best[0]:
                best = (r, pc, mode)
    r, pc, mode = best
    major_names = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    minor_names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
    return {"tonic": (major_names if mode == "major" else minor_names)[pc], "mode": mode}, r


def transcribe(path: Path, fixed_tempo: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """{"motif", "tempo", "key", "tempoFromHum", "noteCount"} or None when transcription is not possible here."""
    events = basic_pitch_notes(path)
    if events is None:
        return None
    line = monophonic(events)
    if not line:
        return {"motif": [], "tempo": fixed_tempo, "key": None, "tempoFromHum": False, "noteCount": 0}
    estimated = estimate_tempo([s for s, _, _ in line])
    tempo = fixed_tempo or estimated or 90.0
    motif = quantise(line, tempo)
    key, _ = detect_key([(p, e - s) for s, e, p in line])
    return {"motif": motif, "tempo": tempo, "key": key, "tempoFromHum": fixed_tempo is None and estimated is not None, "noteCount": len(motif)}
