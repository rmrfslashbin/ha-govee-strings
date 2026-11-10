"""Config flow: one entry per string, each with its bulb count."""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BULB_COUNT,
    CONF_DEVICE_ID,
    CONF_ENFORCE_INTERVAL,
    CONF_IP,
    CONF_SKU,
    DEFAULT_ENFORCE_INTERVAL_MIN,
    DOMAIN,
    MAX_BULBS,
    SCAN_ATTEMPTS,
    SCAN_WINDOW_S,
)
from .data import GoveeConfigEntry, async_acquire_transport, async_release_transport
from .transport import PortInUseError, ScanResult

MANUAL = "manual"

BULB_COUNT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1, max=MAX_BULBS, step=1, mode=selector.NumberSelectorMode.BOX
    )
)


async def _scan(flow: ConfigFlow, unicast: list[str] | None = None) -> dict[str, ScanResult]:
    transport = await async_acquire_transport(flow.hass)
    try:
        return await transport.scan(SCAN_ATTEMPTS, SCAN_WINDOW_S, unicast)
    finally:
        async_release_transport(flow.hass)


class GoveeStringsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Govee string."""

    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, ScanResult] = {}
        self._device: ScanResult | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: GoveeConfigEntry) -> OptionsFlow:
        return GoveeStringsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_DEVICE_ID] == MANUAL:
                return await self.async_step_manual()
            self._device = self._found[user_input[CONF_DEVICE_ID]]
            return await self._async_set_device()
        try:
            found = await _scan(self)
        except PortInUseError:
            return self.async_abort(reason="port_in_use")
        configured = self._async_current_ids(include_ignore=False)
        self._found = {k: v for k, v in found.items() if k not in configured}
        options = [
            selector.SelectOptionDict(
                value=d.device_id, label=f"{d.sku} at {d.ip} ({d.device_id[-5:]})"
            )
            for d in sorted(self._found.values(), key=lambda d: d.ip)
        ]
        options.append(selector.SelectOptionDict(value=MANUAL, label="Enter an IP address"))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
            description_placeholders={"count": str(len(self._found))},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                found = await _scan(self, unicast=[host])
            except PortInUseError:
                return self.async_abort(reason="port_in_use")
            match = next((d for d in found.values() if d.ip == host), None)
            if match is None:
                errors["base"] = "no_answer"
            else:
                self._device = match
                return await self._async_set_device()
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        self._device = ScanResult(
            device_id=discovery_info[CONF_DEVICE_ID],
            sku=discovery_info[CONF_SKU],
            ip=discovery_info[CONF_IP],
        )
        await self.async_set_unique_id(self._device.device_id)
        self._abort_if_unique_id_configured(updates={CONF_IP: self._device.ip})
        self.context["title_placeholders"] = {"sku": self._device.sku, "ip": self._device.ip}
        return await self.async_step_bulbs()

    async def _async_set_device(self) -> ConfigFlowResult:
        assert self._device is not None
        await self.async_set_unique_id(self._device.device_id)
        self._abort_if_unique_id_configured(updates={CONF_IP: self._device.ip})
        return await self.async_step_bulbs()

    async def async_step_bulbs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Bulb count can't be discovered: the same model ships in different lengths."""
        assert self._device is not None
        if user_input is not None:
            return self.async_create_entry(
                title=f"Govee {self._device.sku} {self._device.device_id[-5:].replace(':', '')}",
                data={
                    CONF_DEVICE_ID: self._device.device_id,
                    CONF_SKU: self._device.sku,
                    CONF_IP: self._device.ip,
                },
                options={
                    CONF_BULB_COUNT: int(user_input[CONF_BULB_COUNT]),
                    CONF_ENFORCE_INTERVAL: DEFAULT_ENFORCE_INTERVAL_MIN,
                },
            )
        return self.async_show_form(
            step_id="bulbs",
            data_schema=vol.Schema({vol.Required(CONF_BULB_COUNT): BULB_COUNT_SELECTOR}),
            description_placeholders={"sku": self._device.sku, "ip": self._device.ip},
        )


class GoveeStringsOptionsFlow(OptionsFlow):
    """Change bulb count and the enforce interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_BULB_COUNT: int(user_input[CONF_BULB_COUNT]),
                    CONF_ENFORCE_INTERVAL: int(user_input[CONF_ENFORCE_INTERVAL]),
                }
            )
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BULB_COUNT, default=options[CONF_BULB_COUNT]
                    ): BULB_COUNT_SELECTOR,
                    vol.Required(
                        CONF_ENFORCE_INTERVAL,
                        default=options.get(CONF_ENFORCE_INTERVAL, DEFAULT_ENFORCE_INTERVAL_MIN),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=240,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
