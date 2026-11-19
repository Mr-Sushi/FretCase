"""Instax Wide Link: framing, image encoding and the print sequence, against a fake BLE client.

NOT TESTED ON A DEVICE. These tests check our own reading of the open protocol notes (javl/InstaxBLE).
"""

import asyncio
import io
import struct

import pytest
from fretcase_card import CardInput, Printer, PrinterError, instax, render_card
from PIL import Image


def test_packet_framing_known_bytes():
    pkt = instax.build_packet((0x00, 0x02), b"\x02")
    assert pkt == bytes.fromhex("4162 0008 0002 02 50".replace(" ", ""))
    assert sum(pkt) & 255 == 255


def test_packet_length_counts_whole_packet():
    pkt = instax.build_packet(instax.OP_DOWNLOAD_END)
    assert pkt[:2] == b"Ab" and struct.unpack(">H", pkt[2:4])[0] == len(pkt) == 7
    assert pkt[4:6] == b"\x10\x02"


def test_parse_roundtrip_and_errors():
    resp = instax.build_response((0x10, 0x01), b"\x00\x01")
    assert instax.parse_packet(resp) == ((0x10, 0x01), b"\x00\x01")
    with pytest.raises(instax.InstaxError):
        instax.parse_packet(resp[:-1] + bytes([(resp[-1] + 1) & 255]))
    with pytest.raises(instax.InstaxError):
        instax.parse_packet(instax.build_packet((0, 2)))  # wrong header direction
    with pytest.raises(instax.InstaxError):
        instax.parse_packet(b"aB")


def test_split_writes():
    parts = instax.split_writes(bytes(range(256)) * 2)
    assert all(len(p) <= 182 for p in parts) and b"".join(parts) == bytes(range(256)) * 2


def test_print_packets_layout():
    jpeg = bytes(range(256)) * 10  # 2560 bytes
    pk = instax.print_packets(jpeg, 900)
    assert pk[0][4:6] == b"\x10\x00" and pk[0][6:10] == b"\x02\x00\x00\x00"
    assert struct.unpack(">I", pk[0][10:14])[0] == len(jpeg)
    data = pk[1:-2]
    assert len(data) == 3 and all(p[4:6] == b"\x10\x01" for p in data)
    assert [struct.unpack(">I", p[6:10])[0] for p in data] == [0, 1, 2]
    assert all(len(p) == 7 + 4 + 900 for p in data)  # last chunk padded
    assert b"".join(p[10:-1] for p in data)[: len(jpeg)] == jpeg
    assert pk[-2][4:6] == b"\x10\x02" and pk[-1][4:6] == b"\x10\x80"


def test_encode_image_size_limit_and_dimensions(photo):
    out = render_card(CardInput("无题", "original", "https://x.example/s/abc", "2026.11.19", cover_path=photo))
    jpeg = instax.encode_image(out.print_png)
    assert len(jpeg) <= instax.MAX_JPEG_BYTES and jpeg[:2] == b"\xff\xd8"
    assert Image.open(io.BytesIO(jpeg)).size == (1260, 840)
    assert len(jpeg) > 0.5 * instax.MAX_JPEG_BYTES  # uses the budget, not the lowest quality


def test_encode_image_rejects_wrong_size_and_garbage():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="PNG")
    with pytest.raises(instax.InstaxError):
        instax.encode_image(buf.getvalue())
    with pytest.raises(instax.InstaxError):
        instax.encode_image(b"junk")


# ---- fake printer ----------------------------------------------------------------------------


class FakeBle:
    """Looks like bleak.BleakClient. Reassembles written parts into packets and answers each one."""

    def __init__(self, films=7, silent=False, fail_connect=False):
        self.films, self.silent, self.fail_connect = films, silent, fail_connect
        self.packets: list[bytes] = []
        self.writes: list[bytes] = []
        self.connected = False
        self._buf = b""
        self._cb = None

    async def connect(self):
        if self.fail_connect:
            raise OSError("radio off")
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def start_notify(self, uuid, cb):
        assert uuid == instax.NOTIFY_UUID
        self._cb = cb

    async def write_gatt_char(self, uuid, data, response=False):
        assert uuid == instax.WRITE_UUID and len(data) <= 182
        self.writes.append(bytes(data))
        self._buf += bytes(data)
        while len(self._buf) >= 4:
            n = struct.unpack(">H", self._buf[2:4])[0]
            if len(self._buf) < n:
                return
            pkt, self._buf = self._buf[:n], self._buf[n:]
            assert pkt[:2] == b"Ab" and sum(pkt) & 255 == 255
            self.packets.append(pkt)
            if not self.silent:
                op = (pkt[4], pkt[5])
                payload = b"\x00" + pkt[6:7]
                if op == instax.OP_SUPPORT_FUNCTION_INFO:
                    payload += bytes([self.films])
                self._cb(None, instax.build_response(op, payload))


def printer_with(fake: FakeBle, spec="instax:AA:BB:CC:DD:EE:FF") -> Printer:
    p = Printer(spec)
    p._instax_client_factory = lambda target: fake
    return p


@pytest.fixture(scope="module")
def print_png(photo):
    return render_card(CardInput("无题", "xieyi", "https://x.example/s/abc", "2026.11.19", cover_path=photo)).print_png


def test_spec_parsing():
    assert Printer("instax").address is None
    assert Printer("instax:AA:BB:CC:DD:EE:FF").address == "AA:BB:CC:DD:EE:FF"
    assert Printer("instax").kind == "instax"


def test_print_sequence_end_to_end(print_png):
    fake = FakeBle()
    printer_with(fake).print_card(print_png)
    ops = [(p[4], p[5]) for p in fake.packets]
    assert ops[0] == instax.OP_SUPPORT_FUNCTION_INFO  # film check first
    assert ops[1] == instax.OP_DOWNLOAD_START and ops[-2] == instax.OP_DOWNLOAD_END and ops[-1] == instax.OP_PRINT_IMAGE
    assert set(ops[2:-2]) == {instax.OP_DOWNLOAD_DATA}
    start = fake.packets[1]
    length = struct.unpack(">I", start[10:14])[0]
    jpeg = b"".join(p[10:-1] for p in fake.packets[2:-2])[:length]
    assert Image.open(io.BytesIO(jpeg)).size == (1260, 840) and length <= instax.MAX_JPEG_BYTES
    assert max(len(w) for w in fake.writes) <= 182
    assert not fake.connected  # always disconnects


def test_status(print_png):
    assert printer_with(FakeBle(films=5)).status() == {
        "kind": "instax", "connected": True, "paper": "ok", "remaining": 5}
    assert printer_with(FakeBle(films=0)).status()["paper"] == "out"
    assert printer_with(FakeBle(fail_connect=True)).status() == {
        "kind": "instax", "connected": False, "paper": "unknown", "remaining": None}


def test_out_of_film_and_bluetooth_errors(print_png):
    with pytest.raises(PrinterError, match="film"):
        printer_with(FakeBle(films=0)).print_card(print_png)
    with pytest.raises(PrinterError, match="Bluetooth"):
        printer_with(FakeBle(fail_connect=True)).print_card(print_png)


def test_no_reply_times_out():
    fake = FakeBle(silent=True)
    wide = instax.InstaxWide("x", client_factory=lambda t: fake, reply_timeout=0.2)
    with pytest.raises(instax.InstaxError, match="no reply"):
        wide.status()


def test_works_inside_a_running_event_loop(print_png):
    async def go():
        printer_with(FakeBle()).print_card(print_png)
    asyncio.run(go())


def test_no_printer_found_message(monkeypatch):
    import bleak

    async def none(*a, **k):
        return None
    monkeypatch.setattr(bleak.BleakScanner, "find_device_by_filter", staticmethod(none))
    with pytest.raises(PrinterError, match="no Instax printer"):
        Printer("instax").print_card(
            render_card(CardInput("无题", "text", "https://x.example/s/abc", "2026.11.19")).print_png)
