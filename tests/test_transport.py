"""Transport against real loopback sockets (unprivileged high ports, no multicast)."""

import asyncio
import json
import socket

import pytest

from custom_components.govee_strings.transport import GoveeTransport, PortInUseError

LISTEN, COMMAND = 54002, 54003


@pytest.fixture(autouse=True)
def _sockets(socket_enabled: None) -> None:
    """These tests use real loopback sockets."""


class FakeDevice(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.received: list[dict] = []
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        msg = json.loads(data)["msg"]
        self.received.append(msg)
        if msg["cmd"] == "devStatus":
            reply = {"msg": {"cmd": "devStatus", "data": {"onOff": 1, "brightness": 7}}}
            self.transport.sendto(json.dumps(reply).encode(), ("127.0.0.1", LISTEN))


@pytest.fixture
async def pair():
    loop = asyncio.get_running_loop()
    dev_transport, device = await loop.create_datagram_endpoint(
        FakeDevice, local_addr=("127.0.0.1", COMMAND)
    )
    t = GoveeTransport(loop, bind_host="127.0.0.1", port=LISTEN, command_port=COMMAND)
    await t.start()
    yield t, device
    t.stop()
    dev_transport.close()


async def test_status_round_trip(pair) -> None:
    t, device = pair
    assert await t.request_status("127.0.0.1", wait=2) == {"onOff": 1, "brightness": 7}
    assert device.received[0]["cmd"] == "devStatus"


async def test_status_timeout_returns_none() -> None:
    t = GoveeTransport(
        asyncio.get_running_loop(), bind_host="127.0.0.1", port=LISTEN, command_port=COMMAND + 10
    )
    await t.start()
    try:
        assert await t.request_status("127.0.0.1", wait=0.2) is None
    finally:
        t.stop()


async def test_port_already_bound_raises() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", LISTEN))
    try:
        t = GoveeTransport(asyncio.get_running_loop(), bind_host="127.0.0.1", port=LISTEN)
        with pytest.raises(PortInUseError):
            await t.start()
    finally:
        holder.close()
