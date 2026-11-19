"""Card preview and print against the card-module stub, share resolution, and the panel WebSocket relay."""
import json

import pytest

from conftest import Api, assert_valid, png_bytes
from jsonschema import Draft202012Validator

from fretcase_server.panel import SCHEMA_PATH

PANEL = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------------------------- cards


def test_preview_sets_images_and_reserves_the_share(api, card_module):
    song = api.song()
    out = api.post(song, "card/preview")
    card = out["card"]
    assert card["frontAssetId"] and card["backAssetId"]
    assert card["share"]["state"] == "reserved"
    assert card["share"]["url"] == f"https://fretcase.example/s/{card['share']['shareId']}"
    assert 10 <= len(card["share"]["shareId"]) <= 32
    roles = {a["role"] for a in out["assets"]}
    assert {"card_front", "card_back", "card_print"} <= roles
    png = api.c.get(f"/api/assets/{card['frontAssetId']}")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"
    # the same QR code on every preview of this song, and the asset list does not pile up
    again = api.post(out, "card/preview")
    assert again["card"]["share"] == card["share"]
    assert sum(1 for a in again["assets"] if a["role"] == "card_front") == 1
    assert api.c.get(f"/api/share/{card['share']['shareId']}").json() == {"songId": song["id"]}


def test_preview_is_deterministic_for_the_same_card(api):
    song = api.song()
    a = api.post(song, "card/preview")
    b = api.post(a, "card/preview")
    assert api.c.get(f"/api/assets/{a['card']['frontAssetId']}").content == api.c.get(f"/api/assets/{b['card']['frontAssetId']}").content
    assert api.c.get(f"/api/assets/{a['card']['backAssetId']}").content == api.c.get(f"/api/assets/{b['card']['backAssetId']}").content


def test_print_needs_a_preview_of_the_current_card(api, card_module):
    song = api.song()
    assert api.post(song, "card/print", expect=422)["code"] == "cannot_apply"
    previewed = api.post(song, "card/preview")
    printed = api.post(previewed, "card/print")
    assert printed["card"]["printedAt"]
    assert len(card_module.Printer.instances) == 1 and len(card_module.Printer.instances[0].printed) == 1
    assert card_module.Printer.instances[0].dry_run_dir is not None  # no printer configured: PNG files
    assert list(card_module.Printer.instances[0].dry_run_dir.glob("*.png"))
    # changing what the card shows makes the preview stale
    edited = api.edit(printed, {"op": "setCard", "line": "海风把傍晚吹进歌里"})
    assert api.post(edited, "card/print", expect=422)["code"] == "cannot_apply"
    again = api.post(edited, "card/preview")
    reprinted = api.post(again, "card/print")
    assert reprinted["card"]["printedAt"]
    # a title change counts too
    retitled = api.edit(reprinted, {"op": "setTitle", "title": "另一个名字"})
    assert api.post(retitled, "card/print", expect=422)["code"] == "cannot_apply"


def test_print_ignores_fields_that_only_appear_on_the_song_page(api):
    song = api.song()
    previewed = api.post(song, "card/preview")
    edited = api.edit(previewed, {"op": "setCard", "message": "给你的", "showPhoto": True})
    assert "frontAssetId" not in edited["card"] and "backAssetId" not in edited["card"]
    assert api.post(edited, "card/print", expect=422)["code"] == "cannot_apply"
    assert api.post(api.post(edited, "card/preview"), "card/print")["card"]["printedAt"]


def test_vocal_replace_notes_accepts_lyrics(api):
    song = api.song()
    note = {"start": 0, "duration": 480, "pitch": 70, "lyric": "海", "lineEnd": True}
    out = api.edit(song, {"op": "replaceNotes", "track": "vocal", "from": 0, "to": 480, "notes": [note]})
    assert out["tracks"]["vocal"]["notes"][0] == note
    melody_note = dict(note)
    assert api.edit(out, {"op": "replaceNotes", "track": "melody", "from": 0, "to": 480, "notes": [melody_note]}, expect=400)["code"] == "invalid_request"


def test_city_is_printed_only_when_shown(api, card_module, monkeypatch):
    seen = []
    original = card_module.render_card

    def spy(card):
        seen.append(card)
        return original(card)

    monkeypatch.setattr(card_module, "render_card", spy)
    song = api.edit(api.song(), {"op": "setCard", "city": "Lisbon", "showCity": False})
    api.post(song, "card/preview")
    assert seen[-1].city is None
    shown = api.edit(api.c.get(f"/api/songs/{song['id']}").json()["song"], {"op": "setCard", "showCity": True})
    api.post(shown, "card/preview")
    assert seen[-1].city == "Lisbon"


def test_photo_card_passes_the_photo_path_and_text_style_does_not(api, card_module, monkeypatch):
    seen = []
    original = card_module.render_card
    monkeypatch.setattr(card_module, "render_card", lambda card: (seen.append(card), original(card))[1])
    photo = api.upload(png_bytes(), "photo", "p.png", "image/png")
    seed = api.seed([{"kind": "photo", "assetId": photo["id"]}, {"kind": "text", "text": "quiet night"}])
    song = api.song(seed=seed)
    assert song["card"]["style"] == "ink" and song["card"]["photoAssetId"] == photo["id"]
    api.post(song, "card/preview")
    assert seen[-1].photo_path is not None and seen[-1].style == "ink"
    text_song = api.edit(api.c.get(f"/api/songs/{song['id']}").json()["song"], {"op": "setCard", "style": "text", "line": "一行字"})
    api.post(text_song, "card/preview")
    assert seen[-1].photo_path is None and seen[-1].line == "一行字"


def test_printer_errors_are_422_with_the_printer_detail(api, card_module):
    song = api.post(api.song(), "card/preview")
    card_module.Printer.fail_with = "no paper"
    error = api.post(song, "card/print", expect=422)
    assert error["code"] == "cannot_apply" and error["detail"]["printer"] == "no paper"
    assert "printedAt" not in api.c.get(f"/api/songs/{song['id']}").json()["song"]["card"]


def test_set_card_validation(api):
    song = api.song()
    out = api.edit(song, {"op": "setCard", "style": "comic", "city": "Newcastle upon Tyne", "showCity": True})
    assert out["card"]["style"] == "comic" and out["card"]["showCity"] is True
    cleared = api.edit(out, {"op": "setCard", "city": None})
    assert "city" not in cleared["card"]
    assert api.edit(cleared, {"op": "setCard", "style": "neon"}, expect=400)["code"] == "invalid_request"
    assert api.edit(cleared, {"op": "setCard", "photoAssetId": "a-nothing-here"}, expect=404)["code"] == "not_found"
    wav = api.upload(b"RIFF....", "hum", "h.wav", "audio/wav")
    assert api.edit(cleared, {"op": "setCard", "photoAssetId": wav["id"]}, expect=422)["code"] == "cannot_apply"


def test_card_endpoints_say_so_when_the_module_is_missing(make_client):
    def missing():
        from fretcase_server.cards import load_card_module
        import sys

        saved = sys.modules.pop("fretcase_card", None)
        sys.modules["fretcase_card"] = None  # makes the import fail
        try:
            return load_card_module()
        finally:
            sys.modules.pop("fretcase_card", None)
            if saved is not None:
                sys.modules["fretcase_card"] = saved

    api = Api(make_client(card_module_loader=missing))
    song = api.song()
    r = api.c.post(f"/api/songs/{song['id']}/card/preview", json={"baseRevision": 0})
    assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented"


def test_unknown_share_is_404(api):
    r = api.c.get("/api/share/doesNotExist1")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ----------------------------------------------------------------------------------------------- panel relay


def hello(role, name="test", seq=0):
    return {"v": 1, "type": "hello", "seq": seq, "t": 0, "payload": {"role": role, "name": name}}


def recv(ws):
    message = json.loads(ws.receive_text())
    assert list(PANEL.iter_errors(message)) == [], message
    return message


def connect(client, role):
    ws = client.websocket_connect("/ws/panel")
    ws = ws.__enter__()
    ws.send_text(json.dumps(hello(role)))
    return ws


def test_peer_status_on_connect_and_disconnect(client):
    with client.websocket_connect("/ws/panel") as panel:
        panel.send_text(json.dumps(hello("panel")))
        assert recv(panel)["payload"] == {"panel": True, "app": False}
        assert client.get("/health").json()["panel"] is True
        with client.websocket_connect("/ws/panel") as app:
            app.send_text(json.dumps(hello("app")))
            assert recv(app)["payload"] == {"panel": True, "app": True}
            assert recv(panel)["payload"] == {"panel": True, "app": True}
        status = recv(panel)
        assert status["type"] == "peer.status" and status["payload"] == {"panel": True, "app": False}
    assert client.get("/health").json()["panel"] is False


def test_messages_are_relayed_unchanged_in_both_directions(client):
    with client.websocket_connect("/ws/panel") as panel, client.websocket_connect("/ws/panel") as app:
        panel.send_text(json.dumps(hello("panel")))
        recv(panel)
        app.send_text(json.dumps(hello("app")))
        recv(app)
        recv(panel)
        turn = {"v": 1, "type": "platter.turn", "seq": 1, "t": 120, "payload": {"delta": 3}}
        panel.send_text(json.dumps(turn))
        assert recv(app) == turn
        key = {"v": 1, "type": "key", "seq": 2, "t": 130, "payload": {"id": "capture", "action": "down"}}
        panel.send_text(json.dumps(key))
        assert recv(app) == key
        snapshot = {"v": 1, "type": "snapshot", "seq": 3, "t": 140, "payload": {"faders": {t: 0.5 for t in ("vocal", "melody", "guitar", "bass", "drums", "ambience")}, "keysDown": []}}
        panel.send_text(json.dumps(snapshot))
        assert recv(app) == snapshot
        ring = {"v": 1, "type": "ring.set", "seq": 1, "t": 5, "payload": {"pixels": ["#ff8800"] + [None] * 15, "brightness": 0.5}}
        app.send_text(json.dumps(ring))
        assert recv(panel) == ring
        light = {"v": 1, "type": "key.light", "seq": 2, "t": 6, "payload": {"id": "play", "mode": "pulse", "color": "#00ff00"}}
        app.send_text(json.dumps(light))
        assert recv(panel) == light


def test_invalid_and_misdirected_messages_get_an_error_and_are_not_relayed(client):
    with client.websocket_connect("/ws/panel") as panel, client.websocket_connect("/ws/panel") as app:
        panel.send_text(json.dumps(hello("panel")))
        recv(panel)
        app.send_text(json.dumps(hello("app")))
        recv(app)
        recv(panel)
        panel.send_text("not json")
        assert recv(panel)["payload"]["code"] == "invalid_message"
        panel.send_text(json.dumps({"v": 1, "type": "platter.turn", "seq": 7, "t": 1, "payload": {"delta": 0}}))
        err = recv(panel)
        assert err["payload"]["code"] == "invalid_message" and err["payload"]["seq"] == 7
        panel.send_text(json.dumps({"v": 2, "type": "ping", "seq": 8, "t": 1}))
        assert recv(panel)["payload"]["code"] == "unsupported_version"
        panel.send_text(json.dumps({"v": 1, "type": "ring.set", "seq": 9, "t": 1, "payload": {"pixels": [None] * 16}}))
        assert recv(panel)["payload"]["code"] == "invalid_message"  # a panel may not send lights
        app.send_text(json.dumps({"v": 1, "type": "fader.move", "seq": 4, "t": 1, "payload": {"track": "drums", "value": 0.2}}))
        assert recv(app)["payload"]["code"] == "invalid_message"  # an app may not send fader moves
        app.send_text(json.dumps({"v": 1, "type": "peer.status", "seq": 5, "t": 1, "payload": {"panel": True, "app": True}}))
        assert recv(app)["payload"]["code"] == "invalid_message"  # server-only message
        # nothing reached the other side: the next relayed message is the one that is valid
        good = {"v": 1, "type": "knob.turn", "seq": 10, "t": 2, "payload": {"knob": "tempo", "delta": -2}}
        panel.send_text(json.dumps(good))
        assert recv(app) == good


def test_a_taken_role_is_refused(client):
    with client.websocket_connect("/ws/panel") as first:
        first.send_text(json.dumps(hello("panel")))
        recv(first)
        with client.websocket_connect("/ws/panel") as second:
            second.send_text(json.dumps(hello("panel", name="second")))
            assert recv(second)["payload"]["code"] == "role_taken"
        # the first one is still connected and unaffected
        first.send_text(json.dumps({"v": 1, "type": "ping", "seq": 1, "t": 1}))
        assert recv(first)["type"] == "pong"


def test_the_server_answers_ping_and_requires_hello_first(client):
    with client.websocket_connect("/ws/panel") as ws:
        ws.send_text(json.dumps({"v": 1, "type": "ping", "seq": 0, "t": 1}))
        assert recv(ws)["payload"]["code"] == "invalid_message"
        ws.send_text(json.dumps(hello("app")))
        recv(ws)
        ws.send_text(json.dumps({"v": 1, "type": "ping", "seq": 1, "t": 2}))
        pong = recv(ws)
        assert pong["type"] == "pong" and pong["seq"] >= 0


def test_a_panel_can_reconnect_after_it_drops(client):
    with client.websocket_connect("/ws/panel") as app:
        app.send_text(json.dumps(hello("app")))
        recv(app)
        with client.websocket_connect("/ws/panel") as panel:
            panel.send_text(json.dumps(hello("panel")))
            recv(panel)
            assert recv(app)["payload"]["panel"] is True
        assert recv(app)["payload"] == {"panel": False, "app": True}
        with client.websocket_connect("/ws/panel") as panel:
            panel.send_text(json.dumps(hello("panel")))
            assert recv(panel)["payload"]["panel"] is True
