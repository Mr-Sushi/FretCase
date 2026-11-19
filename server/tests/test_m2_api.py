"""Milestone 2 API: candidates, regions and the new edit ops, lyrics with a model, the song page."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import Api, assert_valid, png_bytes, wav_bytes
from fretcase_engine import editing
from fretcase_engine.candidates import song_signature
from fretcase_server.adapters import Adapters, Offline
from fretcase_server.app import create_app
from fretcase_server.config import Settings


class FakeText:
    """A fake text model. ``mode``: "good" answers with the right number of syllables, "short" is wrong the first
    time, "wrong" is always wrong, "error" raises."""

    configured = True

    def __init__(self, mode="good"):
        self.mode, self.prompts = mode, []
        self.first_wrong_only = False

    def start(self, mode):
        """Switch mode once the song is made (making a song asks the model for lyrics too)."""
        self.mode, self.prompts = mode, []
        self.first_wrong_only = mode == "short"

    def complete(self, system, prompt, max_tokens=1500, timeout=20.0):
        self.prompts.append(prompt)
        if self.mode == "error":
            raise TimeoutError("slow")
        wrong = self.mode == "wrong" or (self.mode == "short" and len(self.prompts) == 1)
        if self.mode == "off":
            raise TimeoutError("not now")
        if "section by section" in prompt:
            structure = json.loads(re.search(r"\n(\[.*\])\n", prompt).group(1))
            out = [
                {"id": row["id"], "chars": list("海" * (row["characters"] + (1 if wrong else 0)))}
                for sec in structure for row in sec["lines"]
                if "characters" in row and row.get("note") != "not needed now"
            ]
            return "Here you go: " + json.dumps({"lines": out}, ensure_ascii=False)
        count = int(re.search(r"each EXACTLY (\d+) characters", prompt).group(1))
        need = int(re.search(r"Give (\d+) other", prompt).group(1))
        words = ["山", "云", "风", "雨", "星"]
        alts = [{"chars": list(words[i % 5] * (count + (1 if wrong else 0))), "note": "更含蓄"} for i in range(need)]
        return json.dumps({"alternatives": alts}, ensure_ascii=False)


@pytest.fixture
def text_api(make_client):
    model = FakeText()
    client = make_client(adapters=Adapters(text_model=model))
    return Api(client), model


def candidates(api, **extra):
    seed = api.seed([{"kind": "text", "text": "海边的傍晚 平静"}])
    r = api.c.post("/api/candidates", json={"seed": seed, **extra})
    assert r.status_code == 201, r.text
    songs = r.json()["candidates"]
    assert len(songs) == 3
    for s in songs:
        assert_valid(s)
    return seed, songs


def verse(song, track):
    sec = song["sections"][1]
    bt = 1920
    return [n for n in song["tracks"][track]["notes"] if sec["startBar"] * bt <= n["start"] < sec["endBar"] * bt]


# ----------------------------------------------------------------------------------------------- candidates


def test_candidates_are_three_hidden_valid_drafts_with_different_parts(api):
    _, songs = candidates(api, timeOfDay="dusk")
    assert [s["candidate"]["index"] for s in songs] == [0, 1, 2]
    assert len({s["candidate"]["groupId"] for s in songs}) == 1
    assert len({json.dumps(s["candidate"]["parts"], sort_keys=True) for s in songs}) == 3
    assert all(s["candidate"]["timeOfDay"] == "dusk" and s["candidate"]["chosen"] is False for s in songs)
    assert api.c.get("/api/songs").json() == {"songs": []}  # drafts are not listed
    assert api.c.get(f"/api/songs/{songs[0]['id']}").json()["song"] == songs[0]  # but they can be read
    assert all(s["card"]["style"] == "text" and s["revision"] == 0 for s in songs)


def test_choose_keeps_one_and_deletes_the_others(api):
    _, songs = candidates(api)
    chosen = api.c.post(f"/api/songs/{songs[1]['id']}/choose", json={}).json()["song"]
    assert_valid(chosen)
    assert chosen["candidate"]["chosen"] is True and chosen["revision"] == 1 and chosen["candidate"]["name"] == songs[1]["candidate"]["name"]
    assert [s["id"] for s in api.c.get("/api/songs").json()["songs"]] == [songs[1]["id"]]
    for other in (songs[0], songs[2]):
        assert api.c.get(f"/api/songs/{other['id']}").status_code == 404
    assert api.c.post(f"/api/songs/{songs[1]['id']}/choose", json={}).json()["song"] == chosen  # asking twice changes nothing
    edited = api.edit(chosen, {"op": "setTempo", "tempo": 70})  # the song now behaves like any other
    assert edited["tempo"] == 70
    plain = api.song()
    r = api.c.post(f"/api/songs/{plain['id']}/choose", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "cannot_apply"
    assert api.c.post("/api/songs/song-nothing-here/choose", json={}).status_code == 404


def test_another_round_avoids_the_previous_combinations(api):
    seed, first = candidates(api, timeOfDay="day")
    r = api.c.post("/api/candidates", json={"seed": seed, "timeOfDay": "day", "previousGroupId": first[0]["candidate"]["groupId"]})
    second = r.json()["candidates"]
    assert second[0]["candidate"]["groupId"] != first[0]["candidate"]["groupId"]
    assert not {song_signature(s) for s in first} & {song_signature(s) for s in second}


def test_time_of_day_changes_the_arrangement(api):
    seed = api.seed([{"kind": "text", "text": "海边的傍晚"}])
    by = {}
    for tod in ("day", "night"):
        by[tod] = api.c.post("/api/candidates", json={"seed": seed, "timeOfDay": tod}).json()["candidates"]
    assert min(s["tempo"] for s in by["day"]) > max(s["tempo"] for s in by["night"])


def test_drafts_expire_after_24_hours_but_chosen_songs_stay(make_client):
    now = {"t": "2026-11-19T10:00:00Z"}
    client = make_client(clock=lambda: now["t"])
    api = Api(client)
    _, first = candidates(api)
    now["t"] = "2026-11-19T20:00:00Z"
    _, second = candidates(api)
    keep = api.c.post(f"/api/songs/{second[0]['id']}/choose", json={}).json()["song"]
    now["t"] = "2026-11-20T11:00:00Z"  # 25 hours after the first group, 15 after the second
    assert client.get(f"/api/songs/{first[0]['id']}").status_code == 404
    assert client.get(f"/api/songs/{keep['id']}").status_code == 200
    assert [s["id"] for s in client.get("/api/songs").json()["songs"]] == [keep["id"]]
    now["t"] = "2026-11-25T10:00:00Z"
    assert client.get(f"/api/songs/{keep['id']}").status_code == 200  # chosen: no expiry


def test_candidates_use_a_hum_a_sound_and_photos(api):
    hum = api.upload(wav_bytes([261.6, 293.7, 329.6, 349.2], 3.0), "hum", "h.wav", "audio/wav")
    sound = api.upload(wav_bytes([200.0], 1.0), "ambience", "s.wav", "audio/wav")
    photo = api.upload(png_bytes(color=(230, 150, 90)), "photo", "p.png", "image/png")
    seed = api.seed([{"kind": "hum", "assetId": hum["id"]}, {"kind": "sound", "assetId": sound["id"]}, {"kind": "photo", "assetId": photo["id"]}, {"kind": "text", "text": "傍晚"}])
    r = api.c.post("/api/candidates", json={"seed": seed})
    assert r.status_code == 201
    for s in r.json()["candidates"]:
        assert_valid(s)
        assert s["card"]["style"] == "xieyi" and s["card"]["coverAssetId"] == photo["id"] and s["card"]["photoAssetIds"] == [photo["id"]]
        assert any(r["play"] for r in s["tracks"]["ambience"]["regions"]) and s["tracks"]["ambience"]["clips"]
        assert {a["id"] for a in s["assets"]} >= {sound["id"], photo["id"]}


def test_photos_limit_is_nine(api):
    photos = [api.upload(png_bytes(), "photo", f"{i}.png", "image/png") for i in range(10)]
    inputs = [{"kind": "photo", "assetId": p["id"]} for p in photos]
    r = api.c.post("/api/seed", json={"inputs": inputs})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    ok = api.seed(inputs[:9])
    assert sum(1 for i in ok["inputs"] if i["kind"] == "photo") == 9
    too_many = {**ok, "inputs": inputs}
    assert api.c.post("/api/candidates", json={"seed": too_many}).status_code == 400
    assert api.c.post("/api/songs", json={"seed": too_many}).status_code == 400


def test_photo_larger_than_4096_is_scaled_down_on_upload(api):
    photo = api.upload(png_bytes(size=(5000, 100)), "photo", "wide.png", "image/png")
    assert (photo["width"], photo["height"]) == (4096, 82)


# ----------------------------------------------------------------------------------------------- regions and the new ops


def test_region_ops_through_the_api_and_undo(api):
    song = api.song()
    out = api.edit(song, {"op": "setRegion", "track": "drums", "section": "s-verse", "play": False}, {"op": "setMaster", "volume": 0.4, "space": "hall"})
    assert out["revision"] == 1 and out["master"] == {"volume": 0.4, "space": "hall"}
    assert verse(out, "drums") == [] and {"track": "drums", "section": "s-verse"} in out["locks"]
    back = api.post(out, "undo")
    assert verse(back, "drums") and back["master"] == song["master"] and back["tracks"]["drums"]["regions"] == song["tracks"]["drums"]["regions"]


@pytest.mark.parametrize("op", [
    {"op": "setRegion", "track": "guitar", "section": "s-verse", "style": "walking"},
    {"op": "setRegion", "track": "guitar", "section": "s-nowhere", "play": False},
    {"op": "setRegion", "track": "guitar", "section": "s-verse"},
    {"op": "shiftRegister", "track": "drums", "section": "s-verse", "direction": "up"},
    {"op": "shiftRegister", "track": "ambience", "section": "s-verse", "direction": "down"},
    {"op": "revertMelody", "section": "s-verse"},
    {"op": "setLead", "section": "s-verse", "track": "guitar"} if False else {"op": "copyRegion", "track": "guitar", "section": "s-nowhere"},
    {"op": "setMaster"},
])
def test_region_ops_that_cannot_apply_are_422(api, op):
    assert api.edit(api.song(), op, expect=422)["code"] == "cannot_apply"


@pytest.mark.parametrize("op", [
    {"op": "setRegion", "track": "guitar", "section": "s-verse", "complexity": 1.5},
    {"op": "setLead", "section": "s-verse", "track": "bass"},
    {"op": "shiftRegister", "track": "bass", "section": "s-verse", "direction": "sideways"},
    {"op": "setMaster", "space": "cave"},
])
def test_malformed_region_ops_are_400(api, op):
    assert api.edit(api.song(), op, expect=400)["code"] == "invalid_request"


def test_lead_and_copy_region_and_shift_through_the_api(api):
    song = api.song()
    led = api.edit(song, {"op": "setLead", "section": "s-verse", "track": "vocal"})
    assert led["sections"][1]["lead"] == "vocal"
    cleared = api.edit(led, {"op": "setLead", "section": "s-verse", "track": None})
    assert "lead" not in cleared["sections"][1] and cleared["tracks"] == song["tracks"]
    copied = api.edit(cleared, {"op": "setRegion", "track": "guitar", "section": "s-verse", "complexity": 0.9}, {"op": "copyRegion", "track": "guitar", "section": "s-verse"})
    assert {r["complexity"] for r in copied["tracks"]["guitar"]["regions"]} == {0.9}
    shifted = api.edit(copied, {"op": "shiftRegister", "track": "melody", "section": "s-verse", "direction": "up"})
    assert [n["pitch"] for n in verse(shifted, "melody")] != [n["pitch"] for n in verse(copied, "melody")]


def test_revert_melody_with_a_hum(api):
    hum = api.upload(wav_bytes([261.6, 293.7, 329.6, 349.2], 3.0), "hum", "h.wav", "audio/wav")
    seed = api.seed([{"kind": "hum", "assetId": hum["id"]}])
    if not seed.get("motif"):
        pytest.skip("no hum transcriber on this machine")
    song = api.song(seed=seed)
    moved = api.edit(song, {"op": "shiftRegister", "track": "melody", "section": "s-verse", "direction": "up"})
    back = api.edit(moved, {"op": "revertMelody", "section": "s-verse"})
    assert [n["pitch"] for n in verse(back, "melody")] == [n["pitch"] for n in verse(song, "melody")]


def test_line_by_line_lyrics_errors_through_the_api(api):
    song = api.song()
    lines = editing.lyric_lines(editing.vocal_notes_in(song, song["sections"][1]))
    counts = [len(l) for l in lines]
    text = "\n".join("海" * c for c in counts[:-1] + [counts[-1] + 2])
    error = api.edit(song, {"op": "setLyrics", "section": "s-verse", "text": text}, expect=422)
    assert error["code"] == "cannot_apply"
    assert error["detail"]["lines"] == [{"index": len(counts) - 1, "noteCount": counts[-1], "syllableCount": counts[-1] + 2}]
    ok = api.edit(song, {"op": "setLyrics", "section": "s-verse", "text": "\n".join("海" * c for c in counts)})
    assert {n["lyric"] for n in verse(ok, "vocal")} == {"海"}


def test_title_change_clears_the_preview(api):
    previewed = api.post(api.song(), "card/preview")
    assert api.edit(previewed, {"op": "setTitle", "title": "新名字"})["card"].get("frontAssetId") is None


# ----------------------------------------------------------------------------------------------- lyrics endpoints


def test_lyrics_endpoints_answer_503_without_a_model(api):
    song = api.song()
    r = api.c.post(f"/api/songs/{song['id']}/lyrics", json={"baseRevision": 0, "themes": ["海"]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "offline_unavailable"
    r = api.c.post(f"/api/songs/{song['id']}/lyrics/alternatives", json={"section": "s-verse", "line": 0})
    assert r.status_code == 503 and r.json()["error"]["code"] == "offline_unavailable"
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"] == song  # nothing changed


def test_themes_come_from_the_text_and_photo_colours_offline(api):
    photo = api.upload(png_bytes(color=(230, 150, 90)), "photo", "p.png", "image/png")
    seed = api.seed([{"kind": "text", "text": "海边的傍晚 想家"}, {"kind": "photo", "assetId": photo["id"]}])
    song = api.song(seed=seed)
    themes = api.c.get(f"/api/songs/{song['id']}/lyrics/themes").json()["themes"]
    by_text = {t["text"]: t["source"] for t in themes}
    assert by_text["海边"] == "text" and "海" not in by_text and by_text["想家"] == "text" and by_text["暖光"] == "photo"
    assert api.c.get("/api/songs/song-nothing-here/lyrics/themes").status_code == 404


def test_lyrics_rewrite_with_a_model_and_keep(text_api):
    api, model = text_api
    model.mode = "off"  # the new song keeps its 啦
    song = api.song()
    model.start("good")
    lines = editing.lyric_lines(editing.vocal_notes_in(song, song["sections"][1]))
    song = api.edit(song, {"op": "setLyrics", "section": "s-verse", "text": "\n".join("山" * len(l) for l in lines)})
    out = api.post(song, "lyrics", sections=["s-verse", "s-chorus"], keep={"s-verse": [0]}, themes=["海", "想家"], tone="subtle", rhyme=True)
    assert out["revision"] == song["revision"] + 1
    got = [("".join(n["lyric"] for n in l)) for l in editing.lyric_lines(editing.vocal_notes_in(out, out["sections"][1]))]
    assert got[0] == "山" * len(lines[0]) and all(g == "海" * len(l) for g, l in zip(got[1:], lines[1:]))
    untouched = [n for n in out["tracks"]["vocal"]["notes"] if n["start"] < 4 * 1920]
    assert all(n["lyric"] == "啦" for n in untouched)  # the intro was not asked for
    assert "海, 想家" in model.prompts[0] and "subtle" in model.prompts[0]
    for prompt in model.prompts:
        assert "section by section" in prompt
    undone = api.post(out, "undo")
    assert [n.get("lyric") for n in verse(undone, "vocal")] == [n.get("lyric") for n in verse(song, "vocal")]


def test_lyrics_with_every_line_kept_has_nothing_to_write(text_api):
    api, model = text_api
    model.mode = "off"
    song = api.song()
    count = len(editing.lyric_lines(editing.vocal_notes_in(song, song["sections"][1])))
    error = api.post(song, "lyrics", expect=422, sections=["s-verse"], keep={"s-verse": list(range(count))})
    assert error["code"] == "cannot_apply"


def test_the_server_checks_syllable_counts_and_retries(make_client):
    model = FakeText("off")
    api = Api(make_client(adapters=Adapters(text_model=model)))
    song = api.song()
    model.start("short")
    out = api.post(song, "lyrics", sections=["s-verse"])
    assert len(model.prompts) == 2 and "wrong length" in model.prompts[1]
    notes = verse(out, "vocal")
    assert all(n["lyric"] == "海" for n in notes)


@pytest.mark.parametrize("mode", ["wrong", "error"])
def test_lyrics_fail_with_503_when_the_model_cannot_deliver(make_client, mode):
    model = FakeText("off")
    api = Api(make_client(adapters=Adapters(text_model=model)))
    song = api.song()
    model.start(mode)
    r = api.c.post(f"/api/songs/{song['id']}/lyrics", json={"baseRevision": song["revision"]})
    assert r.status_code == 503 and r.json()["error"]["code"] == "offline_unavailable"
    assert r.json()["error"]["detail"]["reason"] == {"wrong": "bad_answer", "error": "timeout"}[mode]
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"] == song
    if mode == "wrong":
        assert len(model.prompts) == 3  # two retries with the counts, then give up
        assert "needs" in model.prompts[1] and "you wrote" in model.prompts[1]


def test_lyrics_with_a_stale_revision_is_409(text_api):
    api, model = text_api
    model.mode = "off"
    song = api.song()
    api.edit(song, {"op": "setTempo", "tempo": 70})
    r = api.c.post(f"/api/songs/{song['id']}/lyrics", json={"baseRevision": 0})
    assert r.status_code == 409 and r.json()["error"]["song"]["revision"] == 1


def test_alternatives_are_three_lines_of_exactly_the_right_length(text_api):
    api, model = text_api
    model.mode = "off"
    song = api.song()
    model.start("good")
    lines = editing.lyric_lines(editing.vocal_notes_in(song, song["sections"][1]))
    r = api.c.post(f"/api/songs/{song['id']}/lyrics/alternatives", json={"section": "s-verse", "line": 1, "themes": ["海"]})
    assert r.status_code == 200
    alts = r.json()["alternatives"]
    assert len(alts) == 3 and len({a["text"] for a in alts}) == 3
    assert all(len(a["text"]) == len(lines[1]) and a["note"] for a in alts)
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"] == song  # the song does not change
    assert api.c.post(f"/api/songs/{song['id']}/lyrics/alternatives", json={"section": "s-verse", "line": 99}).status_code == 422
    assert api.c.post(f"/api/songs/{song['id']}/lyrics/alternatives", json={"section": "s-none", "line": 0}).status_code == 422


def test_alternatives_with_wrong_lengths_are_503(make_client):
    api = Api(make_client(adapters=Adapters(text_model=FakeText("wrong"))))
    song = api.song()
    assert api.c.post(f"/api/songs/{song['id']}/lyrics/alternatives", json={"section": "s-verse", "line": 0}).status_code == 503


def test_a_new_song_gets_model_lyrics_when_a_model_answers(text_api):
    api, _ = text_api
    song = api.song()
    assert any(n["lyric"] == "海" for n in song["tracks"]["vocal"]["notes"])
    assert all(n["lyric"] for n in song["tracks"]["vocal"]["notes"])


def test_the_text_model_adapter_speaks_the_messages_format(monkeypatch):
    from fretcase_server.adapters import AnthropicTextModel

    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "好"}]}).encode()

    def fake_urlopen(request, timeout):
        sent.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data), timeout=timeout)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    model = AnthropicTextModel("https://models.example", "secret", "some-model")
    assert model.complete("sys", "hi", timeout=20.0) == "好"
    assert sent["url"] == "https://models.example/v1/messages" and sent["timeout"] == 20.0
    assert sent["headers"]["X-api-key"] == "secret" and sent["headers"]["Anthropic-version"] == "2023-06-01"
    assert sent["body"]["model"] == "some-model" and sent["body"]["system"] == "sys" and sent["body"]["messages"] == [{"role": "user", "content": "hi"}]
    with pytest.raises(Offline):
        AnthropicTextModel(None, None, None).complete("s", "p")


# ----------------------------------------------------------------------------------------------- song page


def shared_song(api, **card):
    photos = [api.upload(png_bytes(color=(40 * i, 120, 200)), "photo", f"{i}.png", "image/png") for i in range(3)]
    sound = api.upload(wav_bytes([200.0], 1.0), "ambience", "s.wav", "audio/wav")
    hum = api.upload(wav_bytes([261.6, 293.7, 329.6], 2.0), "hum", "h.wav", "audio/wav")
    seed = api.seed([{"kind": "photo", "assetId": p["id"]} for p in photos] + [{"kind": "sound", "assetId": sound["id"]}, {"kind": "hum", "assetId": hum["id"]}, {"kind": "text", "text": "好听的标题"}, {"kind": "text", "text": "秘密的种子文字"}])
    song = api.song(seed=seed)
    api.c.put("/api/location", json={"city": "厦门"})
    song = api.edit(song, {"op": "setCard", "line": "海风把傍晚吹进歌里", "message": "回来唱给你听", "city": "厦门", **card})
    song = api.post(song, "card/preview")
    return song, photos, sound, hum


def test_song_page_hides_city_and_photos_unless_shown(api):
    song, photos, sound, hum = shared_song(api, showCity=False, showPhoto=False)
    share = song["card"]["share"]["shareId"]
    body = api.c.get(f"/api/share/{share}/page").json()
    page, public = body["page"], body["song"]
    assert page["title"] == song["title"] and page["line"] == "海风把傍晚吹进歌里" and page["message"] == "回来唱给你听"
    assert "city" not in page and page["photos"] == []
    assert page["card"] == f"/api/share/{share}/assets/{song['card']['frontAssetId']}" and page["date"] == song["createdAt"][:10]
    assert "厦门" not in json.dumps(body, ensure_ascii=False)
    assert "seed" not in public and "provenance" not in public and "秘密的种子文字" not in json.dumps(body, ensure_ascii=False)
    assert_valid(public)
    assert photos[0]["id"] not in json.dumps(body) and hum["id"] not in json.dumps(body)
    assert {a["id"] for a in public["assets"]} == {sound["id"], song["card"]["frontAssetId"]}
    assert api.c.get(f"/api/share/{share}/assets/{photos[0]['id']}").status_code == 404
    assert api.c.get(f"/api/share/{share}/assets/{hum['id']}").status_code == 404
    assert api.c.get(f"/api/share/{share}/assets/{sound['id']}").status_code == 200
    card = api.c.get(page["card"])
    assert card.status_code == 200 and card.headers["content-type"] == "image/png"
    assert page["lyrics"] and page["lyrics"][0]["section"] and all(isinstance(l, str) for l in page["lyrics"][0]["lines"])


def test_song_page_shows_city_and_photos_in_order_when_shown(api):
    song, photos, sound, hum = shared_song(api, showCity=True, showPhoto=True)
    # the song page lists photos in photoAssetIds order
    order = [photos[2]["id"], photos[0]["id"], photos[1]["id"]]
    song = api.post(api.edit(song, {"op": "setCard", "photoAssetIds": order, "coverAssetId": order[0]}), "card/preview")
    share = song["card"]["share"]["shareId"]
    body = api.c.get(f"/api/share/{share}/page").json()
    assert body["page"]["city"] == "厦门"
    assert body["page"]["photos"] == [f"/api/share/{share}/assets/{a}" for a in order]
    assert all(api.c.get(u).status_code == 200 for u in body["page"]["photos"])
    assert_valid(body["song"])
    assert body["song"]["card"]["city"] == "厦门"


def test_song_page_card_only_after_a_preview_and_unknown_share_is_404(api):
    song = api.song()
    assert api.c.get("/api/share/doesNotExist1/page").status_code == 404
    assert api.c.get("/api/share/doesNotExist1/assets/a-whatever-1").status_code == 404
    song = api.post(song, "card/preview")
    page = api.c.get(f"/api/share/{song['card']['share']['shareId']}/page").json()["page"]
    assert "card" in page and "subtitle" not in page  # a song that is no candidate has no subtitle
    _, drafts = candidates(api)
    chosen = api.c.post(f"/api/songs/{drafts[0]['id']}/choose", json={}).json()["song"]
    chosen = api.post(chosen, "card/preview")
    assert api.c.get(f"/api/share/{chosen['card']['share']['shareId']}/page").json()["page"]["subtitle"] == drafts[0]["candidate"]["name"]


def test_qr_url_uses_the_share_base_or_the_servers_own_origin(tmp_path, card_module):
    own = TestClient(create_app(Settings(data_dir=tmp_path / "a", share_base_url=None), card_module_loader=lambda: card_module))
    song = Api(own).post(Api(own).song(), "card/preview")
    assert song["card"]["share"]["url"].startswith("http://testserver/s/")
    based = TestClient(create_app(Settings(data_dir=tmp_path / "b", share_base_url="https://pi.example:8443/"), card_module_loader=lambda: card_module))
    song = Api(based).post(Api(based).song(), "card/preview")
    assert song["card"]["share"]["url"] == f"https://pi.example:8443/s/{song['card']['share']['shareId']}"


def test_song_page_html_is_served_from_the_app_build(tmp_path, card_module):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "song.html").write_text("<!doctype html><title>song</title>", encoding="utf-8")
    (dist / "assets" / "song.js").write_text("console.log(1)", encoding="utf-8")
    client = TestClient(create_app(Settings(data_dir=tmp_path / "d", app_dist=dist), card_module_loader=lambda: card_module))
    for path in ("/s/k3Hq9xV2mPzT", "/s/anything-at-all"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "<title>song</title>" in r.text
    assert client.get("/assets/song.js").status_code == 200
    assert client.get("/assets/../../etc/passwd").status_code == 404
    assert client.get("/api/nothing-here").json()["error"]["code"] == "not_found"
    missing = TestClient(create_app(Settings(data_dir=tmp_path / "e", app_dist=tmp_path / "nowhere"), card_module_loader=lambda: card_module))
    r = missing.get("/s/k3Hq9xV2mPzT")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/plain") and len(r.text) < 200


def test_undo_never_changes_a_printed_card_and_previews_are_not_undo_steps(api):
    song = api.song()
    song = api.edit(song, {"op": "setCard", "line": "海风把傍晚吹进歌里", "message": "回来唱给你听"})
    song = api.post(song, "card/preview")
    printed = api.post(song, "card/print")
    card = printed["card"]
    # one undo takes back the setCard, not the preview; the printed card stays exactly as printed
    back = api.post(printed, "undo")
    assert back["card"] == card and back["title"] == printed["title"]
    assert any(a["id"] == card["frontAssetId"] for a in back["assets"])
    page = api.c.get(f"/api/share/{card['share']['shareId']}/page").json()["page"]
    assert page["line"] == "海风把傍晚吹进歌里" and page.get("card")


def test_bass_register_moves_the_notes_that_fit(api):
    for direction in ("up", "down"):
        song = api.song()
        section = next(s for s in song["sections"] if any(r["play"] for r in song["tracks"]["bass"]["regions"] if r["section"] == s["id"]))
        out = api.edit(song, {"op": "shiftRegister", "track": "bass", "section": section["id"], "direction": direction})
        assert out["tracks"]["bass"]["notes"] != song["tracks"]["bass"]["notes"]
        assert all(28 <= n["pitch"] <= 55 for n in out["tracks"]["bass"]["notes"])



class RefusingModel:
    configured = True

    def __init__(self, reason):
        self.reason, self.calls = reason, 0

    def complete(self, *a, **k):
        from fretcase_server.adapters import ModelError

        self.calls += 1
        raise ModelError(self.reason)


@pytest.mark.parametrize("reason", ["auth", "rate_limited", "unreachable"])
def test_a_refused_model_call_says_why(make_client, reason):
    model = RefusingModel(reason)
    api = Api(make_client(adapters=Adapters(text_model=model)))
    song = api.song()  # making a song tries the model once and keeps 啦
    r = api.c.post(f"/api/songs/{song['id']}/lyrics", json={"baseRevision": song["revision"]})
    assert r.status_code == 503 and r.json()["error"]["detail"]["reason"] == reason


def test_without_a_model_the_reason_is_not_configured(api):
    song = api.song()
    r = api.c.post(f"/api/songs/{song['id']}/lyrics", json={"baseRevision": song["revision"]})
    assert r.status_code == 503 and r.json()["error"]["detail"]["reason"] == "not_configured"
    assert api.c.get("/health").json()["lyrics"] is False


def test_choosing_does_not_wait_for_the_model(text_api):
    api, model = text_api
    made = api.c.post("/api/candidates", json={"seed": api.c.post("/api/seed", json={"inputs": [{"kind": "text", "text": "海边的傍晚"}]}).json()["seed"]}).json()["candidates"]
    model.start("good")
    chosen = api.c.post(f"/api/songs/{made[0]['id']}/choose", json={}).json()["song"]
    assert model.prompts == [] and chosen["candidate"]["chosen"] is True
    assert api.c.get("/health").json()["lyrics"] is True


def test_the_text_model_defaults_to_the_anthropic_api_when_only_a_key_is_set():
    from fretcase_server.adapters import AnthropicTextModel

    m = AnthropicTextModel(None, "sk-test", None)
    assert m.configured and m.endpoint() == "https://api.anthropic.com/v1/messages" and m.name == "claude-sonnet-5-5"
    assert not AnthropicTextModel(None, None, None).configured


def test_env_file_is_read_without_overriding(tmp_path, monkeypatch):
    from fretcase_server.config import load_env_file

    f = tmp_path / ".env"
    f.write_text('# comment\nFRETCASE_TEXT_MODEL_KEY="sk-from-file"\nexport FRETCASE_SHARE_BASE=https://a.example\n', encoding="utf-8")
    monkeypatch.delenv("FRETCASE_TEXT_MODEL_KEY", raising=False)
    monkeypatch.setenv("FRETCASE_SHARE_BASE", "https://kept.example")
    load_env_file(f)
    import os

    assert os.environ["FRETCASE_TEXT_MODEL_KEY"] == "sk-from-file"
    assert os.environ["FRETCASE_SHARE_BASE"] == "https://kept.example"
    monkeypatch.delenv("FRETCASE_TEXT_MODEL_KEY")
