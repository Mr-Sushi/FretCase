from __future__ import annotations

import asyncio

import pytest

from fretcase_bridge.bridge import Bridge
from fretcase_bridge.mapping import Mapping
from helpers import FakeMidi, FakeServer, wait_for


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
