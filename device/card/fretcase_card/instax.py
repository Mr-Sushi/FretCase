"""Instax Wide Link over Bluetooth LE: packet framing, image encoding and a small client.

The protocol is the one documented by the open-source project javl/InstaxBLE
(https://github.com/javl/InstaxBLE, MIT licence). This module is a clean reimplementation written
from that project's protocol notes; no source code was copied. The MIT licence would allow
copying with the copyright notice kept, but nothing here needs it.

UNTESTED ON A DEVICE. There is no printer in the development environment. The packet framing,
image encoding and the print sequence are tested against a fake BLE client only. Values that
come from memory of the open notes and could not be confirmed here are marked ASSUMED; check
them on a real Wide Link before trusting a print.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import threading
from collections.abc import Callable
from typing import Any

from PIL import Image

log = logging.getLogger("fretcase.card.instax")

SERVICE_UUID = "70954782-2d83-473d-9e5f-81e1d02d5273"
WRITE_UUID = "70954783-2d83-473d-9e5f-81e1d02d5273"
NOTIFY_UUID = "70954784-2d83-473d-9e5f-81e1d02d5273"

HEADER_TO_PRINTER = b"\x41\x62"  # "Ab"
HEADER_FROM_PRINTER = b"\x61\x62"  # "aB"
BLE_WRITE_SIZE = 182  # a packet is written in parts of at most this many bytes
IMAGE_SIZE = (1260, 840)  # Instax Wide
MAX_JPEG_BYTES = 105 * 1024
# ASSUMED: bytes of image data per DOWNLOAD_DATA packet for the Wide. The open notes keep this
# in a per-model table that could not be read here; override with FRETCASE_INSTAX_CHUNK.
DEFAULT_CHUNK = 900
NAME_PREFIX = "INSTAX-"

# Opcodes (two bytes)
OP_SUPPORT_FUNCTION_INFO = (0x00, 0x02)
OP_DOWNLOAD_START = (0x10, 0x00)
OP_DOWNLOAD_DATA = (0x10, 0x01)
OP_DOWNLOAD_END = (0x10, 0x02)
OP_PRINT_IMAGE = (0x10, 0x80)

INFO_IMAGE_SUPPORT = 0x00
INFO_BATTERY = 0x01
INFO_PRINTER_FUNCTION = 0x02


class InstaxError(Exception):
    """Anything that goes wrong talking to the printer (the Printer wraps it in PrinterError)."""


# ---- framing ---------------------------------------------------------------------------------


def checksum(data: bytes) -> int:
    return (255 - (sum(data) & 255)) & 255


def build_packet(opcode: tuple[int, int], payload: bytes = b"") -> bytes:
    """``Ab`` + big-endian total length (7 + payload) + opcode + payload + checksum."""
    body = HEADER_TO_PRINTER + struct.pack(">H", 7 + len(payload)) + bytes(opcode) + payload
    return body + bytes([checksum(body)])


def parse_packet(data: bytes) -> tuple[tuple[int, int], bytes]:
    """Check a packet from the printer (``aB`` header, length, checksum). Returns (opcode, payload
    without the checksum). Raises InstaxError."""
    if len(data) < 8 or data[:2] != HEADER_FROM_PRINTER:
        raise InstaxError(f"not a printer packet: {data[:8].hex()}")
    (length,) = struct.unpack(">H", data[2:4])
    if length != len(data):
        raise InstaxError(f"length field {length} does not match packet size {len(data)}")
    if sum(data) & 255 != 255:
        raise InstaxError("bad checksum in printer packet")
    return (data[4], data[5]), data[6:-1]


def split_writes(packet: bytes, size: int = BLE_WRITE_SIZE) -> list[bytes]:
    return [packet[i:i + size] for i in range(0, len(packet), size)]


def build_response(opcode: tuple[int, int], payload: bytes = b"") -> bytes:
    """A packet as the printer sends it (used by tests and the fake printer)."""
    body = HEADER_FROM_PRINTER + struct.pack(">H", 7 + len(payload)) + bytes(opcode) + payload
    return body + bytes([checksum(body)])


# ---- image -----------------------------------------------------------------------------------


def encode_image(png_bytes: bytes, max_bytes: int = MAX_JPEG_BYTES) -> bytes:
    """PNG (or any image) -> 1260 x 840 JPEG of at most ``max_bytes``, at the highest quality that
    fits (binary search on quality). Raises InstaxError if the image cannot be used."""
    try:
        im = Image.open(io.BytesIO(png_bytes))
        im.load()
    except Exception as e:
        raise InstaxError(f"not a valid image: {e}") from e
    im = im.convert("RGB")
    if im.size != IMAGE_SIZE:
        raise InstaxError(f"image must be {IMAGE_SIZE[0]}x{IMAGE_SIZE[1]}, got {im.size[0]}x{im.size[1]}")

    def enc(q: int) -> bytes:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True, subsampling=0 if q >= 90 else 2)
        return buf.getvalue()

    lo, hi, best = 1, 95, None
    while lo <= hi:
        mid = (lo + hi) // 2
        data = enc(mid)
        if len(data) <= max_bytes:
            best, lo = data, mid + 1
        else:
            hi = mid - 1
    if best is None:
        raise InstaxError("image cannot be compressed under the printer's size limit")
    return best


def print_packets(jpeg: bytes, chunk_size: int = DEFAULT_CHUNK) -> list[bytes]:
    """The packets of one print: START (02 00 00 00 + length), DATA (index + zero-padded chunk)
    for every chunk, END, then PRINT_IMAGE."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    packets = [build_packet(OP_DOWNLOAD_START, b"\x02\x00\x00\x00" + struct.pack(">I", len(jpeg)))]
    for i in range(0, len(jpeg), chunk_size):
        chunk = jpeg[i:i + chunk_size].ljust(chunk_size, b"\x00")
        packets.append(build_packet(OP_DOWNLOAD_DATA, struct.pack(">I", i // chunk_size) + chunk))
    packets.append(build_packet(OP_DOWNLOAD_END))
    packets.append(build_packet(OP_PRINT_IMAGE))
    return packets


def info_request(info_type: int) -> bytes:
    return build_packet(OP_SUPPORT_FUNCTION_INFO, bytes([info_type]))


def parse_function_info(packet: bytes) -> tuple[int, bool]:
    """(photos left, charging) from a PRINTER_FUNCTION_INFO reply: byte 8, low 4 bits and bit 7."""
    if len(packet) < 10:
        raise InstaxError("short function-info reply")
    return packet[8] & 15, bool(packet[8] & 0x80)


# ---- client ----------------------------------------------------------------------------------


class InstaxWide:
    """Prints to, and asks about, one Instax Wide Link.

    ``client_factory(address_or_device)`` returns an object shaped like ``bleak.BleakClient``:
    ``connect()``, ``disconnect()``, ``start_notify(uuid, callback)``,
    ``write_gatt_char(uuid, data, response=...)``, all async. Tests pass a fake one.
    ``address`` None means: scan for a device whose name starts with ``INSTAX-``.
    """

    def __init__(self, address: str | None = None, client_factory: Callable[[Any], Any] | None = None,
                 scan_timeout: float = 10.0, reply_timeout: float = 15.0, chunk_size: int | None = None):
        self.address = address
        self._factory = client_factory
        self.scan_timeout = scan_timeout
        self.reply_timeout = reply_timeout
        self.chunk_size = chunk_size or int(os.environ.get("FRETCASE_INSTAX_CHUNK", DEFAULT_CHUNK))

    # -- plumbing
    async def _find(self) -> Any:
        if self._factory is not None:  # tests: no scanning
            return self.address or "fake-instax"
        try:
            from bleak import BleakScanner
        except ImportError as e:  # pragma: no cover
            raise InstaxError("bleak is not installed (pip install bleak)") from e
        if self.address:
            dev = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout)
        else:
            dev = await BleakScanner.find_device_by_filter(
                lambda d, adv: bool(d.name) and d.name.startswith(NAME_PREFIX), timeout=self.scan_timeout)
        if dev is None:
            raise InstaxError("no Instax printer found over Bluetooth (is it switched on and in range?)")
        return dev

    async def _session(self, work):
        target = await self._find()
        if self._factory is not None:
            client = self._factory(target)
        else:  # pragma: no cover - needs bleak and a radio
            from bleak import BleakClient
            client = BleakClient(target, timeout=self.scan_timeout)
        replies: asyncio.Queue = asyncio.Queue()

        def on_notify(_sender, data):
            replies.put_nowait(bytes(data))

        try:
            await asyncio.wait_for(client.connect(), self.scan_timeout)
            await client.start_notify(NOTIFY_UUID, on_notify)
            return await work(client, replies)
        except InstaxError:
            raise
        except TimeoutError as e:
            raise InstaxError("the printer did not answer in time") from e
        except Exception as e:
            raise InstaxError(f"Bluetooth error: {e}") from e
        finally:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
            except Exception:
                pass

    async def _send(self, client, replies: asyncio.Queue, packet: bytes) -> bytes:
        for part in split_writes(packet):
            await client.write_gatt_char(WRITE_UUID, part, response=False)
        opcode = (packet[4], packet[5])
        while True:
            try:
                data = await asyncio.wait_for(replies.get(), self.reply_timeout)
            except TimeoutError as e:
                raise InstaxError(f"no reply to opcode {opcode[0]:02x}{opcode[1]:02x}") from e
            got, _ = parse_packet(data)
            if got == opcode:
                return data

    # -- operations
    async def _status(self) -> dict:
        async def work(client, replies):
            data = await self._send(client, replies, info_request(INFO_PRINTER_FUNCTION))
            left, charging = parse_function_info(data)
            return {"remaining": left, "charging": charging}
        return await self._session(work)

    async def _print(self, jpeg: bytes) -> None:
        async def work(client, replies):
            info = await self._send(client, replies, info_request(INFO_PRINTER_FUNCTION))
            if parse_function_info(info)[0] == 0:
                raise InstaxError("out of film")
            for packet in print_packets(jpeg, self.chunk_size):
                await self._send(client, replies, packet)
        await self._session(work)

    def status(self) -> dict:
        return _run(self._status())

    def print_image(self, png_bytes: bytes) -> None:
        _run(self._print(encode_image(png_bytes)))


def _run(coro):
    """Run a coroutine to completion from sync code, even if this thread already has a loop."""
    result: dict = {}

    def target():
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            result["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result["value"]
