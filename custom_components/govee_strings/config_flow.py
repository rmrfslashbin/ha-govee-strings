"""Config flow for the Govee Strings (LAN) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class GoveeStringsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Govee Strings."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm setup. Discovery and per-string settings come in later steps."""
        if user_input is not None:
            return self.async_create_entry(title="Govee Strings (LAN)", data={})
        return self.async_show_form(step_id="user")
