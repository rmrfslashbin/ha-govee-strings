"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .device import GoveeString


class GoveeStringEntity(Entity):
    """Shared device info and update wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, string: GoveeString) -> None:
        self.string = string
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, string.device_id)},
            manufacturer="Govee",
            model=string.sku,
            model_id=string.sku,
            serial_number=string.device_id,
        )

    @property
    def available(self) -> bool:
        return self.string.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.string.add_listener(self.async_write_ha_state))
