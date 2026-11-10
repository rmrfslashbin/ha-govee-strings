"""Frame-builder tests. Expected bytes are the frames verified by eye on 2026-11-09."""

import base64
import json

import pytest

from custom_components.govee_strings import protocol


def _xor(data: bytes) -> int:
    out = 0
    for byte in data:
        out ^= byte
    return out


def test_frame_is_20_bytes_with_xor_checksum() -> None:
    f = protocol.frame(bytes.fromhex("3305"))
    assert len(f) == 20
    assert f[-1] == _xor(f[:-1])


def test_bulb1_cyan_on_15_bulb_string() -> None:
    # Sauna H7025: bulb 1 turned cyan.
    expected = bytes.fromhex("3305150100ffff00000000000100").ljust(19, b"\0")
    assert protocol.color_frame((0, 255, 255), [1], 15)[:19] == expected


def test_all_45_bulbs_violet_uses_6_byte_mask() -> None:
    # Shed H7039: a 6-byte mask reached bulbs 17-45; a 2-byte mask did not.
    f = protocol.color_frame((0xC0, 0x00, 0xFF), range(1, 46), 45)
    assert f[12:18] == bytes.fromhex("ffffffffff1f")


def test_bulb_30_on_30_bulb_string() -> None:
    # Back Porch H7021: bulb 30 is bit 5 of the fourth mask byte.
    f = protocol.color_frame((0xFF, 0x00, 0xC0), [30], 30)
    assert f[12:16] == bytes.fromhex("00000020")


def test_bulb2_brightness_10() -> None:
    assert protocol.brightness_frame(10, [2], 15)[:7] == bytes.fromhex("330515020a0200")


@pytest.mark.parametrize(("count", "width"), [(1, 2), (15, 2), (16, 2), (17, 3), (30, 4), (45, 6)])
def test_mask_len(count: int, width: int) -> None:
    assert protocol.mask_len(count) == width


@pytest.mark.parametrize("bulb", [0, 16])
def test_bulb_out_of_range(bulb: int) -> None:
    with pytest.raises(ValueError):
        protocol.bulb_mask([bulb], 15)


def test_ptreal_message_round_trips() -> None:
    f = protocol.color_frame((1, 2, 3), [1], 15)
    msg = json.loads(protocol.ptreal_message([f]))
    assert msg["msg"]["cmd"] == "ptReal"
    assert base64.b64decode(msg["msg"]["data"]["command"][0]) == f
