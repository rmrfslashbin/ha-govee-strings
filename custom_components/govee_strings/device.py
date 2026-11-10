"""Model of one Govee string: what HA last sent, and how to send more.

The device cannot report per-bulb state, and its devStatus color goes stale after
per-bulb writes. So this model is the source of truth for colors. Only power and
whole-string brightness are read back from the device.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import protocol
from .const import FRAME_INTERVAL_S, STATUS_MISSES_UNAVAILABLE
from .transport import GoveeTransport

_LOGGER = logging.getLogger(__name__)

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
DEFAULT_RGB: RGB = (255, 255, 255)


@dataclass(slots=True)
class Bulb:
    """One bulb as HA last set it."""

    rgb: RGB = DEFAULT_RGB
    brightness: int = 100  # per-bulb percent, 1..100
    on: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"rgb": list(self.rgb), "brightness": self.brightness, "on": self.on}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bulb:
        r, g, b = (int(c) for c in data.get("rgb", DEFAULT_RGB))
        return cls(
            rgb=(r, g, b),
            brightness=int(data.get("brightness", 100)),
            on=bool(data.get("on", True)),
        )


@dataclass(slots=True)
class Run:
    """A paint instruction: set these bulbs' color, brightness and/or power."""

    bulbs: Sequence[int]
    rgb: RGB | None = None
    brightness: int | None = None
    on: bool | None = None


@dataclass(slots=True)
class StringState:
    """Everything persisted per string."""

    bulbs: list[Bulb] = field(default_factory=list)
    active_pattern: str | None = None
    enforce: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "bulbs": [b.as_dict() for b in self.bulbs],
            "active_pattern": self.active_pattern,
            "enforce": self.enforce,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], bulb_count: int) -> StringState:
        bulbs = [Bulb.from_dict(b) for b in data.get("bulbs", [])][:bulb_count]
        bulbs += [Bulb() for _ in range(bulb_count - len(bulbs))]
        return cls(
            bulbs=bulbs,
            active_pattern=data.get("active_pattern"),
            enforce=bool(data.get("enforce", False)),
        )


class GoveeString:
    """One string light."""

    def __init__(
        self,
        transport: GoveeTransport,
        *,
        device_id: str,
        sku: str,
        ip: str,
        bulb_count: int,
        state: StringState,
        save: Callable[[], None],
    ) -> None:
        self.transport = transport
        self.device_id = device_id
        self.sku = sku
        self.ip = ip
        self.bulb_count = bulb_count
        self.state = state
        self._save = save
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._misses = 0
        # Read back from devStatus.
        self.is_on: bool | None = None
        self.brightness: int | None = None  # whole-string percent
        self.available = True
        # Whole-string color as HA last set it (devStatus color is unreliable).
        self.rgb: RGB | None = None
        self.color_temp_kelvin: int | None = None
        self.applied_options: dict[str, Any] = {}

    # -- listeners -------------------------------------------------------------------
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _changed(self, persist: bool = True) -> None:
        if persist:
            self._save()
        for listener in list(self._listeners):
            listener()

    # -- sending ---------------------------------------------------------------------
    async def _send_frames(self, frames: Iterable[bytes]) -> None:
        async with self._lock:
            first = True
            for frame in frames:
                if not first:
                    await asyncio.sleep(FRAME_INTERVAL_S)
                first = False
                self.transport.send(self.ip, protocol.ptreal_message([frame]))

    async def _send_command(self, cmd: str, data: dict[str, Any]) -> None:
        async with self._lock:
            self.transport.send_command(self.ip, cmd, data)

    def _frames_for(self, indexes: Iterable[int], *, colors: bool, brightness: bool) -> list[bytes]:
        """Group the given bulbs (0-based) by value, one frame per distinct value."""
        by_rgb: dict[RGB, list[int]] = {}
        by_bri: dict[int, list[int]] = {}
        for i in indexes:
            bulb = self.state.bulbs[i]
            by_rgb.setdefault(bulb.rgb if bulb.on else BLACK, []).append(i + 1)
            by_bri.setdefault(bulb.brightness, []).append(i + 1)
        frames: list[bytes] = []
        if colors:
            frames += [protocol.color_frame(rgb, b, self.bulb_count) for rgb, b in by_rgb.items()]
        if brightness:
            frames += [
                protocol.brightness_frame(pct, b, self.bulb_count) for pct, b in by_bri.items()
            ]
        return frames

    # -- whole string ----------------------------------------------------------------
    async def set_power(self, on: bool) -> None:
        await self._send_command("turn", {"value": 1 if on else 0})
        self.is_on = on
        self._changed(persist=False)

    async def set_brightness(self, percent: int) -> None:
        percent = max(1, min(100, percent))
        await self._send_command("brightness", {"value": percent})
        self.brightness = percent
        self._changed(persist=False)

    async def set_color(self, rgb: RGB) -> None:
        """Whole-string color. Every bulb takes it, so per-bulb colors are replaced."""
        await self._send_command(
            "colorwc", {"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": 0}
        )
        self.rgb, self.color_temp_kelvin = rgb, None
        for bulb in self.state.bulbs:
            bulb.rgb, bulb.on = rgb, True
        self.state.active_pattern = None
        self._changed()

    async def set_color_temp(self, kelvin: int) -> None:
        await self._send_command(
            "colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": kelvin}
        )
        self.rgb, self.color_temp_kelvin = None, kelvin
        self.state.active_pattern = None
        self._changed()

    # -- per bulb --------------------------------------------------------------------
    async def paint(self, runs: Sequence[Run], *, pattern: str | None = None) -> None:
        """Apply runs to the model, then send only the frames that changed."""
        color_touched: set[int] = set()
        bri_touched: set[int] = set()
        for run in runs:
            for n in run.bulbs:
                if not 1 <= n <= self.bulb_count:
                    raise ValueError(f"bulb {n} is outside 1..{self.bulb_count}")
                bulb = self.state.bulbs[n - 1]
                if run.rgb is not None and run.rgb != bulb.rgb:
                    bulb.rgb = run.rgb
                    color_touched.add(n - 1)
                if run.on is not None and run.on != bulb.on:
                    bulb.on = run.on
                    color_touched.add(n - 1)
                if run.brightness is not None:
                    pct = max(1, min(100, run.brightness))
                    if pct != bulb.brightness:
                        bulb.brightness = pct
                        bri_touched.add(n - 1)
        frames = self._frames_for(sorted(color_touched), colors=True, brightness=False)
        frames += self._frames_for(sorted(bri_touched), colors=False, brightness=True)
        if not frames:
            return  # nothing changed: keep the active pattern and send nothing
        self.rgb = self.color_temp_kelvin = None
        self.state.active_pattern = pattern
        await self._send_frames(frames)
        self._changed()

    async def apply_bulbs(self, bulbs: Sequence[Bulb], *, pattern: str | None) -> None:
        """Replace every bulb and send the full state."""
        if len(bulbs) != self.bulb_count:
            raise ValueError(f"expected {self.bulb_count} bulbs, got {len(bulbs)}")
        self.state.bulbs = [Bulb(b.rgb, b.brightness, b.on) for b in bulbs]
        self.state.active_pattern = pattern
        self.rgb = self.color_temp_kelvin = None
        await self.repaint()
        self._changed()

    async def repaint(self) -> None:
        """Send the full per-bulb state. Used by enforce and pattern apply."""
        everything = range(self.bulb_count)
        await self._send_frames(self._frames_for(everything, colors=True, brightness=True))

    def set_enforce(self, enforce: bool) -> None:
        self.state.enforce = enforce
        self._changed()

    # -- status ----------------------------------------------------------------------
    async def refresh_status(self) -> bool:
        """Read power and brightness. Return True when the string has just come back."""
        status = await self.transport.request_status(self.ip)
        was_available = self.available
        if status is None:
            self._misses += 1
            if self._misses >= STATUS_MISSES_UNAVAILABLE and self.available:
                self.available = False
                self._changed(persist=False)
            return False
        self._misses = 0
        self.available = True
        on_off, bri = status.get("onOff"), status.get("brightness")
        self.is_on = bool(on_off) if on_off is not None else self.is_on
        self.brightness = int(bri) if isinstance(bri, int | float) else self.brightness
        self._changed(persist=False)
        return not was_available
