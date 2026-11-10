"""Lights: one for the whole string, one per bulb."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import COLOR_TEMP_SKUS, MAX_KELVIN, MIN_KELVIN
from .data import GoveeConfigEntry
from .device import GoveeString, Run
from .entity import GoveeStringEntity


def to_pct(value: int) -> int:
    """HA brightness (0..255) to percent (1..100)."""
    return max(1, min(100, round(value * 100 / 255)))


def to_ha(pct: int) -> int:
    return max(1, min(255, round(pct * 255 / 100)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoveeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    string = entry.runtime_data
    entities: list[LightEntity] = [GoveeStringLight(string)]
    entities += [GoveeBulbLight(string, n) for n in range(1, string.bulb_count + 1)]
    async_add_entities(entities)


class GoveeStringLight(GoveeStringEntity, LightEntity):
    """The whole string."""

    _attr_name = None
    # Color is what HA last sent: the device's reported color goes stale.
    _attr_assumed_state = True

    def __init__(self, string: GoveeString) -> None:
        super().__init__(string)
        self._attr_unique_id = string.device_id
        if string.sku in COLOR_TEMP_SKUS:
            self._attr_supported_color_modes = {ColorMode.RGB, ColorMode.COLOR_TEMP}
            self._attr_min_color_temp_kelvin = MIN_KELVIN
            self._attr_max_color_temp_kelvin = MAX_KELVIN
        else:
            self._attr_supported_color_modes = {ColorMode.RGB}

    @property
    def is_on(self) -> bool | None:
        return self.string.is_on

    @property
    def brightness(self) -> int | None:
        return to_ha(self.string.brightness) if self.string.brightness is not None else None

    @property
    def color_mode(self) -> ColorMode:
        if self.string.color_temp_kelvin is not None:
            return ColorMode.COLOR_TEMP
        return ColorMode.RGB

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self.string.rgb

    @property
    def color_temp_kelvin(self) -> int | None:
        return self.string.color_temp_kelvin

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "bulb_count": self.string.bulb_count,
            "active_pattern": self.string.state.active_pattern,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.string.is_on:
            await self.string.set_power(True)
            if self.string.state.enforce:
                await self.string.repaint()
        if ATTR_BRIGHTNESS in kwargs:
            await self.string.set_brightness(to_pct(kwargs[ATTR_BRIGHTNESS]))
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            await self.string.set_color((int(r), int(g), int(b)))
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.string.set_color_temp(int(kwargs[ATTR_COLOR_TEMP_KELVIN]))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.string.set_power(False)


class GoveeBulbLight(GoveeStringEntity, LightEntity):
    """One bulb. "Off" paints it black, and "on" restores its color."""

    _attr_assumed_state = True
    _attr_supported_color_modes = {ColorMode.RGB}  # noqa: RUF012
    _attr_color_mode = ColorMode.RGB
    _attr_translation_key = "bulb"
    # Disabled by default: up to 56 per string, and a label-targeted automation (e.g.
    # sunset/sunrise on a device label) would otherwise fan out to every bulb. Disabled
    # entities are skipped by label and device targets. Enable them per string as needed.
    _attr_entity_registry_enabled_default = False

    def __init__(self, string: GoveeString, number: int) -> None:
        super().__init__(string)
        self.number = number
        self._attr_unique_id = f"{string.device_id}_bulb_{number}"
        self._attr_translation_placeholders = {"number": str(number)}

    @property
    def _bulb(self) -> Any:
        return self.string.state.bulbs[self.number - 1]

    @property
    def is_on(self) -> bool:
        return bool(self._bulb.on)

    @property
    def brightness(self) -> int:
        return to_ha(self._bulb.brightness)

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        rgb: tuple[int, int, int] = self._bulb.rgb
        return rgb

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb: tuple[int, int, int] | None = None
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            rgb = (int(r), int(g), int(b))
        bri = to_pct(kwargs[ATTR_BRIGHTNESS]) if ATTR_BRIGHTNESS in kwargs else None
        await self.string.paint([Run([self.number], rgb=rgb, brightness=bri, on=True)])

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.string.paint([Run([self.number], on=False)])
