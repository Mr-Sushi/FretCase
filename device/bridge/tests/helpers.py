from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

import mido
from websockets.asyncio.server import serve

from fretcase_bridge.mapping import Mapping
from fretcase_bridge.schema import errors_for, get_validator


class FakeMidi:
    """Stands in for the controller's USB MIDI port.

    Like the firmware, it answers a fader dump request with one CC per fader, unless
    ``answer_dump`` is False.
    """

    FADER_CCS = (21, 22, 23, 24, 25, 26)

    def __init__(self, answer_dump: bool = True, fader_value: int = 102) -> None:
        self.on_open = None
        self.sent: list[mido.Message] = []
        self._q: asyncio.Queue[mido.Message] = asyncio.Queue()
        self.closed = False
        self.answer_dump = answer_dump
        self.fader_value = fader_value

    async def receive(self) -> mido.Message:
        return await self._q.get()

    def inject(self, msg: mido.Message) -> None:
        self._q.put_nowait(msg)

    def send(self, msg: mido.Message) -> None:
        self.sent.append(msg)
        if self.answer_dump and msg == Mapping.default().encode_dump_request():
            for cc in self.FADER_CCS:
                self.inject(mido.Message("control_change", control=cc, value=self.fader_value))

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


def assert_all_valid(messages: list[dict[str, Any]]) -> None:
    v = get_validator()
    for m in messages:
        assert errors_for(m, v) == [], m
