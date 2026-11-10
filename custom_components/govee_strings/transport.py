"""Async UDP transport for the Govee LAN API.

One transport per Home Assistant instance owns the reply port (4002). It is shared by
every config entry and by config flows, and reference-counted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .const import COMMAND_PORT, LISTEN_PORT, MULTICAST_ADDRESS, SCAN_PORT

_LOGGER = logging.getLogger(__name__)

SCAN_MESSAGE = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode()
STATUS_MESSAGE = json.dumps({"msg": {"cmd": "devStatus", "data": {}}}).encode()


class PortInUseError(Exception):
    """The reply port is held by another listener, usually govee_light_local."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    """One device's answer to a scan."""

    device_id: str
    sku: str
    ip: str


Listener = Callable[[str, dict[str, Any], str], None]  # (cmd, data, source_ip)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, owner: GoveeTransport) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        try:
            msg = json.loads(data)["msg"]
            cmd, payload = str(msg["cmd"]), dict(msg.get("data") or {})
        except ValueError, KeyError, TypeError:
            _LOGGER.debug("Ignoring malformed datagram from %s", addr[0])
            return
        self._owner.dispatch(cmd, payload, str(addr[0]))


class GoveeTransport:
    """The shared UDP endpoint."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        bind_host: str = "0.0.0.0",
        port: int = LISTEN_PORT,
        command_port: int = COMMAND_PORT,
    ) -> None:
        self._loop = loop
        self._bind_host = bind_host
        self._port = port
        self._command_port = command_port
        self._transport: asyncio.DatagramTransport | None = None
        self._listeners: list[Listener] = []
        self._status_waiters: dict[str, list[asyncio.Future[dict[str, Any]]]] = {}

    @property
    def running(self) -> bool:
        return self._transport is not None

    async def start(self) -> None:
        """Bind the reply port. Raise PortInUseError if something else holds it."""
        if self._transport is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Deliberately neither SO_REUSEADDR nor SO_REUSEPORT. On Linux, two UDP sockets
        # that both set SO_REUSEADDR may share a port, and replies would then be split
        # with govee_light_local. Failing to bind is the safe outcome.
        try:
            sock.bind((self._bind_host, self._port))
        except OSError as err:
            sock.close()
            raise PortInUseError(str(err)) from err
        with contextlib.suppress(OSError):
            mreq = struct.pack(
                "4s4s", socket.inet_aton(MULTICAST_ADDRESS), socket.inet_aton("0.0.0.0")
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.setblocking(False)
        transport, _ = await self._loop.create_datagram_endpoint(lambda: _Protocol(self), sock=sock)
        self._transport = transport

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        for waiters in self._status_waiters.values():
            for fut in waiters:
                if not fut.done():
                    fut.cancel()
        self._status_waiters.clear()

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def dispatch(self, cmd: str, data: dict[str, Any], source_ip: str) -> None:
        if cmd == "devStatus":
            for fut in self._status_waiters.pop(source_ip, []):
                if not fut.done():
                    fut.set_result(data)
        for listener in list(self._listeners):
            try:
                listener(cmd, data, source_ip)
            except Exception:
                _LOGGER.exception("Govee listener failed")

    def send(self, ip: str, payload: bytes, port: int | None = None) -> None:
        if self._transport is None:
            raise RuntimeError("transport is not running")
        self._transport.sendto(payload, (ip, port or self._command_port))

    def send_command(self, ip: str, cmd: str, data: dict[str, Any]) -> None:
        self.send(ip, json.dumps({"msg": {"cmd": cmd, "data": data}}).encode())

    async def request_status(self, ip: str, wait: float = 2.0) -> dict[str, Any] | None:
        fut: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._status_waiters.setdefault(ip, []).append(fut)
        self.send(ip, STATUS_MESSAGE)
        try:
            async with asyncio.timeout(wait):
                return await fut
        except TimeoutError:
            return None
        finally:
            waiters = self._status_waiters.get(ip, [])
            if fut in waiters:
                waiters.remove(fut)

    async def scan(
        self, attempts: int, window: float, unicast: list[str] | None = None
    ) -> dict[str, ScanResult]:
        """Scan repeatedly (multicast is lossy) and collect answers by device id."""
        found: dict[str, ScanResult] = {}

        def on_msg(cmd: str, data: dict[str, Any], source_ip: str) -> None:
            if cmd == "scan" and (result := parse_scan(data, source_ip)):
                found[result.device_id] = result

        remove = self.add_listener(on_msg)
        try:
            for _ in range(attempts):
                self.send(MULTICAST_ADDRESS, SCAN_MESSAGE, SCAN_PORT)
                for ip in unicast or []:
                    self.send(ip, SCAN_MESSAGE, SCAN_PORT)
                await asyncio.sleep(window / attempts)
        finally:
            remove()
        return found


def parse_scan(data: dict[str, Any], source_ip: str) -> ScanResult | None:
    device_id, sku = data.get("device"), data.get("sku")
    if not isinstance(device_id, str) or not isinstance(sku, str):
        return None
    return ScanResult(device_id=device_id, sku=sku, ip=str(data.get("ip") or source_ip))
