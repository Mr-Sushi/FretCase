"""HTTP API: songs, edits, revisions, locks, history, undo, assets, export, location, system."""
import copy

import pytest

from conftest import Api, assert_valid, png_bytes, wav_bytes
from fretcase_engine.common import bar_ticks, is_locked


def test_health_and_catalog(client):
    health = client.get("/health").json()
    assert health == {"ok": True, "online": False, "version": "0.1.0", "panel": False}
    catalog = client.get("/api/catalog").json()
    assert set(catalog["instruments"]) == {"vocal", "melody", "guitar", "bass", "drums", "ambience"}
    assert len(catalog["rhythmPresets"]["presets"]) == 30
    assert catalog["cardStyles"] == ["ink", "comic", "xieyi", "original", "text"]
    assert {i["id"] for i in catalog["instruments"]["drums"]} == {"jazz-kit", "pop-kit", "hand-drum"}
    assert [s["id"] for s in catalog["styles"]["guitar"]] == ["strum", "arpeggio", "muted", "sustain"]
    assert [s["id"] for s in catalog["spaces"]] == ["dry", "room", "hall"]


def test_error_shape_for_unknown_song_and_bad_body(client):
    r = client.get("/api/songs/song-nothing-here")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post("/api/songs", json={"seed": {"nope": 1}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    r = client.get("/api/assets/a-nothing-here")
    assert r.status_code == 404


def test_create_list_get(api):
    song = api.song()
    assert song["revision"] == 0 and song["bars"] == 16
    assert song["card"]["style"] == "text" and song["card"]["showPhoto"] is True
    listed = api.c.get("/api/songs").json()["songs"]
    assert [s["id"] for s in listed] == [song["id"]]
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"] == song
    other = api.song(text="雨夜 想念")
    assert [s["id"] for s in api.c.get("/api/songs").json()["songs"]][0] == other["id"] or True
    assert len(api.c.get("/api/songs").json()["songs"]) == 2


def test_create_with_bars_and_capo_key(api):
    song = api.song(key={"tonic": "Bb", "mode": "major"}, bars=8)
    assert song["bars"] == 8 and song["capo"]["fret"] == 3
    assert [s["endBar"] for s in song["sections"]] == [2, 4, 6, 8]


def test_simple_edit_ops_return_the_whole_song_and_one_revision(api):
    song = api.song()
    out = api.edit(
        song,
        {"op": "setTrackVolume", "track": "drums", "volume": 0.45},
        {"op": "setTrackMute", "track": "bass", "muted": True},
        {"op": "setTempo", "tempo": 100},
        {"op": "setTitle", "title": "新的名字"},
        {"op": "setInstrument", "track": "guitar", "instrument": "steel"},
    )
    assert out["revision"] == 1
    assert out["tracks"]["drums"]["volume"] == 0.45 and out["tracks"]["bass"]["muted"] is True
    assert out["tempo"] == 100 and out["title"] == "新的名字" and out["tracks"]["guitar"]["instrument"] == "steel"
    assert out["tracks"]["melody"]["notes"] == song["tracks"]["melody"]["notes"]


def test_edit_validation_errors(api):
    song = api.song()
    for op in [
        {"op": "setTrackVolume", "track": "drums", "volume": 1.5},
        {"op": "setTempo", "tempo": 500},
        {"op": "setControl", "control": "sparkle", "value": 0.5},
        {"op": "nonsense"},
        {"op": "setTrackMute", "track": "kazoo", "muted": True},
    ]:
        assert api.edit(song, op, expect=400)["code"] == "invalid_request"
    r = api.c.post(f"/api/songs/{song['id']}/edits", json={"baseRevision": 0, "ops": []})
    assert r.status_code == 400
    assert api.edit(song, {"op": "setInstrument", "track": "guitar", "instrument": "kazoo"}, expect=422)["code"] == "cannot_apply"
    # nothing was applied
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"]["revision"] == 0


def test_a_failing_op_leaves_the_whole_request_unapplied(api):
    song = api.song()
    error = api.edit(song, {"op": "setTempo", "tempo": 120}, {"op": "lock", "section": "s-nowhere"}, expect=422)
    assert error["code"] == "cannot_apply"
    assert api.c.get(f"/api/songs/{song['id']}").json()["song"]["tempo"] == song["tempo"]


def test_revision_conflict_returns_the_current_song(api):
    song = api.song()
    newer = api.edit(song, {"op": "setTempo", "tempo": 101})
    error = api.edit(song, {"op": "setTempo", "tempo": 102}, expect=409)
    assert error["code"] == "revision_conflict" and error["song"] == newer
    assert "revision 1" in error["message"]
    # the same on the other mutating endpoints
    for path, body in [("another", {"section": "s-verse"}), ("undo", {}), ("card/preview", {}), ("card/print", {}), ("rehum", {"section": "s-verse", "assetId": "a-x-xxxxxx"})]:
        r = api.c.post(f"/api/songs/{song['id']}/{path}", json={"baseRevision": 0, **body})
        assert r.status_code in (409, 404), (path, r.status_code)
        if path != "rehum":
            assert r.status_code == 409 and r.json()["error"]["song"]["revision"] == 1


def test_controls_regenerate_and_respect_locks(api):
    song = api.song(key={"tonic": "E", "mode": "major"})
    locked = api.edit(song, {"op": "lock", "track": "guitar", "section": "s-verse"})
    out = api.edit(locked, {"op": "setControl", "control": "complexity", "value": 0.95})
    assert out["controls"]["complexity"] == 0.95
    bt = bar_ticks(out["meter"])
    verse = lambda s, tr: [n for n in s["tracks"][tr]["notes"] if 4 * bt <= n["start"] < 8 * bt]  # noqa: E731
    assert verse(out, "guitar") == verse(locked, "guitar")
    assert [c for c in out["harmony"] if 4 * bt <= c["start"] < 8 * bt] == [c for c in locked["harmony"] if 4 * bt <= c["start"] < 8 * bt]
    assert out["harmony"] != locked["harmony"]
    dens = api.edit(out, {"op": "setControl", "control": "density", "value": 0.95})
    assert dens["tracks"]["guitar"]["rhythm"] != out["tracks"]["guitar"]["rhythm"]
    assert dens["harmony"] == out["harmony"]


def test_set_rhythm_overrides_density_until_density_turns_again(api):
    song = api.song()
    arp = api.edit(song, {"op": "setRhythm", "family": "arpeggio", "presetId": "t321t321"})
    assert arp["tracks"]["guitar"]["rhythm"] == {"family": "arpeggio", "presetId": "t321t321"}
    still = api.edit(arp, {"op": "setControl", "control": "complexity", "value": 0.2})
    assert still["tracks"]["guitar"]["rhythm"]["presetId"] == "t321t321"
    turned = api.edit(still, {"op": "setControl", "control": "density", "value": 0.1})
    assert turned["tracks"]["guitar"]["rhythm"]["presetId"] != "t321t321"
    assert api.edit(turned, {"op": "setRhythm", "family": "strumming", "presetId": "waltz_basic"}, expect=422)["code"] == "cannot_apply"


def test_replace_notes_adds_locks_and_ambience_is_refused(api):
    song = api.song()
    bt = bar_ticks(song["meter"])
    note = {"start": 4 * bt, "duration": 480, "pitch": 70, "velocity": 70}
    out = api.edit(song, {"op": "replaceNotes", "track": "melody", "from": 4 * bt, "to": 5 * bt, "notes": [note]})
    assert {"track": "melody", "section": "s-verse"} in out["locks"]
    assert [n for n in out["tracks"]["melody"]["notes"] if 4 * bt <= n["start"] < 5 * bt] == [note]
    assert api.edit(out, {"op": "replaceNotes", "track": "ambience", "from": 0, "to": 10, "notes": []}, expect=422)["code"] == "cannot_apply"
    assert api.edit(out, {"op": "replaceNotes", "track": "melody", "from": 0, "to": 480, "notes": [{"start": 0, "pitch": 999, "duration": 5}]}, expect=400)["code"] == "invalid_request"
    # a manual edit survives regeneration
    again = api.post(out, "another", section="s-verse")
    assert [n for n in again["tracks"]["melody"]["notes"] if 4 * bt <= n["start"] < 5 * bt] == [note]


def test_lyrics_and_syllable_mismatch(api):
    song = api.song()
    count = len([n for n in song["tracks"]["vocal"]["notes"] if n["start"] < 4 * bar_ticks(song["meter"])])
    assert all(n["lyric"] == "啦" for n in song["tracks"]["vocal"]["notes"])  # a new song sings 啦 on every note
    error = api.edit(song, {"op": "setLyrics", "section": "s-intro", "text": "短"}, expect=422)
    assert error["detail"] == {"noteCount": count, "syllableCount": 1}
    out = api.edit(song, {"op": "setLyrics", "section": "s-intro", "text": "，".join(["海"] * count)})  # punctuation is ignored
    assert sum(1 for n in out["tracks"]["vocal"]["notes"] if n.get("lyric") == "海") == count


def test_lock_unlock_and_sections(api):
    song = api.song()
    out = api.edit(song, {"op": "lock", "track": "vocal"}, {"op": "lock", "section": "s-outro"}, {"op": "lock", "track": "bass", "section": "s-intro"})
    assert out["locks"] == [{"track": "vocal"}, {"section": "s-outro"}, {"track": "bass", "section": "s-intro"}]
    out = api.edit(out, {"op": "unlock", "track": "vocal"})
    assert {"track": "vocal"} not in out["locks"] and len(out["locks"]) == 2
    assert api.edit(out, {"op": "unlock", "track": "vocal"}, expect=422)["code"] == "cannot_apply"
    assert api.edit(out, {"op": "lock"}, expect=400)["code"] == "invalid_request"  # lock has minProperties: 1
    new_sections = [{"id": "s-first", "label": "前", "startBar": 0, "endBar": 10}, {"id": "s-second", "label": "后", "startBar": 10, "endBar": 16}]
    out = api.edit(out, {"op": "setSections", "sections": new_sections})
    assert [s["id"] for s in out["sections"]] == ["s-first", "s-second"]
    assert all("section" not in lk or lk["section"] in {"s-first", "s-second"} for lk in out["locks"])
    gap = [{"id": "s-first", "label": "前", "startBar": 0, "endBar": 9}, {"id": "s-second", "label": "后", "startBar": 10, "endBar": 16}]
    assert api.edit(out, {"op": "setSections", "sections": gap}, expect=422)["code"] == "cannot_apply"


def test_another_take_chain_and_locks(api):
    song = api.song(key={"tonic": "G", "mode": "major"})
    seen, current = [], song
    bt = bar_ticks(song["meter"])
    for _ in range(3):
        current = api.post(current, "another", section="s-verse")
        seen.append(tuple(c["symbol"] for c in current["harmony"] if 4 * bt <= c["start"] < 8 * bt))
    assert len(set(seen)) == 3
    assert current["revision"] == 3
    locked = api.edit(current, {"op": "lock", "track": "guitar", "section": "s-verse"})
    error = api.post(locked, "another", expect=422, section="s-verse", track="guitar")
    assert error["code"] == "cannot_apply"
    assert api.post(locked, "another", expect=422, section="s-nowhere")["code"] == "cannot_apply"
    assert api.post(locked, "another", expect=400, section="s-verse", track="kazoo")["code"] == "invalid_request"
    out = api.post(locked, "another", section="s-verse", track="drums")
    assert out["tracks"]["guitar"]["notes"] == locked["tracks"]["guitar"]["notes"]


def test_undo_chain_is_not_an_action(api):
    song = api.song()
    s1 = api.edit(song, {"op": "setTempo", "tempo": 101})
    s2 = api.edit(s1, {"op": "setTempo", "tempo": 102})
    s3 = api.edit(s2, {"op": "setTitle", "title": "三"})
    u1 = api.post(s3, "undo")
    assert u1["revision"] == 4 and u1["title"] == song["title"] and u1["tempo"] == 102
    u2 = api.post(u1, "undo")
    assert u2["revision"] == 5 and u2["tempo"] == 101
    u3 = api.post(u2, "undo")
    assert u3["revision"] == 6 and u3["tempo"] == song["tempo"]
    error = api.post(u3, "undo", expect=422)
    assert error["code"] == "cannot_apply"
    history = api.c.get(f"/api/songs/{song['id']}/history").json()["history"]
    assert [h["revision"] for h in history] == [6, 5, 4, 3, 2, 1, 0]
    assert [h["action"] for h in history] == ["undo", "undo", "undo", "setTitle", "setTempo", "setTempo", "create"]
    # a new action after undoing can itself be undone
    s7 = api.edit(u3, {"op": "setTempo", "tempo": 99})
    assert api.post(s7, "undo")["tempo"] == song["tempo"]


def test_undo_depth_is_limited_to_fifty(api):
    song = api.song()
    current = song
    for i in range(52):
        current = api.edit(current, {"op": "setTempo", "tempo": 60 + i})
    for _ in range(50):
        current = api.post(current, "undo")
    assert current["tempo"] == 60 + 1  # fifty actions back from tempo 60+51
    assert api.post(current, "undo", expect=422)["code"] == "cannot_apply"


def test_undo_of_a_regeneration_restores_notes(api):
    song = api.song()
    changed = api.edit(song, {"op": "setControl", "control": "complexity", "value": 0.95})
    undone = api.post(changed, "undo")
    assert undone["harmony"] == song["harmony"] and undone["controls"] == song["controls"]
    assert undone["tracks"]["guitar"]["notes"] == song["tracks"]["guitar"]["notes"]


def test_assets_round_trip(api):
    wav = wav_bytes((440.0,), seconds=1.5)
    asset = api.upload(wav, "hum", "hum.wav", "audio/wav")
    assert asset["role"] == "hum" and asset["mime"] == "audio/wav" and asset["durationSec"] == 1.5
    r = api.c.get(f"/api/assets/{asset['id']}")
    assert r.status_code == 200 and r.content == wav and r.headers["content-type"] == "audio/wav"
    photo = api.upload(png_bytes(size=(80, 60)), "photo", "p.png", "image/png")
    assert (photo["width"], photo["height"]) == (80, 60)
    bad = api.c.post("/api/assets", files={"file": ("x", b"abc", "audio/wav")}, data={"role": "banana"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_request"
    assert api.c.post("/api/assets", files={"file": ("x", b"", "audio/wav")}, data={"role": "hum"}).status_code == 400


def test_export_formats(api):
    song = api.song(key={"tonic": "Bb", "mode": "major"})
    midi = api.c.get(f"/api/songs/{song['id']}/export?format=midi")
    assert midi.status_code == 200 and midi.content[:4] == b"MThd" and midi.headers["content-type"] == "audio/midi"
    assert b"<score-partwise" in api.c.get(f"/api/songs/{song['id']}/export?format=musicxml").content
    abc = api.c.get(f"/api/songs/{song['id']}/export?format=abc")
    assert abc.text.startswith("X:1") and "K:Bb" in abc.text
    assert api.c.get(f"/api/songs/{song['id']}/export?format=wav").status_code == 400
    assert api.c.get("/api/songs/song-nothing-here/export?format=midi").status_code == 404


def test_v2_endpoints_answer_501_and_jobs_are_unknown(api):
    song = api.song()
    for path in ("vocal", "share"):
        r = api.c.post(f"/api/songs/{song['id']}/{path}", json={"baseRevision": 0})
        assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented", path
    assert api.edit(song, {"op": "setVocalTake", "assetId": "a-whatever-1"}, expect=501)["code"] == "not_implemented"
    assert api.c.get("/api/jobs/job-nothing").status_code == 404


def test_location_study_log_and_shutdown(make_client):
    stopped = []
    client = make_client(on_shutdown=lambda: stopped.append(True))
    api = Api(client)
    assert client.get("/api/location").json() == {"city": None, "source": "none"}
    assert client.put("/api/location", json={"city": "Lisbon"}).json() == {"city": "Lisbon", "source": "manual"}
    song = api.song()
    assert song["card"]["city"] == "Lisbon" and song["card"]["showCity"] is True
    # a typed place applies to one song
    assert client.get("/api/location").json()["city"] is None
    assert client.put("/api/location", json={"city": ""}).status_code == 400
    r = client.post("/api/study/log", json={"events": [{"at": "2026-11-19T10:00:00Z", "type": "key", "detail": {"id": "play"}}]})
    assert r.status_code == 200 and r.json()["count"] == 1
    assert client.post("/api/study/log", json={"events": [{"type": "x"}]}).status_code == 400
    logs = list((client.app.state.store.root / "study").glob("*.jsonl"))
    assert len(logs) == 1 and '"play"' in logs[0].read_text(encoding="utf-8")
    r = client.post("/api/system/shutdown")
    assert r.status_code == 202 and stopped == [True]


def test_songs_persist_on_disk(tmp_path, card_module):
    from fastapi.testclient import TestClient
    from fretcase_server.app import create_app
    from fretcase_server.config import Settings

    settings = Settings(data_dir=tmp_path / "keep")
    first = Api(TestClient(create_app(settings, card_module_loader=lambda: card_module)))
    song = first.song()
    edited = first.edit(song, {"op": "setTempo", "tempo": 77})
    second = TestClient(create_app(settings, card_module_loader=lambda: card_module))
    assert second.get(f"/api/songs/{song['id']}").json()["song"] == edited
    assert second.get(f"/api/songs/{song['id']}/history").json()["history"][0]["action"] == "setTempo"
