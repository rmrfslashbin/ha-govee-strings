"""Config flow tests."""

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.govee_strings.const import CONF_BULB_COUNT, CONF_IP, DOMAIN

from .conftest import DEVICE_ID, SAUNA, FakeTransport, make_entry


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_picks_discovered_string(
    hass: HomeAssistant, transport: type[FakeTransport]
) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": DEVICE_ID}
    )
    assert result["step_id"] == "bulbs"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BULB_COUNT: 15}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IP] == SAUNA.ip
    assert result["options"][CONF_BULB_COUNT] == 15
    assert result["result"].unique_id == DEVICE_ID


async def test_manual_ip_no_answer_then_answer(
    hass: HomeAssistant, transport: type[FakeTransport]
) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": "manual"}
    )
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "10.0.0.9"})
    assert result["errors"] == {"base": "no_answer"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": SAUNA.ip})
    assert result["step_id"] == "bulbs"


async def test_port_in_use_aborts(hass: HomeAssistant, transport: type[FakeTransport]) -> None:
    transport.port_in_use = True
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "port_in_use"


async def test_discovery_updates_ip_of_known_string(
    hass: HomeAssistant, transport: type[FakeTransport]
) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
        data={"device_id": DEVICE_ID, "sku": "H7025", "ip": "192.168.50.200"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_IP] == "192.168.50.200"


async def test_discovery_of_new_string_asks_bulb_count(
    hass: HomeAssistant, transport: type[FakeTransport]
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
        data={"device_id": DEVICE_ID, "sku": "H7025", "ip": SAUNA.ip},
    )
    assert result["step_id"] == "bulbs"


async def test_options_flow_changes_bulb_count(hass: HomeAssistant, loaded) -> None:
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BULB_COUNT: 20, "enforce_interval": 10}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded.runtime_data.bulb_count == 20


async def test_refuses_while_core_govee_is_loaded(
    hass: HomeAssistant, transport: type[FakeTransport]
) -> None:
    core = MagicMock(state=ConfigEntryState.LOADED)
    real = hass.config_entries.async_entries

    def entries(domain: str | None = None, *args, **kwargs):
        return [core] if domain == "govee_light_local" else real(domain, *args, **kwargs)

    with patch.object(hass.config_entries, "async_entries", side_effect=entries):
        result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "port_in_use"
