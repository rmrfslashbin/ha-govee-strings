"""Govee LAN frame builders for per-bulb control.

Per-bulb writes travel as raw BLE frames inside the undocumented ``ptReal`` LAN command.
Each frame is 19 bytes, zero-padded, followed by an XOR checksum of those 19 bytes.

Verified by eye on 2026-11-09 against H7021 (30 bulbs), H7025 (15) and H7039 (45):

- color:      ``33 05 15 01 RR GG BB 00 00 00 00 00 <mask>``
- brightness: ``33 05 15 02 <percent> <mask>``

``<mask>`` is a little-endian bulb bitmask, bit 0 = bulb 1. Two bytes reach only bulbs
1-16; longer strings need a wider mask (6 bytes drove all 45 bulbs on an H7039).
The device sends no acknowledgement, and ``devStatus`` color goes stale after per-bulb
writes, so callers must treat the state they sent as the state.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable

FRAME_BODY_LEN = 19
_COLOR_HEADER = bytes.fromhex("33051501")
_BRIGHTNESS_HEADER = bytes.fromhex("33051502")
_COLOR_PAD = bytes(5)
MIN_MASK_LEN = 2
MAX_COLOR_BULBS = (FRAME_BODY_LEN - len(_COLOR_HEADER) - 3 - len(_COLOR_PAD)) * 8  # 56


def mask_len(bulb_count: int) -> int:
    """Return the mask width in bytes for a string of ``bulb_count`` bulbs."""
    if bulb_count < 1:
        raise ValueError("bulb_count must be at least 1")
    return max(MIN_MASK_LEN, -(-bulb_count // 8))


def bulb_mask(bulbs: Iterable[int], bulb_count: int) -> bytes:
    """Encode 1-based bulb numbers as a little-endian bitmask sized for the string."""
    value = 0
    for bulb in bulbs:
        if not 1 <= bulb <= bulb_count:
            raise ValueError(f"bulb {bulb} is outside 1..{bulb_count}")
        value |= 1 << (bulb - 1)
    return value.to_bytes(mask_len(bulb_count), "little")


def frame(body: bytes) -> bytes:
    """Pad ``body`` to 19 bytes and append the XOR checksum."""
    if len(body) > FRAME_BODY_LEN:
        raise ValueError(f"frame body is {len(body)} bytes; the limit is {FRAME_BODY_LEN}")
    padded = body + bytes(FRAME_BODY_LEN - len(body))
    checksum = 0
    for byte in padded:
        checksum ^= byte
    return padded + bytes([checksum])


def color_frame(rgb: tuple[int, int, int], bulbs: Iterable[int], bulb_count: int) -> bytes:
    """Build a frame setting ``bulbs`` to ``rgb``."""
    if bulb_count > MAX_COLOR_BULBS:
        raise ValueError(f"a color frame can address at most {MAX_COLOR_BULBS} bulbs")
    if any(not 0 <= c <= 255 for c in rgb):
        raise ValueError("rgb components must be 0..255")
    return frame(_COLOR_HEADER + bytes(rgb) + _COLOR_PAD + bulb_mask(bulbs, bulb_count))


def brightness_frame(percent: int, bulbs: Iterable[int], bulb_count: int) -> bytes:
    """Build a frame setting ``bulbs`` to ``percent`` brightness (1..100)."""
    if not 1 <= percent <= 100:
        raise ValueError("percent must be 1..100")
    return frame(_BRIGHTNESS_HEADER + bytes([percent]) + bulb_mask(bulbs, bulb_count))


def ptreal_message(frames: Iterable[bytes]) -> bytes:
    """Wrap frames in a ``ptReal`` LAN message, ready to send to the command port."""
    commands = [base64.b64encode(f).decode("ascii") for f in frames]
    return json.dumps({"msg": {"cmd": "ptReal", "data": {"command": commands}}}).encode()
