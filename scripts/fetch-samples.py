#!/usr/bin/env python3
"""Download and prepare the instrument samples the app plays (app/public/samples/).

    python3 scripts/fetch-samples.py          # needs network access to raw.githubusercontent.com and ffmpeg

Every file is converted to a short mono MP3 (Safari cannot play Ogg) and listed in
app/public/samples/manifest.json, which the app reads to build one Tone.Sampler per catalogue instrument.

Sources (see app/public/samples/LICENSES.md):
- FluidR3_GM via gleitz/midi-js-soundfonts: Creative Commons Attribution 3.0.
- VCSL, the Versilian Community Sample Library, via danigb/samples: CC0 1.0.
The output is committed so that the case works with no network; run this again only to change the set.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "public" / "samples"
FLUID = "https://raw.githubusercontent.com/gleitz/midi-js-soundfonts/gh-pages/FluidR3_GM/{name}-mp3/{note}.mp3"
VCSL = "https://raw.githubusercontent.com/danigb/samples/main/audio/vcsl/{path}"
NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def note_name(midi: int) -> str:
    return f"{NAMES[midi % 12]}{midi // 12 - 1}"


def every_third(low: int, high: int) -> list[int]:
    """Notes a minor third apart from the first C at or below `low` up to `high` (C, Eb, Gb, A)."""
    start = low - (low % 3)
    return list(range(start, high + 1, 3))


# Pitched instruments: catalogue id -> (FluidR3 instrument, lowest MIDI note, highest MIDI note, seconds kept).
FLUID_SETS = {
    "synth-male": ("choir_aahs", 45, 81, 2.5),
    "synth-female": ("voice_oohs", 54, 87, 2.5),
    "piano": ("acoustic_grand_piano", 36, 96, 3.0),
    "whistle": ("whistle", 60, 96, 2.0),
    "flute": ("flute", 57, 96, 2.5),
    "steel": ("acoustic_guitar_steel", 39, 84, 2.5),
    "nylon": ("acoustic_guitar_nylon", 39, 84, 2.5),
    "electric-clean": ("electric_guitar_clean", 39, 84, 2.5),
    "finger-bass": ("electric_bass_finger", 27, 60, 2.0),
    "upright-bass": ("acoustic_bass", 27, 60, 2.0),
    "synth-bass": ("synth_bass_1", 27, 60, 1.5),
}
# Instruments that reuse another set's files (the app changes the envelope).
ALIASES = {"synth-soft": "synth-female", "ukulele": "nylon"}

# Harmonica from VCSL: real recordings named by note.
HARMONICA_DIR = "Free Aerophones/Harmonica-Hohner-Special20-C/Sustains/Normal"
HARMONICA_NOTES = ["C3", "E3", "C4", "E4", "G4", "C5", "E5", "G5", "C6"]

# Drum kits from VCSL: General MIDI key -> file under audio/vcsl/.
DRUM_KITS = {
    "jazz-kit": {
        36: "Struck Membranophones/Bass Drum 1/BDrumNew_hit_v5_rr1_Sum.m4a",
        38: "Struck Membranophones/Snare Drum, Modern 1/Snare2_HitNS_v4_rr1_Mid.m4a",
        42: "Struck Idiophones/Hi-Hat Cymbal/HiHat_HitC_v2_rr1_Mid.m4a",
        46: "Struck Idiophones/Hi-Hat Cymbal/HiHat_HitO_rr1_Mid.m4a",
        51: "Struck Idiophones/Suspended Cymbal 1/susCymb1_hit_mp1.m4a",
    },
    "pop-kit": {
        36: "Struck Membranophones/Bass Drum 1/BDrumNew_hit_v7_rr1_Sum.m4a",
        38: "Struck Membranophones/Snare Drum, Modern 2/Snare3M_HitSN_v5_rr1_Mid.m4a",
        42: "Struck Idiophones/Hi-Hat Cymbal/HiHat_HitC_v3_rr1_Mid.m4a",
        46: "Struck Idiophones/Hi-Hat Cymbal/HiHat_HitO_rr1_Mid.m4a",
        51: "Struck Idiophones/Suspended Cymbal 1/susCymb1_hit_f1.m4a",
    },
    "hand-drum": {
        36: "Struck Membranophones/Frame Drum/HDrumL_Hit_v3_rr1_Sum.m4a",
        38: "Struck Membranophones/Frame Drum/HDrumS_HitMuted_v3_rr1_Sum.m4a",
        42: "Struck Idiophones/Shaker, Small/Mid_ShakerDouble_Down_rr1.m4a",
        46: "Struck Idiophones/Shaker, Small/Mid_ShakerDouble_Up_rr1.m4a",
        51: "Struck Idiophones/Cajon/Cajon_hit2_mp_rr1.m4a",
    },
}


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "fretcase-fetch-samples"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def to_mp3(src: Path, dest: Path, seconds: float) -> None:
    """Mono, 44.1 kHz, trimmed to `seconds` with a short fade, leading silence removed, peak-normalised."""
    fade = min(0.4, seconds / 4)
    filters = f"silenceremove=start_periods=1:start_threshold=-50dB,atrim=0:{seconds},afade=t=out:st={seconds - fade}:d={fade},loudnorm=I=-16:TP=-1.5:LRA=11"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-af", filters, "-ac", "1", "-ar", "44100", "-b:a", "80k", str(dest)], check=True)


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ffmpeg is needed", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"pitched": {}, "drums": {}, "aliases": ALIASES}
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp)
        for inst, (name, low, high, secs) in FLUID_SETS.items():
            folder = OUT / inst
            folder.mkdir(exist_ok=True)
            files = {}
            for midi in every_third(low, high):
                n = note_name(midi)
                src = raw / f"{inst}-{n}.mp3"
                fetch(FLUID.format(name=name, note=n), src)
                to_mp3(src, folder / f"{n}.mp3", secs)
                files[n] = f"{inst}/{n}.mp3"
            manifest["pitched"][inst] = files
            print(f"{inst}: {len(files)} notes")
        folder = OUT / "harmonica"
        folder.mkdir(exist_ok=True)
        files = {}
        for n in HARMONICA_NOTES:
            src = raw / f"harmonica-{n}.m4a"
            fetch(VCSL.format(path=urllib.parse.quote(f"{HARMONICA_DIR}/Hohner-Special20_Normal_{n}.m4a")), src)
            to_mp3(src, folder / f"{n}.mp3", 2.5)
            files[n] = f"harmonica/{n}.mp3"
        manifest["pitched"]["harmonica"] = files
        print(f"harmonica: {len(files)} notes")
        for kit, keys in DRUM_KITS.items():
            folder = OUT / kit
            folder.mkdir(exist_ok=True)
            files = {}
            for key, path in keys.items():
                src = raw / f"{kit}-{key}.m4a"
                fetch(VCSL.format(path=urllib.parse.quote(path)), src)
                to_mp3(src, folder / f"{key}.mp3", 1.6 if key != 51 else 2.5)
                files[str(key)] = f"{kit}/{key}.mp3"
            manifest["drums"][kit] = files
            print(f"{kit}: {len(files)} hits")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.rglob("*.mp3"))
    print(f"wrote {OUT} ({total / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
