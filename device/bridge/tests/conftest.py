from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

import mido
import pytest
from websockets.asyncio.server import serve

from fretcase_bridge.bridge import Bridge
from fretcase_bridge.mapping import Mapping
from fretcase_bridge.schema import errors_for, get_validator


class FakeMidi:
    """Stands in for the controller's USB MIDI port."""

    def __init__(self) -> None:
        self.on_open = None
        self.sent: list[mido.Message] = []
        self._q: asyncio.Queue[mido.Message] = asyncio.Queue()
        self.closed = False

    async def receive(self) -> mido.Message:
        return await self._q.get()

    def inject(self, msg: mido.Message) -> None:
        self._q.put_nowait(msg)

    def send(self, msg: mido.Message) -> None:
        self.sent.append(msg)

    def close(self) -> None:
        self.closed = True


class FakeServer:
    """A WebSocket server playing the relay: records what the panel sends, can send to it."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.sessions: list[list[dict[str, Any]]] = []
        self.conns: list[Any] = []
        self.answer_pings = True
        self._server = None
        self.port = 0

    async def _handler(self, ws) -> None:
        self.conns.append(ws)
        self.sessions.append([])
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                self.sessions[-1].append(msg)
                if msg["type"] == "ping" and self.answer_pings:
                    await self.send({"v": 1, "type": "pong", "seq": 0, "t": 0})
        finally:
            pass

    async def start(self, port: int = 0) -> None:
        self._server = await serve(self._handler, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/panel"

    async def send(self, msg: dict[str, Any]) -> None:
        await self.conns[-1].send(json.dumps(msg))

    async def drop_connection(self) -> None:
        await self.conns[-1].close()

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.received if m["type"] == type_]


async def wait_for(cond: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


@pytest.fixture
def mapping() -> Mapping:
    return Mapping.default()


@pytest.fixture
async def server():
    s = FakeServer()
    await s.start()
    yield s
    await s.stop()


@pytest.fixture
def midi() -> FakeMidi:
    return FakeMidi()


@pytest.fixture
async def running(server, midi, mapping):
    """A bridge connected to the fake server, with fast timers."""
    bridge = Bridge(
        server.url,
        midi,
        mapping,
        flush_interval=0.01,
        ping_interval=0.1,
        link_timeout=0.35,
        reconnect_delays=(0.05, 0.1),
    )
    task = asyncio.create_task(bridge.run())
    await wait_for(lambda: len(server.of_type("snapshot")) >= 1 and bridge._connected)
    yield bridge
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def assert_all_valid(messages: list[dict[str, Any]]) -> None:
    v = get_validator()
    for m in messages:
        assert errors_for(m, v) == [], m
