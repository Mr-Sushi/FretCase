import json

import mido
import pytest

from fretcase_bridge.mapping import (
    FaderValue,
    FirmwareVersion,
    KeyChange,
    KnobTurn,
    Mapping,
    MappingError,
    PlatterTurn,
    decode_relative,
)


def cc(control, value, channel=0):
    return mido.Message("control_change", channel=channel, control=control, value=value)


def test_relative_two_complement():
    assert [decode_relative(v) for v in (1, 2, 63, 127, 126, 65, 0, 64)] == [1, 2, 63, -1, -2, -63, 0, -64]


def test_platter_and_knobs(mapping):
    assert mapping.decode(cc(16, 3)) == PlatterTurn(3)
    assert mapping.decode(cc(16, 127)) == PlatterTurn(-1)
    assert mapping.decode(cc(16, 0)) is None
    assert mapping.decode(cc(18, 126)) == KnobTurn("complexity", -2)
    assert mapping.decode(cc(17, 1)) == KnobTurn("brightness", 1)
    assert mapping.decode(cc(19, 1)) == KnobTurn("density", 1)
    assert mapping.decode(cc(20, 1)) == KnobTurn("tempo", 1)


def test_faders(mapping):
    assert mapping.decode(cc(21, 0)) == FaderValue("vocal", 0.0)
    assert mapping.decode(cc(26, 127)) == FaderValue("ambience", 1.0)
    assert mapping.decode(cc(24, 64)) == FaderValue("bass", round(64 / 127, 4))


def test_keys(mapping):
    on = mido.Message("note_on", channel=0, note=36, velocity=100)
    off = mido.Message("note_off", channel=0, note=36)
    zero = mido.Message("note_on", channel=0, note=36, velocity=0)
    assert mapping.decode(on) == KeyChange("capture", "down")
    assert mapping.decode(off) == KeyChange("capture", "up")
    assert mapping.decode(zero) == KeyChange("capture", "up")
    assert mapping.decode(mido.Message("note_on", channel=0, note=45, velocity=1)) == KeyChange(
        "track.ambience", "down"
    )


def test_ignores_other_channels_and_unknown(mapping):
    assert mapping.decode(cc(16, 3, channel=1)) is None
    assert mapping.decode(cc(99, 3)) is None
    assert mapping.decode(mido.Message("note_on", channel=0, note=10, velocity=1)) is None
    assert mapping.decode(mido.Message("note_on", channel=3, note=36, velocity=1)) is None
    assert mapping.decode(mido.Message("pitchwheel", channel=0, pitch=5)) is None


def test_every_control_is_mapped(mapping):
    assert len({*mapping.knob_cc.values(), *mapping.fader_cc.values(), mapping.platter_cc}) == 11
    assert set(mapping.key_note) == {
        "capture", "play", "undo", "another", "track.vocal", "track.melody",
        "track.guitar", "track.bass", "track.drums", "track.ambience",
    }  # fmt: skip


def test_firmware_version(mapping):
    msg = mido.Message("sysex", data=[*mapping.sysex_prefix, mapping.sx_version, 0, 1, 2])
    assert mapping.decode(msg) == FirmwareVersion("0.1.2")


def test_encode_ring(mapping):
    pixels = ["#ffffff", "#000000", None] + [None] * 13
    msg = mapping.encode_ring(pixels, 0.5)
    d = msg.data
    assert list(d[:3]) == [125, 70, 67]
    assert d[3] == mapping.sx_ring
    assert d[4] == round(0.5 * 127)
    assert len(d) == 3 + 1 + 1 + 16 * 3
    assert list(d[5:8]) == [127, 127, 127]
    assert list(d[8:14]) == [0] * 6
    assert all(0 <= b <= 127 for b in d)
    with pytest.raises(ValueError):
        mapping.encode_ring(["#ffffff"])


def test_encode_key_light(mapping):
    msg = mapping.encode_key_light("play", "blink", "#e2725b")
    d = list(msg.data)
    assert d[:4] == [125, 70, 67, mapping.sx_key_light]
    assert d[4:7] == [37, 2, 1]
    assert d[7:] == [round(0xE2 * 127 / 255), round(0x72 * 127 / 255), round(0x5B * 127 / 255)]
    d = list(mapping.encode_key_light("capture", "off").data)
    assert d[6] == 0 and d[7:] == [0, 0, 0]
    assert list(mapping.encode_dump_request().data) == [125, 70, 67, mapping.sx_dump_request]


def test_bad_mapping_files(tmp_path):
    from importlib import resources

    base = json.loads(resources.files("fretcase_bridge").joinpath("mapping.default.json").read_text())
    dup = json.loads(json.dumps(base))
    dup["knobs"]["tempo"] = dup["platter"]["cc"]
    with pytest.raises(MappingError):
        Mapping(dup)
    big = json.loads(json.dumps(base))
    big["keys"]["play"] = 200
    with pytest.raises(MappingError):
        Mapping(big)
    missing = json.loads(json.dumps(base))
    del missing["faders"]["bass"]
    with pytest.raises(MappingError):
        Mapping(missing)
    p = tmp_path / "m.json"
    p.write_text(json.dumps(base))
    assert Mapping.load(p).platter_cc == 16
