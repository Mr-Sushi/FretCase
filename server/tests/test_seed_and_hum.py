"""Seed cards (offline analysis), hum transcription with Basic Pitch, re-hum, adapter timeouts."""
import time

import pytest

from conftest import Api, assert_valid, png_bytes, wav_bytes
from fretcase_engine.common import bar_ticks
from fretcase_server import hum
from fretcase_server.adapters import Adapters, Offline, OfflineStub, call_with_timeout

C_MAJOR_PHRASE = [261.63, 293.66, 329.63, 349.23, 392.0, 329.63, 293.66, 261.63]


def test_text_seed_card_has_reasons_and_is_offline(api):
    seed = api.seed([{"kind": "text", "text": "海边的傍晚，很平静"}])
    assert seed["source"] == "offline" and seed["mood"] == "平静偏暖"
    assert seed["key"]["mode"] == "major" and 40 <= seed["tempo"] <= 220
    assert {r["field"] for r in seed["reasons"]} >= {"mood", "tempo", "key", "meter"}
    assert "motif" not in seed
    sad = api.seed([{"kind": "text", "text": "rain tonight, I miss you"}])
    assert sad["key"]["mode"] == "minor" and sad["tempo"] < seed["tempo"]


def test_photo_seed_card_uses_colour_statistics(api):
    warm = api.upload(png_bytes((230, 150, 60), (64, 64)), "photo", "w.png", "image/png")
    dark = api.upload(png_bytes((20, 30, 70), (64, 64)), "photo", "d.png", "image/png")
    bright_seed = api.seed([{"kind": "photo", "assetId": warm["id"]}])
    dark_seed = api.seed([{"kind": "photo", "assetId": dark["id"]}])
    assert bright_seed["key"]["mode"] == "major" and dark_seed["key"]["mode"] == "minor"
    assert bright_seed["instruments"]["guitar"] == "nylon" and dark_seed["instruments"]["guitar"] == "steel"
    assert any("照片" in r["text"] for r in bright_seed["reasons"])


def test_sound_seed_card_finds_a_beat(api):
    clicks = [i * 0.5 for i in range(12)]  # 120 beats per minute
    sound = api.upload(wav_bytes(clicks=clicks, seconds=6.2, rate=11025), "ambience", "c.wav", "audio/wav")
    seed = api.seed([{"kind": "sound", "assetId": sound["id"]}])
    assert 110 <= seed["tempo"] <= 120  # the offline tempo is clamped to 60-120
    assert seed["instruments"] == {"ambience": "recording"}


def test_seed_input_validation(api):
    c = api.c
    assert c.post("/api/seed", json={"inputs": []}).status_code == 400
    assert c.post("/api/seed", json={"inputs": [{"kind": "text"}]}).status_code == 400
    assert c.post("/api/seed", json={"inputs": [{"kind": "hum"}]}).status_code == 400
    assert c.post("/api/seed", json={"inputs": [{"kind": "hum", "assetId": "a-nothing-here"}]}).status_code == 404
    photo = api.upload(png_bytes(), "photo", "p.png", "image/png")
    r = c.post("/api/seed", json={"inputs": [{"kind": "hum", "assetId": photo["id"]}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_real_basic_pitch_transcribes_a_hummed_phrase(api):
    pytest.importorskip("basic_pitch")
    audio = api.upload(wav_bytes(C_MAJOR_PHRASE, seconds=4.0), "hum", "h.wav", "audio/wav")
    seed = api.seed([{"kind": "hum", "assetId": audio["id"]}])
    motif = seed["motif"]
    assert motif[0]["start"] == 0 and len(motif) >= 5
    assert [n["pitch"] for n in motif][:3] == [60, 62, 64]
    assert all(n["start"] % 240 == 0 and n["duration"] % 240 == 0 for n in motif)
    assert seed["key"] == {"tonic": "C", "mode": "major"}
    assert any(r["field"] == "motif" for r in seed["reasons"])
    song = api.song(seed=seed)
    assert song["tracks"]["melody"]["notes"][0]["pitch"] == 60
    assert song["seed"]["motif"] == motif


def test_seed_without_a_transcriber_has_no_motif_but_still_works(make_client):
    api = Api(make_client(hum_transcriber=lambda path, tempo: None))
    audio = api.upload(wav_bytes([440.0]), "hum", "h.wav", "audio/wav")
    seed = api.seed([{"kind": "hum", "assetId": audio["id"]}, {"kind": "text", "text": "quiet night"}])
    assert "motif" not in seed
    assert any(r["field"] == "motif" and "无法转写" in r["text"] for r in seed["reasons"])
    assert_valid(api.song(seed=seed))


def test_rehum_with_a_fake_transcriber_and_without_one(make_client):
    notes = [{"start": 0, "duration": 480, "pitch": 62}, {"start": 480, "duration": 480, "pitch": 64}, {"start": 960, "duration": 960, "pitch": 66}]
    api = Api(make_client(hum_transcriber=lambda path, tempo: {"motif": notes, "tempo": tempo, "key": None, "tempoFromHum": False, "noteCount": 3}))
    audio = api.upload(wav_bytes([440.0]), "hum", "h.wav", "audio/wav")
    song = api.song(key={"tonic": "D", "mode": "major"})
    out = api.post(song, "rehum", section="s-verse", assetId=audio["id"])
    bt = bar_ticks(out["meter"])
    verse = [n for n in out["tracks"]["melody"]["notes"] if 4 * bt <= n["start"] < 8 * bt]
    assert verse and verse != [n for n in song["tracks"]["melody"]["notes"] if 4 * bt <= n["start"] < 8 * bt]
    assert any(a["id"] == audio["id"] for a in out["assets"])
    locked = api.edit(out, {"op": "lock", "track": "melody", "section": "s-verse"})
    assert api.post(locked, "rehum", expect=422, section="s-verse", assetId=audio["id"])["code"] == "cannot_apply"
    photo = api.upload(png_bytes(), "photo", "p.png", "image/png")
    assert api.post(locked, "rehum", expect=422, section="s-intro", assetId=photo["id"])["code"] == "cannot_apply"

    none_api = Api(make_client(hum_transcriber=lambda path, tempo: None))
    a2 = none_api.upload(wav_bytes([440.0]), "hum", "h.wav", "audio/wav")
    s2 = none_api.song()
    assert none_api.post(s2, "rehum", expect=422, section="s-verse", assetId=a2["id"])["detail"]["reason"] == "no_transcriber"


def test_quantise_and_key_detection_helpers():
    line = [(0.0, 0.5, 60), (0.5, 1.0, 62), (1.0, 2.0, 64)]
    motif = hum.quantise(line, 120)
    assert [(n["start"], n["duration"]) for n in motif] == [(0, 480), (480, 480), (960, 960)]
    key, r = hum.detect_key([(60, 1), (62, 1), (64, 1), (65, 1), (67, 2), (69, 1), (71, 1), (60, 2)])
    assert key == {"tonic": "C", "mode": "major"} and r > 0.5
    assert hum.estimate_tempo([i * 0.5 for i in range(10)]) in (60.0, 120.0)
    assert hum.monophonic([(0, 1, 60, 0.9), (0.2, 0.9, 64, 0.2), (1, 2, 62, 0.9)]) == [(0, 1, 60), (1, 2, 62)]


# ----------------------------------------------------------------------------------------------- adapters


def test_adapter_calls_time_out_and_fall_back():
    started = time.monotonic()
    result = call_with_timeout(lambda: time.sleep(2) or "late", timeout=0.1, fallback="offline")
    assert result == "offline" and time.monotonic() - started < 1.0
    assert call_with_timeout(lambda: "fast", timeout=1.0, fallback="offline") == "fast"

    def broken():
        raise RuntimeError("provider down")

    assert call_with_timeout(broken, timeout=1.0, fallback="offline") == "offline"
    with pytest.raises(Offline):
        call_with_timeout(OfflineStub().render, {})


def test_a_slow_or_failing_seed_model_falls_back_to_the_offline_card(make_client):
    class SlowModel:
        def analyse(self, inputs, assets):
            time.sleep(2)
            return {"never": "used"}

    class BrokenModel:
        def analyse(self, inputs, assets):
            raise ConnectionError("no network")

    for model in (SlowModel(), BrokenModel()):
        api = Api(make_client(adapters=Adapters(seed_model=model, timeout_s=0.2)))
        seed = api.seed([{"kind": "text", "text": "calm sea"}])
        assert seed["source"] == "offline"


def test_a_model_seed_card_is_marked_as_model(make_client):
    class Model:
        def analyse(self, inputs, assets):
            return {"inputs": inputs, "key": {"tonic": "D", "mode": "major"}, "tempo": 100, "mood": "x", "reasons": []}

    api = Api(make_client(adapters=Adapters(seed_model=Model(), timeout_s=1.0)))
    assert api.seed([{"kind": "text", "text": "hello"}])["source"] == "model"
