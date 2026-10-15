"""Resumable BLE sync client (protocol/PROTOCOL.md, behaviour rules) and an in-memory transport for tests.

The transport delivers CTRL and DATA notifications through one ordered event queue, because both share one ATT
bearer and their relative order (TRANSFER_DONE after the last chunk) is the only ordering guarantee BLE gives.
"""

from __future__ import annotations

import asyncio
import json
import os
import zlib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from . import ble
from .container import FormatError, parse
from .device_model import DeviceModel

CTRL_TIMEOUT_S = 5.0
MAX_RESUMES_PER_FETCH = 8


class LinkLost(Exception):
    pass


class SyncError(RuntimeError):
    """A failure that reconnecting will not fix."""


class _Busy(Exception):
    pass


class _CrcMismatch(Exception):
    pass


class _ReadFailed(Exception):
    pass


class Transport(Protocol):
    mtu: int

    async def read_info(self) -> bytes: ...
    async def write_ctrl(self, b: bytes) -> None: ...
    async def next_event(self, timeout: float) -> tuple[str, bytes]:
        """("ctrl"|"data", payload) in arrival order; TimeoutError on timeout, LinkLost once the link is gone."""
    async def close(self) -> None: ...


class ModelTransport:
    """Transport over a DeviceModel with fault injection. The device runs synchronously on each write."""

    def __init__(self, dev: DeviceModel, mtu: int = 247, drop_after_chunks: int | None = None,
                 drop_chunk: int | None = None, corrupt: Callable[[int], bool] | None = None,
                 drop_on_op: int | None = None, drop_before: bool = True,
                 on_write: Callable[[bytes], None] | None = None):
        self.dev, self.mtu = dev, mtu
        self.drop_after_chunks, self.drop_chunk, self.corrupt = drop_after_chunks, drop_chunk, corrupt
        self.drop_on_op, self.drop_before, self.on_write = drop_on_op, drop_before, on_write
        self.writes: list[bytes] = []
        self.data_seen = 0  # DATA chunks the device produced on this connection
        self.data_delivered = 0
        self._events: deque[tuple[str, bytes]] = deque()
        self._closed = False
        dev.outputs.clear()
        dev.connect(mtu)

    def _drop(self) -> None:
        self._closed = True
        self.dev.disconnect()
        self.dev.outputs.clear()  # whatever was in flight is lost with the link

    def _collect(self) -> None:
        self.dev.run_until_idle()
        for ch, msg in self.dev.outputs:
            if self._closed:
                break
            if ch == "data":
                idx = self.data_seen
                self.data_seen += 1
                if self.drop_after_chunks is not None and idx >= self.drop_after_chunks:
                    self._drop()
                    break
                if idx == self.drop_chunk:
                    continue
                seq, payload = ble.unpack_data_chunk(msg)
                if self.corrupt is not None and payload and self.corrupt(seq):
                    msg = msg[:2] + bytes([payload[0] ^ 0x01]) + payload[1:]
                self.data_delivered += 1
            self._events.append((ch, msg))
        self.dev.outputs.clear()

    async def read_info(self) -> bytes:
        if self._closed:
            raise LinkLost("closed")
        return self.dev.info()

    async def write_ctrl(self, b: bytes) -> None:
        if self._closed:
            raise LinkLost("closed")
        self.writes.append(b)
        if self.on_write:
            self.on_write(b)
        if self.drop_on_op is not None and b[0] == self.drop_on_op:
            self.drop_on_op = None
            if not self.drop_before:
                self.dev.request(b)
            self._drop()
            raise LinkLost("dropped on write")
        self.dev.request(b)
        self._collect()

    async def next_event(self, timeout: float) -> tuple[str, bytes]:
        if self._events:
            return self._events.popleft()
        if self._closed:
            raise LinkLost("closed")
        raise TimeoutError

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.dev.disconnect()


def note_key(e: ble.ListEntry) -> str:
    return f"{e.file_id}:{e.boot_id}:{e.start_us}"


def wall_ms(boot_id: int, start_us: int, clock: dict[int, tuple[int, int]]) -> int | None:
    pair = clock.get(boot_id)
    if pair is None:
        return None
    unix_ms, ticks_us = pair
    return unix_ms + (start_us - ticks_us) // 1000


class SyncClient:
    def __init__(self, t: Transport, window: int = 16, stall_s: float = 5.0, mtu_retry_s: float = 0.5):
        if window < 2:
            raise ValueError("window must be at least 2")
        self.t, self.window, self.stall_s, self.mtu_retry_s = t, window, stall_s, mtu_retry_s

    async def _next_ctrl(self) -> ble.CtrlMessage:
        """Next CTRL message, discarding DATA left over from an aborted transfer."""
        while True:
            try:
                ch, msg = await self.t.next_event(CTRL_TIMEOUT_S)
            except TimeoutError:
                raise LinkLost("no response from device") from None
            if ch == "ctrl":
                return ble.decode_ctrl(msg)

    async def _request(self, req: bytes) -> ble.CtrlMessage:
        """Sends a request and returns its first response, retrying once if the MTU was not negotiated yet."""
        for attempt in range(2):
            await self.t.write_ctrl(req)
            msg = await self._next_ctrl()
            if isinstance(msg, ble.ErrorAck) and msg.status == ble.STATUS_MTU:
                if attempt == 0:
                    await asyncio.sleep(self.mtu_retry_s)
                    continue
                raise SyncError("the link MTU is below 64 bytes; this phone or adapter cannot sync")
            return msg
        raise AssertionError("unreachable")

    async def info(self) -> ble.Info:
        return ble.unpack_info(await self.t.read_info())

    async def set_time(self, unix_ms: int) -> int:
        msg = await self._request(ble.req_set_time(unix_ms))
        if not isinstance(msg, ble.SetTimeAck):
            raise SyncError(f"unexpected SET_TIME answer {msg!r}")
        return msg.ticks_us

    async def list(self) -> list[ble.ListEntry]:
        msg = await self._request(ble.req_list())
        entries = []
        while True:
            if not isinstance(msg, ble.ListEntry):
                raise SyncError(f"unexpected LIST answer {msg!r}")
            if msg.total == 0:
                return []
            entries.append(msg)
            if len(entries) == msg.total:
                return entries
            msg = await self._next_ctrl()

    async def delete(self, file_id: int) -> bool:
        """True if the device deleted the note or no longer has it."""
        msg = await self._request(ble.req_delete(file_id))
        if isinstance(msg, ble.DeleteAck):
            return True
        if isinstance(msg, ble.ErrorAck) and msg.status == ble.STATUS_NOT_FOUND:
            return True
        if isinstance(msg, ble.ErrorAck) and msg.status == ble.STATUS_BUSY:
            return False
        raise SyncError(f"unexpected DELETE answer {msg!r}")

    async def _abort(self) -> None:
        await self.t.write_ctrl(ble.req_abort())
        while not isinstance(await self._next_ctrl(), ble.AbortAck):
            pass

    async def fetch(self, entry: ble.ListEntry, part: Path) -> bytes:
        """Fetches a note into `part`, resuming from its current size, and returns the verified bytes."""
        resumes = 0
        while True:
            offset = part.stat().st_size if part.exists() else 0
            if offset > entry.size:
                part.unlink()
                offset = 0
            msg = await self._request(ble.req_get(entry.file_id, offset, self.window))
            if isinstance(msg, ble.ErrorAck):
                if msg.status == ble.STATUS_BUSY:
                    raise _Busy()
                if msg.status == ble.STATUS_BAD_ARGS and offset:
                    part.unlink()
                    continue
                if msg.status == ble.STATUS_IO:
                    raise _ReadFailed()
                raise SyncError(f"GET of note {entry.file_id} failed with status {msg.status}")
            if not isinstance(msg, ble.GetAck) or msg.file_id != entry.file_id:
                raise SyncError(f"unexpected GET answer {msg!r}")
            outcome = await self._receive(part, offset, msg.total_size)
            if isinstance(outcome, ble.TransferDone):
                data = part.read_bytes()
                try:
                    parse(data)
                    ok = zlib.crc32(data) == outcome.file_crc32
                except FormatError:
                    ok = False
                if not ok:
                    part.unlink()
                    raise _CrcMismatch()
                return data
            resumes += 1
            if resumes > MAX_RESUMES_PER_FETCH:
                raise SyncError(f"note {entry.file_id}: transfer keeps losing chunks")
            await self._abort()

    async def _receive(self, part: Path, offset: int, size: int) -> ble.CtrlMessage | None:
        """Appends chunks until TRANSFER_DONE (returned) or a gap or stall (None: caller resumes)."""
        expected_seq, consumed, received = 0, 0, offset
        half = self.window // 2
        link_ok = True  # after a failed CREDIT write, keep the chunks already queued; next_event raises LinkLost
        with open(part, "ab") as f:
            try:
                while True:
                    try:
                        ch, msg = await self.t.next_event(self.stall_s)
                    except TimeoutError:
                        return None
                    if ch == "ctrl":
                        m = ble.decode_ctrl(msg)
                        if isinstance(m, ble.TransferFailed):
                            raise _ReadFailed()
                        if isinstance(m, ble.TransferDone):
                            return m if received == size else None
                        continue
                    seq, payload = ble.unpack_data_chunk(msg)
                    if seq != expected_seq:
                        return None
                    f.write(payload)
                    received += len(payload)
                    expected_seq = (expected_seq + 1) & 0xFFFF
                    consumed += 1
                    if consumed >= half and link_ok:
                        consumed = 0
                        try:
                            await self.t.write_ctrl(ble.req_credit(half))
                        except LinkLost:
                            link_ok = False
            finally:
                f.flush()
                os.fsync(f.fileno())


@dataclass
class SyncReport:
    fetched: list[int] = field(default_factory=list)
    deleted: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def _load_clock(path: Path) -> dict[int, tuple[int, int]]:
    if not path.exists():
        return {}
    return {int(k): (v[0], v[1]) for k, v in json.loads(path.read_text()).items()}


def _save_clock(path: Path, clock: dict[int, tuple[int, int]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({str(k): list(v) for k, v in sorted(clock.items())}))
    os.replace(tmp, path)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


async def _fetch_verified(client: SyncClient, e: ble.ListEntry, part: Path) -> bytes | str:
    """Verified bytes, or the reason the note is skipped. A CRC mismatch or a device read failure is retried once."""
    retried = False
    while True:
        try:
            return await client.fetch(e, part)
        except _Busy:
            return "busy (recording)"
        except _CrcMismatch:
            if retried:
                return "crc mismatch after refetch"
        except _ReadFailed:
            if retried:
                return "read failure on device"
        retried = True


async def _sync_once(t: Transport, out_dir: Path, delete: bool, now_ms: Callable[[], int], window: int,
                     mtu_retry_s: float, report: SyncReport) -> None:
    client = SyncClient(t, window, mtu_retry_s=mtu_retry_s)
    info = await client.info()
    unix_ms = now_ms()
    ticks = await client.set_time(unix_ms)
    clock_path = out_dir / "clock.json"
    clock = _load_clock(clock_path)
    clock[info.boot_id] = (unix_ms, ticks)
    _save_clock(clock_path, clock)
    for e in await client.list():
        name = note_key(e).replace(":", "_") + ".e32"
        final, part = out_dir / name, out_dir / (name + ".part")
        if not (final.exists() and final.stat().st_size == e.size):
            result = await _fetch_verified(client, e, part)
            if isinstance(result, str):
                if (e.file_id, result) not in report.skipped:
                    report.skipped.append((e.file_id, result))
                continue
            os.replace(part, final)
            _fsync_dir(out_dir)
            if e.file_id not in report.fetched:
                report.fetched.append(e.file_id)
        if delete and await client.delete(e.file_id) and e.file_id not in report.deleted:
            report.deleted.append(e.file_id)


async def sync_all(connect: Callable[[], Awaitable[Transport]], out_dir: Path, delete: bool,
                   now_ms: Callable[[], int], window: int = 16, attempts: int = 3,
                   mtu_retry_s: float = 0.5) -> SyncReport:
    """SET_TIME, LIST, fetch every note, then DELETE it only once it is stored (two-phase delete).

    Reconnects through `connect()` after a lost link and resumes from the partial files, up to `attempts` times."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report = SyncReport()
    for _ in range(attempts):
        t = await connect()
        try:
            await _sync_once(t, out_dir, delete, now_ms, window, mtu_retry_s, report)
            return report
        except LinkLost:
            continue
        finally:
            await t.close()
    raise SyncError(f"link lost {attempts} times; partial notes are kept and the next sync resumes them")
