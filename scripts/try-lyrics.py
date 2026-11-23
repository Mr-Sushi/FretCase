"""Try lyric writing with a real text model, through the real HTTP API, in a throwaway data folder.

    uv run python scripts/try-lyrics.py "Seaside at dusk, very windy, a little homesick"

Needs FRETCASE_TEXT_MODEL_KEY, in the environment or in the gitignored .env at the repository root
(FRETCASE_TEXT_MODEL_API, FRETCASE_TEXT_MODEL_NAME and FRETCASE_TEXT_MODEL_URL are optional; an OpenAI key works too).
First makes one direct call to show which model answers, or the service's own error. Then prints the lines it gets,
their lengths against the notes, how long each call took, and three other wordings for one chorus line.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from fretcase_server.config import load_env_file

load_env_file()

from fastapi.testclient import TestClient  # noqa: E402

from fretcase_engine import editing  # noqa: E402
from fretcase_server.app import create_app  # noqa: E402
from fretcase_server.config import Settings  # noqa: E402


def lines_of(song: dict) -> list[tuple[str, list[str], list[int]]]:
    out = []
    for section in song["sections"]:
        lines = editing.lyric_lines(editing.vocal_notes_in(song, section))
        if lines:
            out.append((section["label"], ["".join(n.get("lyric") or "" for n in l) for l in lines], [len(l) for l in lines]))
    return out


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else "Seaside at dusk, very windy, a little homesick"
    with tempfile.TemporaryDirectory() as data:
        settings = Settings(data_dir=Path(data))
        if not settings.text_model_key:
            print("No FRETCASE_TEXT_MODEL_KEY in the environment or in .env; nothing to try.")
            return 2
        from fretcase_server.adapters import ModelError, make_text_model

        model = make_text_model(settings.text_model_api, settings.text_model_url, settings.text_model_key, settings.text_model_name)
        print(f"model: {type(model).__name__} {model.name} at {model.endpoint()}")
        started = time.monotonic()
        try:
            said = model.complete("Answer in one word.", "Say OK.", max_tokens=20, timeout=30.0)
            print(f"direct call answered in {time.monotonic() - started:.1f} s: {said.strip()[:40]!r}")
        except ModelError as exc:
            print(f"direct call failed ({exc.reason}): {exc}")
            return 1
        client = TestClient(create_app(settings))
        health = client.get("/health").json()
        print(f"model configured: {health['lyrics']}, online: {health['online']}")
        seed = client.post("/api/seed", json={"inputs": [{"kind": "text", "text": text}]}).json()["seed"]
        drafts = client.post("/api/candidates", json={"seed": seed, "timeOfDay": "dusk"}).json()["candidates"]
        song = client.post(f"/api/songs/{drafts[0]['id']}/choose", json={}).json()["song"]
        print(f"song: {song['title']} ({song['candidate']['name']})\n")

        themes = [t["text"] for t in client.get(f"/api/songs/{song['id']}/lyrics/themes").json()["themes"]][:4]
        print("themes:", ", ".join(themes))
        started = time.monotonic()
        r = client.post(f"/api/songs/{song['id']}/lyrics", json={"baseRevision": song["revision"], "themes": themes, "tone": "plain", "rhyme": True})
        took = time.monotonic() - started
        if r.status_code != 200:
            print(f"rewrite failed after {took:.1f} s: {r.status_code} {r.json()['error']}")
            return 1
        song = r.json()["song"]
        print(f"rewrite took {took:.1f} s\n")
        for label, texts, counts in lines_of(song):
            print(f"[{label}]")
            for t, c in zip(texts, counts):
                n = sum(len(line) for line in editing.split_syllables(t))
                print(f"  {t}   ({n} syllables / {c} notes{'' if n == c else '  MISMATCH'})")

        chorus = next((s for s in song["sections"] if s["label"] == "Chorus"), song["sections"][1])
        started = time.monotonic()
        r = client.post(f"/api/songs/{song['id']}/lyrics/alternatives", json={"section": chorus["id"], "line": 0, "themes": themes})
        took = time.monotonic() - started
        print(f"\nother wordings for the first {chorus['label']} line ({took:.1f} s):")
        if r.status_code != 200:
            print(f"  failed: {r.status_code} {r.json()['error']}")
            return 1
        for alt in r.json()["alternatives"]:
            print(f"  {alt['text']}   {alt.get('note', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
