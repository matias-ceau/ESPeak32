"""Reference device for the BLE transfer engine (protocol/PROTOCOL.md, behaviour rules).

Same API and semantics as firmware/core e32_xfer; generates protocol/vectors/sync.txt via synctxt.py.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from . import ble
from .container import HEADER_BYTES, FormatError, unpack_header

MIN_MTU = 64
MAX_PAYLOAD = 507
_ARG_BYTES = {ble.OP_LIST: 0, ble.OP_GET: 10, ble.OP_CREDIT: 2, ble.OP_DELETE: 4, ble.OP_SET_TIME: 8,
              ble.OP_ABORT: 0}


@dataclass
class DeviceConfig:
    boot_id: int = 5
    fw: tuple[int, int, int] = (0, 2, 0)
    codecs_mask: int = 3
    battery_pct: int = 255
    free_bytes: int = 2_500_000
    now_us: int = 1_000_000


@dataclass
class _Transfer:
    file_id: int
    size: int
    offset: int
    credits: int
    crc: int
    seq: int = 0


class DeviceModel:
    def __init__(self, notes: dict[int, bytes], config: DeviceConfig | None = None,
                 busy: dict[int, bytes] | None = None):
        self.notes = dict(notes)
        self.busy = dict(busy or {})
        self.config = config or DeviceConfig()
        self.outputs: list[tuple[str, bytes]] = []
        self.fail_read_at: tuple[int, int] | None = None
        self._mtu = 23
        self._connected = False
        self._xfer: _Transfer | None = None

    def connect(self, mtu: int) -> None:
        self._connected, self._mtu, self._xfer = True, mtu, None

    def set_mtu(self, mtu: int) -> None:
        self._mtu = mtu

    def disconnect(self) -> None:
        self._connected, self._xfer = False, None

    def info(self) -> bytes:
        c = self.config
        return ble.pack_info(ble.Info(1, c.battery_pct, c.fw, c.codecs_mask, c.free_bytes, c.boot_id, c.now_us,
                                      len(self.notes)))

    def _send(self, channel: str, msg: bytes) -> None:
        self.outputs.append((channel, msg))

    def _status(self, op: int, status: int) -> None:
        self._send("ctrl", bytes([op | 0x80, status]))

    def _read_fails(self, file_id: int, start: int, end: int) -> bool:
        f = self.fail_read_at
        return f is not None and f[0] == file_id and start <= f[1] < end

    def request(self, req: bytes) -> None:
        if not self._connected or not req:
            return
        op, args = req[0], req[1:]
        if op == ble.OP_CREDIT:
            if len(args) == 2 and self._xfer is not None:
                self._xfer.credits = min(0xFFFF, self._xfer.credits + struct.unpack("<H", args)[0])
            return
        if op not in _ARG_BYTES:
            return self._status(op, ble.STATUS_UNKNOWN_OPCODE)
        if self._mtu < MIN_MTU:
            return self._status(op, ble.STATUS_MTU)
        if len(args) != _ARG_BYTES[op]:
            return self._status(op, ble.STATUS_BAD_ARGS)
        if op == ble.OP_LIST:
            self._list()
        elif op == ble.OP_GET:
            self._get(*struct.unpack("<IIH", args))
        elif op == ble.OP_DELETE:
            self._delete(struct.unpack("<I", args)[0])
        elif op == ble.OP_SET_TIME:
            self._send("ctrl", ble.pack_ctrl(ble.SetTimeAck(self.config.now_us)))
        elif op == ble.OP_ABORT:
            self._xfer = None
            self._send("ctrl", ble.pack_ctrl(ble.AbortAck()))

    def _list(self) -> None:
        ids = sorted(self.notes)
        if not ids:
            return self._send("ctrl", ble.pack_ctrl(ble.ListEntry(0, 0, 0, 0, 0, 0, 0)))
        for i, fid in enumerate(ids):
            data = self.notes[fid]
            try:
                h = unpack_header(data[:HEADER_BYTES])
                codec, boot, start = h.codec, h.boot_id, h.start_us
            except FormatError:
                codec, boot, start = 255, 0, 0
            self._send("ctrl", ble.pack_ctrl(ble.ListEntry(i, len(ids), fid, len(data), codec, boot, start)))

    def _get(self, file_id: int, offset: int, credits: int) -> None:
        if file_id in self.busy:
            return self._status(ble.OP_GET, ble.STATUS_BUSY)
        if file_id not in self.notes:
            return self._status(ble.OP_GET, ble.STATUS_NOT_FOUND)
        data = self.notes[file_id]
        if offset > len(data):
            return self._status(ble.OP_GET, ble.STATUS_BAD_ARGS)
        self._xfer = None
        if self._read_fails(file_id, 0, offset):
            return self._status(ble.OP_GET, ble.STATUS_IO)
        self._xfer = _Transfer(file_id, len(data), offset, credits, zlib.crc32(data[:offset]))
        self._send("ctrl", ble.pack_ctrl(ble.GetAck(file_id, len(data))))

    def _delete(self, file_id: int) -> None:
        if file_id in self.busy or (self._xfer is not None and self._xfer.file_id == file_id):
            return self._status(ble.OP_DELETE, ble.STATUS_BUSY)
        if file_id not in self.notes:
            return self._status(ble.OP_DELETE, ble.STATUS_NOT_FOUND)
        del self.notes[file_id]
        self._send("ctrl", ble.pack_ctrl(ble.DeleteAck(file_id)))

    def pump(self) -> bool:
        x = self._xfer
        if not self._connected or x is None:
            return False
        if x.offset == x.size:
            self._xfer = None
            self._send("ctrl", ble.pack_ctrl(ble.TransferDone(x.file_id, x.crc)))
            return True
        if x.credits == 0:
            return False
        n = min(min(self._mtu - 5, MAX_PAYLOAD), x.size - x.offset)
        if self._read_fails(x.file_id, x.offset, x.offset + n):
            self._xfer = None
            self._send("ctrl", ble.pack_ctrl(ble.TransferFailed(ble.STATUS_IO)))
            return True
        chunk = self.notes[x.file_id][x.offset:x.offset + n]
        self._send("data", ble.pack_data_chunk(x.seq, chunk))
        x.crc = zlib.crc32(chunk, x.crc)
        x.offset += n
        x.seq = (x.seq + 1) & 0xFFFF
        x.credits -= 1
        return True

    def run_until_idle(self) -> None:
        while self.pump():
            pass
