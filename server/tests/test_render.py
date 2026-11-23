"""The studio version: whole-song rendering by a music model, as a job (POST /api/songs/{id}/render)."""
import base64
import time

import pytest

from conftest import Api, assert_valid, png_bytes, wav_bytes
from fretcase_server import adapters as adapters_mod
from fretcase_server import render as studio
from fretcase_server.adapters import Adapters, LyriaRenderer, ModelError, RenderResult, parse_lyria_answer


class FakeRenderer:
    configured = True
    name = "fake-lyria"

    def __init__(self, fail=None, delay=0.0):
        self.calls = []
        self.fail = fail
        self.delay = delay

    def render(self, prompt, images=(), timeout=240.0):
        self.calls.append({"prompt": prompt, "images": list(images), "timeout": timeout})
        time.sleep(self.delay)
        if self.fail:
            raise ModelError(self.fail, "nope")
        return RenderResult(audio=wav_bytes(seconds=2.0), mime="audio/wav", text="[Verse] ...")


def wait(api, job, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = api.c.get(f"/api/jobs/{job['id']}")
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


def lyric_song(api):
    song = api.song()
    sec = next(s for s in song["sections"] if s["label"] == "Verse")
    n = sum(1 for x in song["tracks"]["vocal"]["notes"] if sec["startBar"] * 1920 <= x["start"] < sec["endBar"] * 1920)
    words = " ".join(["sing"] * n)
    return api.edit(song, {"op": "setLyrics", "section": sec["id"], "text": words})


def test_render_runs_as_a_job_and_stores_a_current_studio_version(make_client):
    model = FakeRenderer()
    api = Api(make_client(adapters=Adapters(renderer=model)))
    song = lyric_song(api)
    r = api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]})
    assert r.status_code == 202, r.text
    job = wait(api, r.json()["job"])
    assert job["state"] == "done", job
    out = job["result"]["song"]
    assert_valid(out)
    render = out["render"]
    assert render["model"] == "fake-lyria"
    assert render["basedOnRevision"] == song["revision"]
    assert render["revision"] == out["revision"] == song["revision"] + 1
    assert render["durationSec"] == pytest.approx(2.0, abs=0.05)
    assert any(w["section"] == "Verse" and w["lines"] for w in render["lyrics"])
    asset = next(a for a in out["assets"] if a["id"] == render["assetId"])
    assert asset["role"] == "song_render" and asset["mime"] == "audio/wav"
    assert api.c.get(f"/api/assets/{render['assetId']}").status_code == 200
    prompt = model.calls[0]["prompt"]
    assert "sing sing sing" in prompt and "[Verse]" in prompt and f"{out['tempo']} BPM" in prompt
    assert "[0:00 - " in prompt  # timestamps for the structure


def test_rendering_again_replaces_the_old_recording(make_client):
    api = Api(make_client(adapters=Adapters(renderer=FakeRenderer())))
    song = lyric_song(api)
    first = wait(api, api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"])["result"]["song"]
    second = wait(api, api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": first["revision"]}).json()["job"])["result"]["song"]
    renders = [a for a in second["assets"] if a["role"] == "song_render"]
    assert len(renders) == 1 and renders[0]["id"] == second["render"]["assetId"] != first["render"]["assetId"]


def test_a_photo_is_sent_with_the_prompt(make_client):
    model = FakeRenderer()
    api = Api(make_client(adapters=Adapters(renderer=model)))
    photo = api.upload(png_bytes(size=(2000, 1500)), "photo", "p.png", "image/png")
    seed = api.seed([{"kind": "photo", "assetId": photo["id"]}, {"kind": "text", "text": "Seaside at dusk"}])
    song = api.song(seed=seed)
    wait(api, api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"])
    images = model.calls[0]["images"]
    assert len(images) == 1 and images[0][0] == "image/jpeg"
    from PIL import Image
    import io
    assert max(Image.open(io.BytesIO(images[0][1])).size) == 1024


def test_without_a_music_model_the_render_is_unavailable_at_once(client):
    api = Api(client)
    song = api.song()
    r = api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "offline_unavailable" and err["detail"]["reason"] == "not_configured"
    assert client.get("/health").json()["render"] is False


def test_a_failed_model_call_fails_the_job_with_the_reason_and_leaves_the_song(make_client):
    api = Api(make_client(adapters=Adapters(renderer=FakeRenderer(fail="auth"))))
    song = api.song()
    job = wait(api, api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"])
    assert job["state"] == "failed"
    assert job["error"]["code"] == "offline_unavailable" and job["error"]["detail"]["reason"] == "auth"
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"]["revision"] == song["revision"]


def test_a_stale_revision_is_refused_and_a_second_request_joins_the_running_job(make_client):
    api = Api(make_client(adapters=Adapters(renderer=FakeRenderer(delay=0.3))))
    song = api.song()
    assert api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"] + 5}).status_code == 409
    a = api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"]
    b = api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"]
    assert a["id"] == b["id"]
    wait(api, a)


def test_an_edit_during_rendering_marks_the_render_as_older_than_the_song(make_client):
    api = Api(make_client(adapters=Adapters(renderer=FakeRenderer(delay=0.3))))
    song = api.song()
    job = api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"]
    edited = api.edit(song, {"op": "setTempo", "tempo": song["tempo"] + 4})
    out = wait(api, job)["result"]["song"]
    assert out["tempo"] == edited["tempo"]  # the edit is kept
    assert out["render"]["basedOnRevision"] == song["revision"]
    assert out["render"]["basedOnRevision"] != out["render"]["revision"] - 1  # so the app knows it is older


def test_the_song_page_plays_the_studio_version_with_the_lyrics_it_sang(make_client):
    api = Api(make_client(adapters=Adapters(renderer=FakeRenderer())))
    song = lyric_song(api)
    out = wait(api, api.c.post(f"/api/songs/{song['id']}/render", json={"baseRevision": song["revision"]}).json()["job"])["result"]["song"]
    r = api.c.post(f"/api/songs/{out['id']}/card/preview", json={"baseRevision": out["revision"]})
    assert r.status_code == 200, r.text
    share = r.json()["song"]["card"]["share"]["shareId"]
    page = api.c.get(f"/api/share/{share}/page").json()
    assert page["page"]["render"]["audio"].endswith(out["render"]["assetId"])
    assert page["page"]["render"]["lyrics"] == out["render"]["lyrics"]
    assert api.c.get(page["page"]["render"]["audio"]).status_code == 200


def test_unknown_jobs_are_not_found(client):
    assert client.get("/api/jobs/job-nope").status_code == 404


def test_the_prompt_leaves_unwritten_la_lines_out_and_marks_instrumental_sections():
    song = {
        "title": "Test", "tempo": 120, "bars": 4, "key": {"tonic": "C", "mode": "major"}, "meter": {"numerator": 4, "denominator": 4},
        "sections": [{"id": "a", "label": "Intro", "startBar": 0, "endBar": 2}, {"id": "b", "label": "Verse", "startBar": 2, "endBar": 4}],
        "tracks": {t: {"instrument": i, "muted": False, "regions": [{"section": "a", "play": t != "vocal"}, {"section": "b", "play": True}], "notes": []}
                   for t, i in [("vocal", "synth-male"), ("melody", "piano"), ("guitar", "steel"), ("bass", "finger-bass"), ("drums", "jazz-kit"), ("ambience", "recording")]},
    }
    song["tracks"]["vocal"]["notes"] = [{"start": 2 * 1920 + i * 480, "duration": 480, "pitch": 60, "lyric": "la", **({"lineEnd": True} if i == 3 else {})} for i in range(4)]
    song["tracks"]["ambience"]["clips"] = []
    prompt = studio.build_prompt(song)
    assert "[0:00 - 0:04] Intro:" in prompt and "[0:04 - 0:08] Verse:" in prompt
    assert "a warm male lead vocal" in prompt
    assert "(instrumental)" in prompt and "la la la" not in prompt.lower()
    assert studio.lyrics_snapshot(song) == []


def test_lyria_answers_are_read_in_either_part_order_and_key_spelling():
    audio = base64.b64encode(b"ID3fake").decode()
    r = parse_lyria_answer({"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/mpeg", "data": audio}}, {"text": "[Verse]"}]}}]})
    assert r.audio == b"ID3fake" and r.mime == "audio/mpeg" and r.text == "[Verse]"
    r = parse_lyria_answer({"candidates": [{"content": {"parts": [{"text": "x"}, {"inline_data": {"mime_type": "audio/wav", "data": audio}}]}}]})
    assert r.mime == "audio/wav"
    with pytest.raises(ModelError) as e:
        parse_lyria_answer({"candidates": [{"content": {"parts": [{"text": "only words"}]}}]})
    assert e.value.reason == "bad_answer"
    with pytest.raises(ModelError) as e:
        parse_lyria_answer({"promptFeedback": {"blockReason": "SAFETY"}})
    assert e.value.reason == "blocked"


def test_the_lyria_adapter_sends_the_prompt_and_images_to_generate_content(monkeypatch):
    sent = {}

    def fake_post(model, url, headers, payload, timeout):
        sent.update(url=url, headers=headers, payload=payload, timeout=timeout)
        return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/mpeg", "data": base64.b64encode(b"mp3").decode()}}]}}]}

    monkeypatch.setattr(adapters_mod, "_post_json", fake_post)
    lyria = LyriaRenderer(None, "test-key", None)
    assert lyria.configured and lyria.name == "lyria-3.5"
    out = lyria.render("A song", [("image/jpeg", b"jpg")], timeout=99)
    assert out.audio == b"mp3"
    assert sent["url"] == "https://generativelanguage.googleapis.com/v1beta/models/lyria-3.5:generateContent"
    assert sent["headers"] == {"x-goog-api-key": "test-key"} and sent["timeout"] == 99
    parts = sent["payload"]["contents"][0]["parts"]
    assert parts[0] == {"text": "A song"} and parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert sent["payload"]["generationConfig"]["responseModalities"] == ["AUDIO", "TEXT"]
    assert not LyriaRenderer(None, None, None).configured


def test_a_vocal_take_replaces_the_guide_voice_and_can_be_taken_off_again(client):
    api = Api(client)
    song = api.song()
    take = api.upload(wav_bytes(seconds=1.5), "vocal_take", "take.wav", "audio/wav")
    with_take = api.edit(song, {"op": "setVocalTake", "assetId": take["id"]})
    assert_valid(with_take)
    vocal = with_take["tracks"]["vocal"]
    assert vocal["source"] == "recording" and vocal["renderAssetId"] == take["id"]
    assert any(a["id"] == take["id"] and a["role"] == "vocal_take" for a in with_take["assets"])
    second = api.upload(wav_bytes(seconds=1.5), "vocal_take", "take2.wav", "audio/wav")
    replaced = api.edit(with_take, {"op": "setVocalTake", "assetId": second["id"]})
    assert not any(a["id"] == take["id"] for a in replaced["assets"])
    back = api.edit(replaced, {"op": "setVocalTake"})
    assert back["tracks"]["vocal"]["source"] == "none" and "renderAssetId" not in back["tracks"]["vocal"]
    assert not any(a["role"] == "vocal_take" for a in back["assets"])
    photo = api.upload(png_bytes(), "photo", "p.png", "image/png")
    api.edit(back, {"op": "setVocalTake", "assetId": photo["id"]}, expect=422)
