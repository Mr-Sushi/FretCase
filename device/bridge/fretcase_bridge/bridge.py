"""The panel bridge: turns controller MIDI into panel messages and lights back into MIDI."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl as ssl_module
import time
from typing import Any, Callable, Optional

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from . import __version__
from .mapping import (
    TRACKS,
    FaderValue,
    FirmwareVersion,
    KeyChange,
    KnobTurn,
    Mapping,
    PlatterTurn,
)
from .midi import MidiPort
from .schema import errors_for, get_validator

log = logging.getLogger("fretcase.bridge")

MAX_PLATTER_DELTA = 64
MAX_KNOB_DELTA = 32
FADER_MIN_STEP = 0.01


class LinkDown(Exception):
    """Nothing was heard from the app side within the timeout."""


class Bridge:
    def __init__(
        self,
        url: str,
        midi: MidiPort,
        mapping: Mapping | None = None,
        *,
        ssl: ssl_module.SSLContext | None = None,
        name: str = "bridge",
        flush_interval: float = 0.02,
        ping_interval: float = 2.0,
        link_timeout: float = 5.0,
        reconnect_delays: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0),
        clock: Callable[[], float] = time.monotonic,
    ):
        self.url = url
        self.midi = midi
        self.mapping = mapping or Mapping.default()
        self.ssl = ssl
        self.name = name
        self.flush_interval = flush_interval
        self.ping_interval = ping_interval
        self.link_timeout = link_timeout
        self.reconnect_delays = reconnect_delays
        self._clock = clock
        self._t0 = clock()
        self._validator = get_validator()

        # Controller state, kept even while the link is down so a snapshot is always possible.
        self.faders: dict[str, float] = {t: self.mapping.fader_default for t in TRACKS}
        # Faders whose real position the controller has reported. The app takes fader
        # positions from the snapshot as truth, so no snapshot goes out until all are known.
        self.faders_known: set[str] = set()
        self._snapshot_waiting = False
        self.keys_down: set[str] = set()
        self.firmware: Optional[str] = None
        self.ring_cache: Optional[tuple[list[Optional[str]], float]] = None
        self.light_cache: dict[str, tuple[str, Optional[str]]] = {}

        # Pending coalesced events (only filled while connected).
        self._platter = 0
        self._knobs: dict[str, int] = {}
        self._fader_pending: dict[str, float] = {}
        self._fader_sent: dict[str, float] = {}

        self._connected = False
        self._seq = 0
        self._send_lock = asyncio.Lock()
        self._out: asyncio.Queue[tuple[str, Any, int]] = asyncio.Queue()
        self._last_rx = 0.0
        self._app_present: Optional[bool] = None
        self.dropped_invalid = 0
        self.connect_count = 0

    # ---- time and sequence ----------------------------------------------------------------

    def now_ms(self) -> int:
        return max(0, int((self._clock() - self._t0) * 1000))

    # ---- controller side ------------------------------------------------------------------

    def handle_midi(self, msg) -> None:
        """Handle one message from the controller. Safe to call from the event loop only."""
        event = self.mapping.decode(msg)
        if event is None:
            return
        if isinstance(event, FirmwareVersion):
            self.firmware = event.version
            return
        if isinstance(event, FaderValue):
            self.faders[event.track] = event.value
            self.faders_known.add(event.track)
            if self._connected and self._snapshot_waiting and self.all_faders_known():
                self._snapshot_waiting = False
                self._out.put_nowait(("snapshot", self.snapshot_payload(), self.now_ms()))
                self._fader_sent = dict(self.faders)
            elif self._connected:
                self._fader_pending[event.track] = event.value
        elif isinstance(event, KeyChange):
            was_down = event.id in self.keys_down
            if event.action == "down":
                self.keys_down.add(event.id)
            else:
                self.keys_down.discard(event.id)
            # Ignore repeated downs and ups without a down (e.g. after a controller reset).
            if (event.action == "down") == was_down:
                return
            if self._connected:
                self._out.put_nowait(("key", {"id": event.id, "action": event.action}, self.now_ms()))
        elif isinstance(event, PlatterTurn):
            if self._connected:
                self._platter += event.delta
        elif isinstance(event, KnobTurn):
            if self._connected:
                self._knobs[event.knob] = self._knobs.get(event.knob, 0) + event.delta

    def midi_opened(self) -> None:
        """The controller (re)appeared: ask for fader positions and restore the lights."""
        self.midi.send(self.mapping.encode_dump_request())
        if self.ring_cache is not None:
            self.midi.send(self.mapping.encode_ring(*self.ring_cache))
        for key, (mode, color) in self.light_cache.items():
            self.midi.send(self.mapping.encode_key_light(key, mode, color))

    async def _midi_loop(self) -> None:
        while True:
            self.handle_midi(await self.midi.receive())

    # ---- coalescing -----------------------------------------------------------------------

    def _drain_coalesced(self) -> list[tuple[str, Any, int]]:
        """Messages for the events gathered since the last tick."""
        t = self.now_ms()
        out: list[tuple[str, Any, int]] = []
        if self._platter:
            step = max(-MAX_PLATTER_DELTA, min(MAX_PLATTER_DELTA, self._platter))
            self._platter -= step
            out.append(("platter.turn", {"delta": step}, t))
        for knob in list(self._knobs):
            total = self._knobs[knob]
            step = max(-MAX_KNOB_DELTA, min(MAX_KNOB_DELTA, total))
            if total == step:
                del self._knobs[knob]
            else:
                self._knobs[knob] = total - step
            if step:
                out.append(("knob.turn", {"knob": knob, "delta": step}, t))
        for track in list(self._fader_pending):
            value = self._fader_pending[track]
            last = self._fader_sent.get(track)
            at_end = value in (0.0, 1.0) and value != last
            if last is None or abs(value - last) >= FADER_MIN_STEP or at_end:
                self._fader_sent[track] = value
                del self._fader_pending[track]
                out.append(("fader.move", {"track": track, "value": value}, t))
        return out

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            for item in self._drain_coalesced():
                self._out.put_nowait(item)

    async def _send_loop(self, ws) -> None:
        while True:
            type_, payload, t = await self._out.get()
            await self._send(ws, type_, payload, t)

    # ---- messages -------------------------------------------------------------------------

    async def _send(self, ws, type_: str, payload: Any = None, t: int | None = None) -> bool:
        async with self._send_lock:
            msg: dict[str, Any] = {
                "v": 1,
                "type": type_,
                "seq": self._seq,
                "t": self.now_ms() if t is None else t,
            }
            if payload is not None:
                msg["payload"] = payload
            problems = errors_for(msg, self._validator)
            if problems:
                # A bug on our side. Never put an invalid message on the wire.
                self.dropped_invalid += 1
                log.error("not sending invalid %s message: %s", type_, "; ".join(problems))
                return False
            self._seq += 1
            await ws.send(json.dumps(msg, separators=(",", ":")))
            return True

    def all_faders_known(self) -> bool:
        return len(self.faders_known) == len(TRACKS)

    async def _send_snapshot_if_known(self, ws) -> None:
        """Send a snapshot now, or as soon as the controller has reported every fader."""
        if self.all_faders_known():
            self._snapshot_waiting = False
            await self._send(ws, "snapshot", self.snapshot_payload())
            # The snapshot is what the app now knows; later fader moves are relative to it.
            self._fader_sent = dict(self.faders)
        else:
            self._snapshot_waiting = True
            self._fader_sent = {t: self.faders[t] for t in self.faders_known}

    def snapshot_payload(self) -> dict[str, Any]:
        return {
            "faders": {t: self.faders[t] for t in TRACKS},
            "keysDown": sorted(self.keys_down),
        }

    async def _send_hello_and_snapshot(self, ws) -> None:
        hello: dict[str, Any] = {"role": "panel", "name": self.name}
        hello["firmware"] = self.firmware or f"bridge-{__version__}"
        await self._send(ws, "hello", hello)
        await self._send_snapshot_if_known(ws)

    async def _handle_incoming(self, ws, raw: str | bytes) -> None:
        self._last_rx = self._clock()
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("ignoring a frame that is not JSON")
            return
        problems = errors_for(msg, self._validator)
        if problems:
            log.warning("ignoring invalid message: %s", "; ".join(problems))
            return
        type_ = msg["type"]
        payload = msg.get("payload", {})
        if type_ == "ping":
            await self._send(ws, "pong")
        elif type_ == "ring.set":
            self.ring_cache = (payload["pixels"], payload.get("brightness", 0.6))
            self.midi.send(self.mapping.encode_ring(*self.ring_cache))
        elif type_ == "key.light":
            self.light_cache[payload["id"]] = (payload["mode"], payload.get("color"))
            self.midi.send(
                self.mapping.encode_key_light(payload["id"], payload["mode"], payload.get("color"))
            )
        elif type_ == "peer.status":
            app = payload["app"]
            if app and self._app_present is False:
                await self._send_snapshot_if_known(ws)
            self._app_present = app
        elif type_ == "error":
            log.warning("server error: %s %s", payload.get("code"), payload.get("message"))
        # pong, hello and panel-bound messages need no action.

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            await self._handle_incoming(ws, raw)

    async def _ping_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(self.ping_interval)
            if self._clock() - self._last_rx > self.link_timeout:
                raise LinkDown("no reply within %.1f s" % self.link_timeout)
            await self._send(ws, "ping")

    # ---- connection -----------------------------------------------------------------------

    async def _session(self, ws) -> None:
        self._seq = 0
        self._last_rx = self._clock()
        self._app_present = None
        self._platter = 0
        self._knobs.clear()
        self._fader_pending.clear()
        while not self._out.empty():
            self._out.get_nowait()
        await self._send_hello_and_snapshot(ws)
        self._connected = True
        tasks = [
            asyncio.create_task(self._recv_loop(ws)),
            asyncio.create_task(self._ping_loop(ws)),
            asyncio.create_task(self._send_loop(ws)),
            asyncio.create_task(self._flush_loop()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()  # re-raise
        finally:
            self._connected = False
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _connection_loop(self) -> None:
        failures = 0
        while True:
            try:
                async with connect(
                    self.url,
                    ssl=self.ssl,
                    open_timeout=5,
                    close_timeout=2,
                    ping_interval=None,  # we use the protocol's own ping message
                ) as ws:
                    self.connect_count += 1
                    failures = 0
                    log.info("connected to %s", self.url)
                    await self._session(ws)
                    log.info("connection closed")
            except (OSError, WebSocketException, asyncio.TimeoutError, LinkDown) as e:
                log.warning("panel link down: %s", e)
            delay = self.reconnect_delays[min(failures, len(self.reconnect_delays) - 1)]
            failures += 1
            await asyncio.sleep(delay)

    async def run(self) -> None:
        self.midi.on_open = self.midi_opened
        self.midi_opened()  # for a port that is already open; a no-op on a closed MidoPort
        midi_task = asyncio.create_task(self._midi_loop())
        try:
            await self._connection_loop()
        finally:
            midi_task.cancel()
            await asyncio.gather(midi_task, return_exceptions=True)
            self.midi.close()
