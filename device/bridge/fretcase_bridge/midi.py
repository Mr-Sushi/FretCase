"""MIDI port abstraction: a real mido port with re-open, and the protocol the bridge needs."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional, Protocol

import mido

log = logging.getLogger("fretcase.bridge.midi")

DEFAULT_PORT_HINTS = ("FretCase", "Teensy", "Pico")


class MidiPort(Protocol):
    """What the bridge needs from a MIDI connection to the controller."""

    on_open: Optional[Callable[[], None]]

    async def receive(self) -> mido.Message:
        """Wait for the next message from the controller."""

    def send(self, msg: mido.Message) -> None:
        """Send to the controller; silently dropped while the controller is not connected."""

    def close(self) -> None: ...


def find_port(names: list[str], hints: tuple[str, ...]) -> Optional[str]:
    """First port whose name contains a hint (case-insensitive); hints are tried in order."""
    for hint in hints:
        for name in names:
            if hint.lower() in name.lower():
                return name
    return None


class MidoPort:
    """A USB MIDI controller opened with mido (python-rtmidi backend).

    If the controller is not there, or is unplugged, the port is opened again as soon as it
    shows up. ``on_open`` is called after every successful open.
    """

    def __init__(self, hints: tuple[str, ...] = DEFAULT_PORT_HINTS, poll_seconds: float = 2.0):
        self.hints = hints
        self.poll_seconds = poll_seconds
        self.on_open: Optional[Callable[[], None]] = None
        self._in: Optional[mido.ports.BaseInput] = None
        self._out: Optional[mido.ports.BaseOutput] = None
        self._name: Optional[str] = None
        self._queue: asyncio.Queue[mido.Message] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # called from the rtmidi thread
    def _callback(self, msg: mido.Message) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._queue.put_nowait, msg)

    def _try_open(self) -> bool:
        try:
            in_names = mido.get_input_names()
        except Exception as e:  # no backend installed, or the MIDI subsystem is not available
            log.warning("cannot list MIDI ports: %s", e)
            return False
        name = find_port(in_names, self.hints)
        if name is None:
            return False
        try:
            self._in = mido.open_input(name, callback=self._callback)
            out_name = find_port(mido.get_output_names(), (name.rsplit(" ", 1)[0], *self.hints))
            self._out = mido.open_output(out_name) if out_name else None
        except Exception as e:
            log.warning("cannot open MIDI port %r: %s", name, e)
            self.close()
            return False
        self._name = name
        log.info("MIDI controller connected: %s", name)
        if self.on_open:
            self.on_open()
        return True

    def _still_there(self) -> bool:
        try:
            return self._name in mido.get_input_names()
        except Exception:
            return False

    async def receive(self) -> mido.Message:
        self._loop = asyncio.get_running_loop()
        while True:
            if self._in is None:
                if not self._try_open():
                    await asyncio.sleep(self.poll_seconds)
                    continue
            try:
                return await asyncio.wait_for(self._queue.get(), self.poll_seconds)
            except asyncio.TimeoutError:
                if not self._still_there():
                    log.warning("MIDI controller disconnected")
                    self.close()

    def send(self, msg: mido.Message) -> None:
        if self._out is None:
            return
        try:
            self._out.send(msg)
        except Exception as e:
            log.warning("MIDI send failed: %s", e)

    def close(self) -> None:
        for port in (self._in, self._out):
            if port is not None:
                try:
                    port.close()
                except Exception:
                    pass
        self._in = None
        self._out = None
        self._name = None
