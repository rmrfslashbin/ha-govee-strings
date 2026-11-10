"""Setup, entities, actions, patterns and enforce."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.govee_strings import protocol
from custom_components.govee_strings.const import DOMAIN
from custom_components.govee_strings.services import parse_bulbs

from .conftest import DEVICE_ID, FakeTransport, fake, make_entry

LIGHT = "light.govee_h7025_4696"
SELECT = "select.govee_h7025_4696_pattern"
SWITCH = "switch.govee_h7025_4696_enforce_pattern"


def _device_id(hass: HomeAssistant) -> str:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, DEVICE_ID), entry.entry_id)
    assert device is not None
    return device.id


async def test_setup_sends_nothing_to_the_light(hass: HomeAssistant, loaded) -> None:
    # Only a status read: a hand-set per-bulb pattern must survive setup.
    assert fake(hass).sent == []
    assert fake(hass).status_requests >= 1
    state = hass.states.get(LIGHT)
    assert state is not None and state.state == "on"
    assert state.attributes["bulb_count"] == 15


async def test_bulb_lights_are_disabled_by_default(hass: HomeAssistant, loaded) -> None:
    ent = er.async_get(hass)
    bulbs = [
        e
        for e in er.async_entries_for_config_entry(ent, loaded.entry_id)
        if "_bulb_" in e.unique_id
    ]
    assert len(bulbs) == 15
    assert all(e.disabled_by is er.RegistryEntryDisabler.INTEGRATION for e in bulbs)


async def test_port_in_use_retries_setup(
    hass: HomeAssistant, transport: type[FakeTransport]
) -> None:
    transport.port_in_use = True
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_paint_groups_bulbs_by_value(hass: HomeAssistant, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        "paint",
        {
            "device_id": _device_id(hass),
            "runs": [
                {"bulbs": "1-15", "rgb": [192, 0, 255]},
                {"bulbs": [1], "rgb": [0, 255, 255]},
                {"bulbs": "2", "brightness": 10},
            ],
        },
        blocking=True,
    )
    assert fake(hass).frames() == [
        protocol.color_frame((0, 255, 255), [1], 15),
        protocol.color_frame((192, 0, 255), range(2, 16), 15),
        protocol.brightness_frame(10, [2], 15),
    ]


async def test_paint_off_is_black_and_on_restores(hass: HomeAssistant, loaded) -> None:
    dev = _device_id(hass)
    call = hass.services.async_call
    await call(
        DOMAIN,
        "paint",
        {"device_id": dev, "runs": [{"bulbs": [3], "rgb": [1, 2, 3]}]},
        blocking=True,
    )
    await call(
        DOMAIN, "paint", {"device_id": dev, "runs": [{"bulbs": [3], "on": False}]}, blocking=True
    )
    await call(
        DOMAIN, "paint", {"device_id": dev, "runs": [{"bulbs": [3], "on": True}]}, blocking=True
    )
    assert fake(hass).frames()[-2:] == [
        protocol.color_frame((0, 0, 0), [3], 15),
        protocol.color_frame((1, 2, 3), [3], 15),
    ]


async def test_paint_rejects_bulb_beyond_string(hass: HomeAssistant, loaded) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "paint",
            {"device_id": _device_id(hass), "runs": [{"bulbs": [16], "rgb": [1, 1, 1]}]},
            blocking=True,
        )


async def test_whole_string_color_uses_colorwc(hass: HomeAssistant, loaded) -> None:
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT, "rgb_color": [10, 20, 30]}, blocking=True
    )
    assert fake(hass).sent[-1][1] == {
        "cmd": "colorwc",
        "data": {"color": {"r": 10, "g": 20, "b": 30}, "colorTemInKelvin": 0},
    }
    assert all(b.rgb == (10, 20, 30) for b in loaded.runtime_data.state.bulbs)


async def test_save_apply_and_select_pattern(hass: HomeAssistant, loaded) -> None:
    bulbs = [{"rgb": [i, 0, 0], "brightness": 10 + i} for i in range(15)]
    await hass.services.async_call(
        DOMAIN, "save_pattern", {"name": "ramp", "bulbs": bulbs}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).attributes["options"] == ["ramp"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "ramp"}, blocking=True
    )
    assert hass.states.get(SELECT).state == "ramp"
    # Full repaint: 15 distinct colors + 15 distinct brightnesses.
    assert len(fake(hass).frames()) == 30

    # A paint that changes nothing keeps the pattern (sunset turn_on on a bulb, say).
    fake(hass).sent.clear()
    await hass.services.async_call(
        DOMAIN,
        "paint",
        {"device_id": _device_id(hass), "runs": [{"bulbs": [1], "on": True}]},
        blocking=True,
    )
    assert fake(hass).sent == []
    assert hass.states.get(SELECT).state == "ramp"


async def test_apply_pattern_fit(hass: HomeAssistant, loaded) -> None:
    await hass.services.async_call(
        DOMAIN,
        "save_pattern",
        {"name": "pair", "bulbs": [{"rgb": [1, 1, 1]}, {"rgb": [2, 2, 2]}]},
        blocking=True,
    )
    dev = _device_id(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "apply_pattern", {"device_id": dev, "name": "pair"}, blocking=True
        )
    await hass.services.async_call(
        DOMAIN, "apply_pattern", {"device_id": dev, "name": "pair", "fit": "repeat"}, blocking=True
    )
    rgbs = [b.rgb for b in loaded.runtime_data.state.bulbs]
    assert rgbs[:4] == [(1, 1, 1), (2, 2, 2), (1, 1, 1), (2, 2, 2)]


async def test_enforce_repaints_when_string_returns(hass: HomeAssistant, loaded) -> None:
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    string = loaded.runtime_data
    FakeTransport.status = None
    for _ in range(3):
        await string.refresh_status()
    assert not string.available
    FakeTransport.status = {"onOff": 1, "brightness": 40}
    assert await string.refresh_status() is True


async def test_turn_on_with_enforce_repaints(hass: HomeAssistant, loaded) -> None:
    string = loaded.runtime_data
    await hass.services.async_call("light", "turn_off", {"entity_id": LIGHT}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    fake(hass).sent.clear()
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT}, blocking=True)
    assert fake(hass).commands()[0] == "turn"
    assert "ptReal" in fake(hass).commands()
    assert string.is_on


@pytest.mark.parametrize(
    ("value", "expected"),
    [(7, [7]), ([3, 1], [1, 3]), ("1-3,9", [1, 2, 3, 9]), (["1-2", 5], [1, 2, 5])],
)
def test_parse_bulbs(value, expected) -> None:
    assert parse_bulbs(value) == expected
