"""`Transport` over bleak (optional dependency: `pip install -e 'tools[ble]'`). bleak is imported lazily."""

from __future__ import annotations

import asyncio
import contextlib
import sys

from .ble import CTRL_UUID, DATA_UUID, INFO_UUID, OP_GET, SERVICE_UUID
from .sync import LinkLost, Transport

_LOST = ("lost", b"")


class DeviceNotFound(RuntimeError):
    pass


class BluetoothError(RuntimeError):
    """The PC's Bluetooth stack failed (adapter off or blocked, bluetoothd not running...)."""


class BleakTransport:
    def __init__(self) -> None:
        self.client = None
        self.mtu = 23
        self._events: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self._lost = False
        self._connected = False
        self._last_ctrl: bytes | None = None  # duplicate filters, see _on_ctrl / _on_data
        self._last_seq: int | None = None

    def mark_connected(self) -> None:
        """Starts honouring disconnect callbacks; bleak can report a stale one while connecting."""
        self._connected = True
        self._lost = False
        self._events = asyncio.Queue()
        self._last_ctrl = self._last_seq = None

    def _on_disconnect(self, _client) -> None:
        if not self._connected:
            return
        self._lost = True
        self._events.put_nowait(_LOST)

    # After a reconnect within one process, BlueZ/bleak may deliver each notification twice. Our protocol never
    # repeats a DATA seq back to back, and never answers twice identically without a new request, so both are dropped.
    def _wrote(self) -> None:
        self._last_ctrl = None

    def _on_ctrl(self, _sender, data: bytearray) -> None:
        msg = bytes(data)
        if msg == self._last_ctrl:
            return
        self._last_ctrl = msg
        self._events.put_nowait(("ctrl", msg))

    def _on_data(self, _sender, data: bytearray) -> None:
        msg = bytes(data)
        seq = int.from_bytes(msg[:2], "little") if len(msg) >= 2 else None
        if seq is not None and seq == self._last_seq:
            return
        self._last_seq = seq
        self._events.put_nowait(("data", msg))

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
        self._wrote()
        if b and b[0] == OP_GET:
            self._last_seq = None  # seq restarts at 0 for every GET
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


def _is_espeak32(adv) -> bool:
    return SERVICE_UUID in (u.lower() for u in adv.service_uuids)


# Scans pass no service-UUID filter to BlueZ and match here instead: bluez 5.87 can crash (use-after-free in
# is_filter_match) when a UUID discovery filter outlives the client that set it.
async def scan_bleak(timeout: float = 5.0) -> list[tuple[str, str, int]]:
    from bleak import BleakScanner
    from bleak.exc import BleakError

    try:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except BleakError as e:
        raise BluetoothError(str(e)) from e
    return [(d.address, d.name or "", adv.rssi) for d, adv in found.values() if _is_espeak32(adv)]


async def connect_bleak(address: str | None, pair: bool, timeout: float = 10.0) -> Transport:
    from bleak.exc import BleakError

    try:
        return await _connect_bleak(address, pair, timeout)
    except BleakError as e:
        raise BluetoothError(str(e)) from e


async def _connect_bleak(address: str | None, pair: bool, timeout: float) -> Transport:
    from bleak import BleakScanner

    if address is None:
        target = await BleakScanner.find_device_by_filter(lambda d, adv: _is_espeak32(adv), timeout=timeout)
        if target is None:
            raise DeviceNotFound("no ESPeak32 advertising nearby (flick the switch on-off, or hold the button 1.5 s, to advertise)")
    else:
        target = address
    addr = target if isinstance(target, str) else target.address
    if sys.platform.startswith("linux"):  # BlueZ needs an agent to confirm Just Works pairing
        from .bluez_agent import just_works_agent

        agent = just_works_agent(addr)
    else:
        agent = contextlib.nullcontext()
    async with agent:
        return await _open(target, pair, timeout)


async def _open(target, pair: bool, timeout: float) -> Transport:
    from bleak import BleakClient
    from bleak.exc import BleakError

    t = BleakTransport()
    client = BleakClient(target, disconnected_callback=t._on_disconnect, timeout=timeout)
    t.client = client
    try:
        await client.connect()
    except (BleakError, asyncio.TimeoutError) as e:
        raise DeviceNotFound(f"cannot connect: {e}") from e
    t.mark_connected()
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
