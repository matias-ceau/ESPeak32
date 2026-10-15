"""`Transport` over bleak (optional dependency: `pip install -e 'tools[ble]'`). bleak is imported lazily."""

from __future__ import annotations

import asyncio

from .ble import CTRL_UUID, DATA_UUID, INFO_UUID, SERVICE_UUID
from .sync import LinkLost, Transport

_LOST = ("lost", b"")


class DeviceNotFound(RuntimeError):
    pass


class BleakTransport:
    def __init__(self) -> None:
        self.client = None
        self.mtu = 23
        self._events: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self._lost = False

    def _on_disconnect(self, _client) -> None:
        self._lost = True
        self._events.put_nowait(_LOST)

    def _on_ctrl(self, _sender, data: bytearray) -> None:
        self._events.put_nowait(("ctrl", bytes(data)))

    def _on_data(self, _sender, data: bytearray) -> None:
        self._events.put_nowait(("data", bytes(data)))

    async def _gatt(self, coro):
        from bleak.exc import BleakError

        if self._lost:
            raise LinkLost("disconnected")
        try:
            return await coro
        except (BleakError, OSError) as e:
            if self._lost or not self.client.is_connected:
                raise LinkLost(str(e)) from e
            raise

    async def read_info(self) -> bytes:
        return bytes(await self._gatt(self.client.read_gatt_char(INFO_UUID)))

    async def write_ctrl(self, b: bytes) -> None:
        await self._gatt(self.client.write_gatt_char(CTRL_UUID, b, response=True))

    async def next_event(self, timeout: float) -> tuple[str, bytes]:
        try:
            ev = await asyncio.wait_for(self._events.get(), timeout)
        except asyncio.TimeoutError:
            raise TimeoutError from None
        if ev is _LOST:
            self._events.put_nowait(_LOST)  # every later call fails too
            raise LinkLost("disconnected")
        return ev

    async def close(self) -> None:
        if self.client is not None and self.client.is_connected:
            await self.client.disconnect()


async def scan_bleak(timeout: float = 5.0) -> list[tuple[str, str, int]]:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout, service_uuids=[SERVICE_UUID], return_adv=True)
    return [(d.address, d.name or "", adv.rssi) for d, adv in found.values()]


async def connect_bleak(address: str | None, pair: bool, timeout: float = 10.0) -> Transport:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError

    if address is None:
        target = await BleakScanner.find_device_by_filter(
            lambda d, adv: SERVICE_UUID in (u.lower() for u in adv.service_uuids), timeout=timeout)
        if target is None:
            raise DeviceNotFound("no ESPeak32 advertising nearby (press the button for 1.5 s to advertise)")
    else:
        target = address
    t = BleakTransport()
    client = BleakClient(target, disconnected_callback=t._on_disconnect, timeout=timeout)
    t.client = client
    try:
        await client.connect()
    except (BleakError, asyncio.TimeoutError) as e:
        raise DeviceNotFound(f"cannot connect: {e}") from e
    if pair:
        await client.pair()
    try:
        await client.read_gatt_char(INFO_UUID)  # encrypted: makes the OS pair (Just Works) if it has not yet
    except BleakError:
        await client.pair()
    t.mtu = client.mtu_size
    # StartNotify (one ordered D-Bus stream) rather than AcquireNotify (one socket per characteristic, so CTRL can
    # overtake DATA); bleak >= 3.0.2 defaults to it, 2.1-3.0.1 did not.
    await client.start_notify(CTRL_UUID, t._on_ctrl, bluez={"use_start_notify": True})
    await client.start_notify(DATA_UUID, t._on_data, bluez={"use_start_notify": True})
    return t
