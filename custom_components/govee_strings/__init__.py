"""The Govee Strings (LAN) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BULB_COUNT,
    CONF_DEVICE_ID,
    CONF_ENFORCE_INTERVAL,
    CONF_IP,
    CONF_SKU,
    DEFAULT_ENFORCE_INTERVAL_MIN,
    DOMAIN,
    STATUS_INTERVAL,
)
from .data import (
    GoveeConfigEntry,
    async_acquire_transport,
    async_release_transport,
    async_setup_data,
    async_start_discovery,
    get_data,
    save_string_state,
)
from .device import GoveeString, StringState
from .services import async_setup_services
from .transport import PortInUseError

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SELECT, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up shared state and actions."""
    await async_setup_data(hass)
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GoveeConfigEntry) -> bool:
    """Set up one string."""
    try:
        transport = await async_acquire_transport(hass)
    except PortInUseError as err:
        raise ConfigEntryNotReady(
            "UDP port 4002 is in use. Disable the built-in Govee lights local integration "
            f"first ({err})"
        ) from err

    data = get_data(hass)
    device_id: str = entry.data[CONF_DEVICE_ID]
    bulb_count: int = entry.options[CONF_BULB_COUNT]
    state = StringState.from_dict(data.states.get(device_id, {}), bulb_count)
    string = GoveeString(
        transport,
        device_id=device_id,
        sku=entry.data[CONF_SKU],
        ip=entry.data[CONF_IP],
        bulb_count=bulb_count,
        state=state,
        save=lambda: save_string_state(hass, string),
    )
    string.applied_options = dict(entry.options)
    entry.runtime_data = string
    data.strings[device_id] = string

    def _forget() -> None:
        data.strings.pop(device_id, None)

    entry.async_on_unload(_forget)
    entry.async_on_unload(lambda: async_release_transport(hass))

    # Never send anything to the light during setup: the per-bulb state it shows may be
    # one Robert chose by hand, which the device cannot report back.
    await string.refresh_status()

    async def _poll(_now: Any) -> None:
        if await string.refresh_status() and string.state.enforce and string.is_on:
            await string.repaint()  # it came back, e.g. after a power cut

    entry.async_on_unload(async_track_time_interval(hass, _poll, STATUS_INTERVAL))

    interval = timedelta(
        minutes=entry.options.get(CONF_ENFORCE_INTERVAL, DEFAULT_ENFORCE_INTERVAL_MIN)
    )

    async def _enforce(_now: Any) -> None:
        if string.state.enforce and string.is_on and string.available:
            await string.repaint()

    entry.async_on_unload(async_track_time_interval(hass, _enforce, interval))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    async_start_discovery(hass)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: GoveeConfigEntry) -> None:
    """Reload when a setting changes. An address change alone needs no reload."""
    if dict(entry.options) != entry.runtime_data.applied_options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GoveeConfigEntry) -> bool:
    """Unload a string."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
