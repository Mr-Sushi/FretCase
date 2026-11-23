import io
import json
import math
import struct
import sys
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).parent / "stubs"))  # the fretcase_card stub

import fretcase_card as card_stub  # noqa: E402
from fretcase_server.app import create_app  # noqa: E402
from fretcase_server.config import Settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SONG_SCHEMA = json.loads((ROOT / "shared" / "schema" / "song.schema.json").read_text(encoding="utf-8"))
SONG_VALIDATOR = Draft202012Validator(SONG_SCHEMA, format_checker=FormatChecker())


def assert_valid(song):
    errors = [f"{list(e.absolute_path)}: {e.message}" for e in SONG_VALIDATOR.iter_errors(song)]
    assert errors == []


def wav_bytes(frequencies=(440.0,), seconds=1.0, rate=22050, clicks=None):
    """A mono WAV: consecutive sine notes, or a click track when ``clicks`` is a list of times."""
    n = int(rate * seconds)
    samples = [0.0] * n
    if clicks is not None:
        for t in clicks:
            start = int(t * rate)
            for i in range(min(400, n - start)):
                samples[start + i] += 0.9 * math.exp(-i / 60.0) * math.sin(i * 0.9)
    else:
        per = n // len(frequencies)
        for k, f in enumerate(frequencies):
            for i in range(per):
                samples[k * per + i] = 0.5 * math.sin(2 * math.pi * f * i / rate)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
    return out.getvalue()


def png_bytes(color=(200, 120, 60), size=(64, 48)):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def card_module():
    card_stub.Printer.instances = []
    card_stub.Printer.fail_with = None
    return card_stub


@pytest.fixture
def make_client(tmp_path, card_module):
    def make(**kwargs):
        kwargs.setdefault("card_module_loader", lambda: card_module)
        settings = Settings(data_dir=tmp_path / "data", share_base_url="https://fretcase.example")
        app = create_app(settings, **kwargs)
        return TestClient(app)

    return make


@pytest.fixture
def client(make_client):
    return make_client()


class Api:
    """Small helpers over the test client."""

    def __init__(self, client):
        self.c = client

    def upload(self, data, role, name="x.bin", mime="application/octet-stream"):
        r = self.c.post("/api/assets", files={"file": (name, data, mime)}, data={"role": role})
        assert r.status_code == 200, r.text
        return r.json()["asset"]

    def seed(self, inputs):
        r = self.c.post("/api/seed", json={"inputs": inputs})
        assert r.status_code == 200, r.text
        return r.json()["seed"]

    def song(self, text="Seaside at dusk, calm", key=None, bars=None, seed=None):
        seed = seed or self.seed([{"kind": "text", "text": text}])
        if key:
            seed["key"] = key
        body = {"seed": seed}
        if bars:
            body["bars"] = bars
        r = self.c.post("/api/songs", json=body)
        assert r.status_code == 201, r.text
        song = r.json()["song"]
        assert_valid(song)
        return song

    def edit(self, song, *ops, expect=200):
        r = self.c.post(f"/api/songs/{song['id']}/edits", json={"baseRevision": song["revision"], "ops": list(ops)})
        assert r.status_code == expect, r.text
        if expect == 200:
            assert_valid(r.json()["song"])
            return r.json()["song"]
        return r.json()["error"]

    def post(self, song, path, expect=200, **body):
        r = self.c.post(f"/api/songs/{song['id']}/{path}", json={"baseRevision": song["revision"], **body})
        assert r.status_code == expect, r.text
        if expect == 200:
            assert_valid(r.json()["song"])
            return r.json()["song"]
        return r.json()["error"]


@pytest.fixture
def api(client):
    return Api(client)
