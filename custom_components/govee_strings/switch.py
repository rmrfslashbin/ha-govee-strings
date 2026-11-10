"""'HA owns the config': re-send the known per-bulb state."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .data import GoveeConfigEntry
from .device import GoveeString
from .entity import GoveeStringEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoveeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GoveeEnforceSwitch(entry.runtime_data)])


class GoveeEnforceSwitch(GoveeStringEntity, SwitchEntity):
    """When on, HA re-sends its state on a timer, on turn-on and when the string returns.

    It never turns a string on. Changes made in the Govee app are overwritten.
    """

    _attr_translation_key = "enforce"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, string: GoveeString) -> None:
        super().__init__(string)
        self._attr_unique_id = f"{string.device_id}_enforce"

    @property
    def is_on(self) -> bool:
        return self.string.state.enforce

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.string.set_enforce(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.string.set_enforce(False)
