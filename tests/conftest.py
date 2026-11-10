"""Shared fixtures: a fake transport, so no test touches the network."""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.govee_strings.const import (
    CONF_BULB_COUNT,
    CONF_DEVICE_ID,
    CONF_ENFORCE_INTERVAL,
    CONF_IP,
    CONF_SKU,
    DOMAIN,
)
from custom_components.govee_strings.data import get_data
from custom_components.govee_strings.transport import PortInUseError, ScanResult

DEVICE_ID = "1D:C9:DC:6E:01:06:46:96"
SAUNA = ScanResult(device_id=DEVICE_ID, sku="H7025", ip="192.168.50.172")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components/."""


class FakeTransport:
    """Records what would have gone on the wire."""

    instances: ClassVar[list[FakeTransport]] = []
    devices: ClassVar[dict[str, ScanResult]] = {}
    status: ClassVar[dict[str, Any] | None] = {"onOff": 1, "brightness": 40}
    port_in_use: ClassVar[bool] = False

    def __init__(self, loop: Any) -> None:
        self.running = False
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.status_requests = 0
        FakeTransport.instances.append(self)

    async def start(self) -> None:
        if FakeTransport.port_in_use:
            raise PortInUseError("Address already in use")
        self.running = True

    def stop(self) -> None:
        self.running = False

    def add_listener(self, listener: Any) -> Any:
        return lambda: None

    def send(self, ip: str, payload: bytes, port: int = 4003) -> None:
        self.sent.append((ip, json.loads(payload)["msg"]))

    def send_command(self, ip: str, cmd: str, data: dict[str, Any]) -> None:
        self.sent.append((ip, {"cmd": cmd, "data": data}))

    async def request_status(self, ip: str, wait: float = 2.0) -> dict[str, Any] | None:
        self.status_requests += 1
        return FakeTransport.status

    async def scan(
        self, attempts: int, window: float, unicast: list[str] | None = None
    ) -> dict[str, ScanResult]:
        return dict(FakeTransport.devices)

    # helpers for assertions
    def frames(self) -> list[bytes]:
        out = []
        for _ip, msg in self.sent:
            if msg["cmd"] == "ptReal":
                out += [base64.b64decode(c) for c in msg["data"]["command"]]
        return out

    def commands(self) -> list[str]:
        return [msg["cmd"] for _ip, msg in self.sent]


@pytest.fixture
def transport() -> Generator[type[FakeTransport]]:
    FakeTransport.instances = []
    FakeTransport.devices = {SAUNA.device_id: SAUNA}
    FakeTransport.status = {"onOff": 1, "brightness": 40}
    FakeTransport.port_in_use = False
    with (
        patch("custom_components.govee_strings.data.GoveeTransport", FakeTransport),
        patch("custom_components.govee_strings.device.FRAME_INTERVAL_S", 0),
        patch("custom_components.govee_strings.data.async_start_discovery"),
        patch("custom_components.govee_strings.async_start_discovery"),
    ):
        yield FakeTransport


def make_entry(bulb_count: int = 15) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        title="Govee H7025 4696",
        data={CONF_DEVICE_ID: DEVICE_ID, CONF_SKU: "H7025", CONF_IP: SAUNA.ip},
        options={CONF_BULB_COUNT: bulb_count, CONF_ENFORCE_INTERVAL: 5},
    )


@pytest.fixture
async def loaded(hass: HomeAssistant, transport: type[FakeTransport]) -> MockConfigEntry:
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def fake(hass: HomeAssistant) -> FakeTransport:
    t: FakeTransport = get_data(hass).transport  # type: ignore[assignment]
    return t
