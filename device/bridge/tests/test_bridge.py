import asyncio

import mido

from conftest import assert_all_valid, wait_for


def cc(control, value):
    return mido.Message("control_change", channel=0, control=control, value=value)


def note(n, on=True):
    return mido.Message("note_on" if on else "note_off", channel=0, note=n, velocity=100 if on else 0)


async def test_hello_then_snapshot_first(running, server):
    first = server.received[:2]
    assert [m["type"] for m in first] == ["hello", "snapshot"]
    assert [m["seq"] for m in first] == [0, 1]
    assert first[0]["payload"]["role"] == "panel"
    assert first[0]["payload"]["name"] == "bridge"
    snap = first[1]["payload"]
    assert set(snap["faders"]) == {"vocal", "melody", "guitar", "bass", "drums", "ambience"}
    assert snap["keysDown"] == []
    assert_all_valid(first)


async def test_asks_controller_for_fader_positions_on_start(running, midi, mapping):
    assert mapping.encode_dump_request() in midi.sent


async def test_platter_deltas_are_summed(running, server, midi):
    for v in (1, 1, 2):
        midi.inject(cc(16, v))
    await wait_for(lambda: server.of_type("platter.turn"))
    await asyncio.sleep(0.05)
    turns = server.of_type("platter.turn")
    assert sum(m["payload"]["delta"] for m in turns) == 4
    assert len(turns) <= 2
    assert_all_valid(server.received)


async def test_platter_back_and_forth_cancels(running, server, midi):
    midi.inject(cc(16, 2))
    midi.inject(cc(16, 126))  # -2
    midi.inject(cc(17, 1))
    await wait_for(lambda: server.of_type("knob.turn"))
    assert server.of_type("platter.turn") == []


async def test_large_platter_delta_is_split(running, server, midi):
    running.handle_midi(cc(16, 63))
    running.handle_midi(cc(16, 63))  # 126 detents in one tick
    await wait_for(lambda: sum(m["payload"]["delta"] for m in server.of_type("platter.turn")) == 126)
    deltas = [m["payload"]["delta"] for m in server.of_type("platter.turn")]
    assert max(deltas) <= 64 and len(deltas) >= 2


async def test_knobs_are_separate(running, server, midi):
    midi.inject(cc(18, 126))
    midi.inject(cc(18, 127))
    midi.inject(cc(20, 5))
    await wait_for(lambda: len(server.of_type("knob.turn")) >= 2)
    got = {m["payload"]["knob"]: m["payload"]["delta"] for m in server.of_type("knob.turn")}
    assert got == {"complexity": -3, "tempo": 5}
    assert_all_valid(server.received)


async def test_fader_filtering(running, server, midi):
    # snapshot said 0.8 for everything; 0.8 -> 0.5 is a real move
    midi.inject(cc(25, 64))
    await wait_for(lambda: server.of_type("fader.move"))
    move = server.of_type("fader.move")[-1]["payload"]
    assert move["track"] == "drums" and abs(move["value"] - 0.5039) < 1e-3
    n = len(server.of_type("fader.move"))
    midi.inject(cc(25, 65))  # a change of 0.008: below the 0.01 step
    await asyncio.sleep(0.08)
    assert len(server.of_type("fader.move")) == n
    midi.inject(cc(25, 70))
    await wait_for(lambda: len(server.of_type("fader.move")) == n + 1)
    midi.inject(cc(25, 0))  # the bottom is always reported
    await wait_for(lambda: server.of_type("fader.move")[-1]["payload"]["value"] == 0.0)
    assert_all_valid(server.received)


async def test_fader_bursts_send_latest_value(running, server, midi):
    for v in range(10, 100, 5):
        running.handle_midi(cc(21, v))
    await wait_for(lambda: server.of_type("fader.move"))
    await asyncio.sleep(0.05)
    last = server.of_type("fader.move")[-1]["payload"]
    assert abs(last["value"] - 95 / 127) < 1e-3


async def test_keys_down_up_with_times(running, server, midi):
    midi.inject(note(36))
    await asyncio.sleep(0.15)
    midi.inject(note(36, on=False))
    midi.inject(note(42))
    await wait_for(lambda: len(server.of_type("key")) == 3)
    keys = server.of_type("key")
    assert [(k["payload"]["id"], k["payload"]["action"]) for k in keys] == [
        ("capture", "down"),
        ("capture", "up"),
        ("track.guitar", "down"),
    ]
    assert keys[1]["t"] - keys[0]["t"] >= 140
    assert_all_valid(server.received)


async def test_repeated_key_down_and_stray_up_are_ignored(running, server, midi):
    midi.inject(note(37))
    midi.inject(note(37))
    midi.inject(note(38, on=False))
    midi.inject(note(37, on=False))
    await wait_for(lambda: len(server.of_type("key")) == 2)
    await asyncio.sleep(0.05)
    assert len(server.of_type("key")) == 2


async def test_seq_counts_up_without_gaps_and_t_does_not_go_back(running, server, midi):
    for i in range(5):
        midi.inject(note(36 + i))
        midi.inject(cc(17, 1))
        await asyncio.sleep(0.02)
    await wait_for(lambda: len(server.of_type("key")) == 5)
    msgs = server.sessions[0]
    assert [m["seq"] for m in msgs] == list(range(len(msgs)))
    assert_all_valid(msgs)


async def test_ring_and_key_lights_become_midi(running, server, midi, mapping):
    pixels = ["#e08a12", "#3a2a1c"] + [None] * 14
    await server.send({"v": 1, "type": "ring.set", "seq": 0, "t": 1, "payload": {"pixels": pixels, "brightness": 0.5}})
    await server.send({"v": 1, "type": "key.light", "seq": 1, "t": 2, "payload": {"id": "capture", "mode": "blink"}})
    await wait_for(lambda: mapping.encode_key_light("capture", "blink") in midi.sent)
    assert mapping.encode_ring(pixels, 0.5) in midi.sent


async def test_ring_default_brightness(running, server, midi, mapping):
    pixels = [None] * 16
    await server.send({"v": 1, "type": "ring.set", "seq": 0, "t": 1, "payload": {"pixels": pixels}})
    await wait_for(lambda: mapping.encode_ring(pixels, 0.6) in midi.sent)


async def test_invalid_incoming_messages_are_ignored(running, server, midi):
    await server.conns[-1].send("not json")
    await server.send({"v": 1, "type": "ring.set", "seq": 0, "t": 1, "payload": {"pixels": ["#fff"]}})
    await server.send({"v": 1, "type": "key.light", "seq": 1, "t": 2, "payload": {"id": "nope", "mode": "on"}})
    await server.send({"v": 2, "type": "ping", "seq": 2, "t": 2})
    before = len(midi.sent)
    await asyncio.sleep(0.1)
    assert len(midi.sent) == before
    # still alive
    midi.inject(note(36))
    await wait_for(lambda: server.of_type("key"))


async def test_answers_ping_with_pong(running, server):
    await server.send({"v": 1, "type": "ping", "seq": 5, "t": 5})
    await wait_for(lambda: server.of_type("pong"))
    assert_all_valid(server.of_type("pong"))
    assert "payload" not in server.of_type("pong")[0]


async def test_sends_pings(running, server):
    await wait_for(lambda: len(server.of_type("ping")) >= 2)
    assert_all_valid(server.of_type("ping"))


async def test_snapshot_when_the_app_arrives(running, server, midi):
    midi.inject(cc(22, 10))
    await wait_for(lambda: server.of_type("fader.move"))
    n = len(server.of_type("snapshot"))
    peer = lambda panel, app: {"v": 1, "type": "peer.status", "seq": 0, "t": 1, "payload": {"panel": panel, "app": app}}
    await server.send(peer(True, True))  # app already there: the initial snapshot covered it
    await asyncio.sleep(0.05)
    assert len(server.of_type("snapshot")) == n
    await server.send(peer(True, False))
    await server.send(peer(True, True))
    await wait_for(lambda: len(server.of_type("snapshot")) == n + 1)
    snap = server.of_type("snapshot")[-1]["payload"]
    assert abs(snap["faders"]["melody"] - 10 / 127) < 1e-3
    assert_all_valid(server.received)


async def test_snapshot_lists_keys_held(running, server, midi):
    midi.inject(note(36))
    await wait_for(lambda: server.of_type("key"))
    await server.send({"v": 1, "type": "peer.status", "seq": 0, "t": 1, "payload": {"panel": True, "app": False}})
    await server.send({"v": 1, "type": "peer.status", "seq": 1, "t": 1, "payload": {"panel": True, "app": True}})
    await wait_for(lambda: len(server.of_type("snapshot")) == 2)
    assert server.of_type("snapshot")[-1]["payload"]["keysDown"] == ["capture"]


async def test_reconnects_after_the_server_drops_the_connection(running, server, midi):
    await server.drop_connection()
    await wait_for(lambda: len(server.sessions) == 2 and len(server.sessions[1]) >= 2)
    assert [m["type"] for m in server.sessions[1][:2]] == ["hello", "snapshot"]
    assert server.sessions[1][0]["seq"] == 0
    midi.inject(note(36))
    await wait_for(lambda: any(m["type"] == "key" for m in server.sessions[1]))
    assert_all_valid(server.received)


async def test_reconnects_when_the_server_goes_silent(server, midi, mapping):
    from fretcase_bridge.bridge import Bridge

    server.answer_pings = False
    bridge = Bridge(server.url, midi, mapping, flush_interval=0.01, ping_interval=0.05,
                    link_timeout=0.2, reconnect_delays=(0.05,))  # fmt: skip
    task = asyncio.create_task(bridge.run())
    try:
        await wait_for(lambda: len(server.sessions) >= 2, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_waits_for_a_server_that_is_not_up_yet(midi, mapping):
    from conftest import FakeServer
    from fretcase_bridge.bridge import Bridge

    s = FakeServer()
    await s.start()
    port = s.port
    await s.stop()  # nobody is listening on this port now
    bridge = Bridge(f"ws://127.0.0.1:{port}/ws/panel", midi, mapping, flush_interval=0.01,
                    ping_interval=0.1, link_timeout=0.5, reconnect_delays=(0.05,))  # fmt: skip
    task = asyncio.create_task(bridge.run())
    try:
        midi.inject(note(36))  # pressed while offline: must not be sent later as a stale event
        await asyncio.sleep(0.2)
        s2 = FakeServer()
        await s2.start(port)
        try:
            await wait_for(lambda: s2.of_type("snapshot"))
            await asyncio.sleep(0.05)
            assert s2.of_type("key") == []
            assert s2.of_type("snapshot")[0]["payload"]["keysDown"] == ["capture"]
        finally:
            await s2.stop()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_lights_are_restored_when_the_controller_comes_back(running, server, midi, mapping):
    await server.send({"v": 1, "type": "key.light", "seq": 0, "t": 1, "payload": {"id": "play", "mode": "on", "color": "#ffffff"}})
    await wait_for(lambda: mapping.encode_key_light("play", "on", "#ffffff") in midi.sent)
    midi.sent.clear()
    midi.on_open()
    assert mapping.encode_dump_request() in midi.sent
    assert mapping.encode_key_light("play", "on", "#ffffff") in midi.sent


async def test_firmware_version_is_reported_in_hello(server, midi, mapping):
    from fretcase_bridge.bridge import Bridge

    bridge = Bridge(server.url, midi, mapping, flush_interval=0.01, ping_interval=0.1, link_timeout=0.5)
    midi.inject(mido.Message("sysex", data=[*mapping.sysex_prefix, mapping.sx_version, 0, 1, 7]))
    task = asyncio.create_task(bridge.run())
    try:
        await wait_for(lambda: server.of_type("hello"))
        assert server.of_type("hello")[0]["payload"]["firmware"] == "0.1.7"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
