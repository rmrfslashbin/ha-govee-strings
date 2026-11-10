"""Actions: paint bulbs, and save, apply or delete patterns."""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MAX_BULBS
from .data import get_data
from .device import Bulb, GoveeString, Run
from .patterns import Fit, PatternMismatchError, fit_bulbs

ATTR_DEVICE_ID = "device_id"
ATTR_RUNS = "runs"
ATTR_BULBS = "bulbs"
ATTR_NAME = "name"
ATTR_FIT = "fit"


def parse_bulbs(value: Any) -> list[int]:
    """Accept 7, [1, 2, 3], "1-15,17" or ["1-3", 9]. Return sorted, unique bulb numbers."""
    items = value if isinstance(value, list) else [value]
    out: set[int] = set()
    for item in items:
        for raw in str(item).split(","):
            part = raw.strip()
            if not part:
                continue
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-", 1))
                if lo > hi:
                    raise vol.Invalid(f"bad range {part!r}")
                out.update(range(lo, hi + 1))
            else:
                out.add(int(part))
    if not out or min(out) < 1 or max(out) > MAX_BULBS:
        raise vol.Invalid(f"bulbs must be within 1..{MAX_BULBS}")
    return sorted(out)


RGB_SCHEMA = vol.All(vol.Length(min=3, max=3), [vol.All(vol.Coerce(int), vol.Range(0, 255))])
PCT_SCHEMA = vol.All(vol.Coerce(int), vol.Range(1, 100))

RUN_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BULBS): parse_bulbs,
        vol.Optional("rgb"): RGB_SCHEMA,
        vol.Optional("brightness"): PCT_SCHEMA,
        vol.Optional("on"): cv.boolean,
    }
)
BULB_SCHEMA = vol.Schema(
    {
        vol.Required("rgb"): RGB_SCHEMA,
        vol.Optional("brightness", default=100): PCT_SCHEMA,
        vol.Optional("on", default=True): cv.boolean,
    }
)

PAINT_SCHEMA = vol.Schema(
    {vol.Required(ATTR_DEVICE_ID): cv.string, vol.Required(ATTR_RUNS): [RUN_SCHEMA]}
)
SAVE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_NAME): cv.string,
            vol.Optional(ATTR_DEVICE_ID): cv.string,
            vol.Optional(ATTR_BULBS): [BULB_SCHEMA],
        }
    ),
    cv.has_at_least_one_key(ATTR_DEVICE_ID, ATTR_BULBS),
)
APPLY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_NAME): cv.string,
        vol.Optional(ATTR_FIT, default=Fit.EXACT.value): vol.In([f.value for f in Fit]),
    }
)
DELETE_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string})


def _string_for_device(hass: HomeAssistant, device_id: str) -> GoveeString:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for domain, ident in device.identifiers:
            if domain == DOMAIN and (string := get_data(hass).strings.get(ident)):
                return string
    raise ServiceValidationError(f"{device_id} is not a loaded Govee string")


async def apply_pattern(hass: HomeAssistant, string: GoveeString, name: str, fit: Fit) -> None:
    """Apply a saved pattern to a string. Shared by the action and the select entity."""
    patterns = get_data(hass).patterns
    try:
        bulbs = patterns.get(name)
        fitted = fit_bulbs(bulbs, string.bulb_count, fit)
    except (KeyError, PatternMismatchError) as err:
        raise ServiceValidationError(str(err)) from err
    await string.apply_bulbs(fitted, pattern=name)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def paint(call: ServiceCall) -> None:
        string = _string_for_device(hass, call.data[ATTR_DEVICE_ID])
        runs = [
            Run(
                bulbs=r[ATTR_BULBS],
                rgb=(int(r["rgb"][0]), int(r["rgb"][1]), int(r["rgb"][2])) if "rgb" in r else None,
                brightness=r.get("brightness"),
                on=r.get("on"),
            )
            for r in call.data[ATTR_RUNS]
        ]
        try:
            await string.paint(runs)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def save_pattern(call: ServiceCall) -> None:
        if ATTR_BULBS in call.data:
            bulbs = [Bulb.from_dict(b) for b in call.data[ATTR_BULBS]]
        else:
            bulbs = list(_string_for_device(hass, call.data[ATTR_DEVICE_ID]).state.bulbs)
        try:
            get_data(hass).patterns.save(call.data[ATTR_NAME], bulbs)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def apply(call: ServiceCall) -> None:
        string = _string_for_device(hass, call.data[ATTR_DEVICE_ID])
        await apply_pattern(hass, string, call.data[ATTR_NAME], Fit(call.data[ATTR_FIT]))

    async def delete_pattern(call: ServiceCall) -> None:
        try:
            get_data(hass).patterns.delete(call.data[ATTR_NAME])
        except KeyError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, "paint", paint, PAINT_SCHEMA)
    hass.services.async_register(DOMAIN, "save_pattern", save_pattern, SAVE_SCHEMA)
    hass.services.async_register(DOMAIN, "apply_pattern", apply, APPLY_SCHEMA)
    hass.services.async_register(DOMAIN, "delete_pattern", delete_pattern, DELETE_SCHEMA)
