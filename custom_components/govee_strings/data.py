"""Integration-wide state: the shared transport, stores and background discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DEVICE_ID,
    CONF_IP,
    CONF_SKU,
    DISCOVERY_INTERVAL,
    DOMAIN,
    SCAN_ATTEMPTS,
    SCAN_WINDOW_S,
    STORAGE_KEY_STATE,
    STORAGE_VERSION,
)
from .device import GoveeString
from .patterns import PatternStore
from .transport import GoveeTransport, PortInUseError, ScanResult

CORE_DOMAIN = "govee_light_local"

_LOGGER = logging.getLogger(__name__)

type GoveeConfigEntry = ConfigEntry[GoveeString]


@dataclass
class GoveeData:
    """Everything shared across config entries."""

    transport: GoveeTransport
    patterns: PatternStore
    state_store: Store[dict[str, Any]]
    states: dict[str, Any] = field(default_factory=dict)
    refs: int = 0
    strings: dict[str, GoveeString] = field(default_factory=dict)
    _cancel_discovery: CALLBACK_TYPE | None = None


def get_data(hass: HomeAssistant) -> GoveeData:
    data: GoveeData = hass.data[DOMAIN]
    return data


async def async_setup_data(hass: HomeAssistant) -> GoveeData:
    patterns = PatternStore(hass)
    await patterns.async_load()
    state_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY_STATE)
    data = GoveeData(
        transport=GoveeTransport(hass.loop),
        patterns=patterns,
        state_store=state_store,
        states=await state_store.async_load() or {},
    )
    hass.data[DOMAIN] = data
    return data


async def async_acquire_transport(hass: HomeAssistant) -> GoveeTransport:
    """Start the transport on first use. Raises PortInUseError.

    A config flow can run before the integration's async_setup, so create the shared
    state here if it doesn't exist yet.
    """
    data = hass.data.get(DOMAIN) or await async_setup_data(hass)
    if any(
        e.state is ConfigEntryState.LOADED for e in hass.config_entries.async_entries(CORE_DOMAIN)
    ):
        raise PortInUseError(f"{CORE_DOMAIN} is loaded and holds UDP port 4002")
    await data.transport.start()
    data.refs += 1
    return data.transport


@callback
def async_release_transport(hass: HomeAssistant) -> None:
    data = get_data(hass)
    data.refs = max(0, data.refs - 1)
    if data.refs == 0:
        if data._cancel_discovery:
            data._cancel_discovery()
            data._cancel_discovery = None
        data.transport.stop()


def save_string_state(hass: HomeAssistant, string: GoveeString) -> None:
    data = get_data(hass)
    data.states[string.device_id] = string.state.as_dict()
    data.state_store.async_delay_save(lambda: data.states, 2.0)


@callback
def async_start_discovery(hass: HomeAssistant) -> None:
    """Scan periodically while any entry is loaded."""
    data = get_data(hass)
    if data._cancel_discovery is not None:
        return

    async def _scan(_now: Any = None) -> None:
        if not data.transport.running:
            return
        found = await data.transport.scan(SCAN_ATTEMPTS, SCAN_WINDOW_S)
        async_handle_scan(hass, found)

    data._cancel_discovery = async_track_time_interval(hass, _scan, DISCOVERY_INTERVAL)
    hass.async_create_background_task(_scan(), f"{DOMAIN} initial scan")


@callback
def async_handle_scan(hass: HomeAssistant, found: dict[str, ScanResult]) -> None:
    """Follow DHCP address changes and offer new strings for setup."""
    known = {e.unique_id: e for e in hass.config_entries.async_entries(DOMAIN)}
    for result in found.values():
        entry = known.get(result.device_id)
        if entry is None:
            discovery_flow.async_create_flow(
                hass,
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_DEVICE_ID: result.device_id, CONF_SKU: result.sku, CONF_IP: result.ip},
            )
        elif entry.data.get(CONF_IP) != result.ip:
            _LOGGER.info("Govee %s moved to %s", result.device_id, result.ip)
            hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_IP: result.ip})
            if (string := get_data(hass).strings.get(result.device_id)) is not None:
                string.ip = result.ip
