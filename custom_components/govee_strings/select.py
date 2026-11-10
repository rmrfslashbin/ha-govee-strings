"""Saved-pattern picker. Selecting a pattern applies it, which also makes it scene-capable."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_PATTERNS_UPDATED
from .data import GoveeConfigEntry, get_data
from .device import GoveeString
from .entity import GoveeStringEntity
from .patterns import Fit
from .services import apply_pattern


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoveeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GoveePatternSelect(entry.runtime_data)])


class GoveePatternSelect(GoveeStringEntity, SelectEntity):
    """Shows the applied pattern; picking one applies it."""

    _attr_translation_key = "pattern"

    def __init__(self, string: GoveeString) -> None:
        super().__init__(string)
        self._attr_unique_id = f"{string.device_id}_pattern"

    @property
    def options(self) -> list[str]:
        return get_data(self.hass).patterns.names(self.string.bulb_count)

    @property
    def current_option(self) -> str | None:
        current = self.string.state.active_pattern
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        await apply_pattern(self.hass, self.string, option, Fit.EXACT)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _patterns_changed() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PATTERNS_UPDATED, _patterns_changed)
        )
