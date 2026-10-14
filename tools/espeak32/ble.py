"""BLE message codec (see protocol/PROTOCOL.md)."""

from __future__ import annotations

import dataclasses
import json
import struct
import sys
from dataclasses import dataclass

SERVICE_UUID = "8f05e6c5-7b93-4a53-b175-b3416b3a0d20"
INFO_UUID = "8f05e6c6-7b93-4a53-b175-b3416b3a0d20"
CTRL_UUID = "8f05e6c7-7b93-4a53-b175-b3416b3a0d20"
DATA_UUID = "8f05e6c8-7b93-4a53-b175-b3416b3a0d20"

OP_LIST, OP_GET, OP_CREDIT, OP_DELETE, OP_SET_TIME, OP_ABORT = 1, 2, 3, 4, 5, 6
EV_TRANSFER_DONE = 0x83
(STATUS_OK, STATUS_UNKNOWN_OPCODE, STATUS_BAD_ARGS, STATUS_NOT_FOUND,
 STATUS_BUSY, STATUS_MTU, STATUS_IO) = range(7)

_INFO = struct.Struct("<BBBBBBIIQI")
_LIST = struct.Struct("<HHIIBIQ")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Info:
    proto_version: int
    battery_pct: int
    fw: tuple[int, int, int]
    codecs_mask: int
    free_bytes: int
    boot_id: int
    ticks_us: int
    file_count: int


@dataclass(frozen=True)
class ListEntry:
    index: int
    total: int
    file_id: int
    size: int
    codec: int
    boot_id: int
    start_us: int


@dataclass(frozen=True)
class GetAck:
    file_id: int
    total_size: int


@dataclass(frozen=True)
class DeleteAck:
    file_id: int


@dataclass(frozen=True)
class SetTimeAck:
    ticks_us: int


@dataclass(frozen=True)
class AbortAck:
    pass


@dataclass(frozen=True)
class TransferDone:
    file_id: int
    file_crc32: int


@dataclass(frozen=True)
class ErrorAck:
    op: int
    status: int


CtrlMessage = ListEntry | GetAck | DeleteAck | SetTimeAck | AbortAck | TransferDone | ErrorAck


def pack_info(i: Info) -> bytes:
    return _INFO.pack(i.proto_version, i.battery_pct, *i.fw, i.codecs_mask,
                      i.free_bytes, i.boot_id, i.ticks_us, i.file_count)


def unpack_info(b: bytes) -> Info:
    if len(b) != _INFO.size:
        raise ProtocolError("bad INFO length")
    v, bat, major, minor, patch, mask, free, boot, ticks, count = _INFO.unpack(b)
    return Info(v, bat, (major, minor, patch), mask, free, boot, ticks, count)


def req_list() -> bytes:
    return bytes([OP_LIST])


def req_get(file_id: int, offset: int, credits: int) -> bytes:
    return struct.pack("<BIIH", OP_GET, file_id, offset, credits)


def req_credit(credits: int) -> bytes:
    return struct.pack("<BH", OP_CREDIT, credits)


def req_delete(file_id: int) -> bytes:
    return struct.pack("<BI", OP_DELETE, file_id)


def req_set_time(unix_ms: int) -> bytes:
    return struct.pack("<BQ", OP_SET_TIME, unix_ms)


def req_abort() -> bytes:
    return bytes([OP_ABORT])


def pack_ctrl(msg: CtrlMessage) -> bytes:
    if isinstance(msg, ErrorAck):
        return bytes([msg.op | 0x80, msg.status])
    if isinstance(msg, ListEntry):
        if msg.total == 0:
            return bytes([0x80 | OP_LIST, 0]) + struct.pack("<HH", 0, 0)
        return bytes([0x80 | OP_LIST, 0]) + _LIST.pack(*dataclasses.astuple(msg))
    if isinstance(msg, GetAck):
        return bytes([0x80 | OP_GET, 0]) + struct.pack("<II", msg.file_id, msg.total_size)
    if isinstance(msg, DeleteAck):
        return bytes([0x80 | OP_DELETE, 0]) + struct.pack("<I", msg.file_id)
    if isinstance(msg, SetTimeAck):
        return bytes([0x80 | OP_SET_TIME, 0]) + struct.pack("<Q", msg.ticks_us)
    if isinstance(msg, AbortAck):
        return bytes([0x80 | OP_ABORT, 0])
    if isinstance(msg, TransferDone):
        return bytes([EV_TRANSFER_DONE, 0]) + struct.pack("<II", msg.file_id, msg.file_crc32)
    raise ProtocolError(f"cannot pack {msg!r}")


def _body(body: bytes, size: int) -> bytes:
    if len(body) != size:
        raise ProtocolError("bad body length")
    return body


def decode_ctrl(msg: bytes) -> CtrlMessage:
    if len(msg) < 2 or not msg[0] & 0x80:
        raise ProtocolError("bad CTRL notification")
    op, status, body = msg[0] & 0x7F, msg[1], msg[2:]
    if op not in (OP_LIST, OP_GET, OP_CREDIT, OP_DELETE, OP_SET_TIME, OP_ABORT):
        raise ProtocolError(f"unknown opcode {op}")
    if status != STATUS_OK:
        return ErrorAck(op, status)
    if op == OP_LIST:
        if len(body) == 4:
            index, total = struct.unpack("<HH", body)
            if total != 0:
                raise ProtocolError("bad body length")
            return ListEntry(0, 0, 0, 0, 0, 0, 0)
        return ListEntry(*_LIST.unpack(_body(body, _LIST.size)))
    if op == OP_GET:
        return GetAck(*struct.unpack("<II", _body(body, 8)))
    if op == OP_CREDIT:  # 0x83 is the TRANSFER_DONE event; CREDIT itself has no response
        return TransferDone(*struct.unpack("<II", _body(body, 8)))
    if op == OP_DELETE:
        return DeleteAck(*struct.unpack("<I", _body(body, 4)))
    if op == OP_SET_TIME:
        return SetTimeAck(*struct.unpack("<Q", _body(body, 8)))
    if op == OP_ABORT:
        _body(body, 0)
        return AbortAck()
    raise ProtocolError(f"unexpected notification for opcode {op}")


def pack_data_chunk(seq: int, payload: bytes) -> bytes:
    if not 0 <= seq <= 0xFFFF:
        raise ProtocolError("seq out of range")
    return struct.pack("<H", seq) + payload


def unpack_data_chunk(b: bytes) -> tuple[int, bytes]:
    if len(b) < 2:
        raise ProtocolError("chunk too short")
    return struct.unpack_from("<H", b)[0], b[2:]


def generate_vectors() -> list[dict]:
    info = Info(1, 87, (0, 1, 0), 0b011, 2_500_000, 5, 1_000_000, 3)
    ctrl = [
        ListEntry(0, 2, 5, 1000, 1, 3, 77), ListEntry(0, 0, 0, 0, 0, 0, 0), GetAck(5, 1000),
        DeleteAck(5), SetTimeAck(123456789), AbortAck(), TransferDone(5, 0xCAFEBABE),
        ErrorAck(OP_GET, STATUS_NOT_FOUND),
    ]
    info_dict = dataclasses.asdict(info)
    info_dict["fw"] = list(info_dict["fw"])  # JSON has no tuples
    out = [{"name": "info", "hex": pack_info(info).hex(), "decoded": info_dict}]
    for name, b in [("req_list", req_list()), ("req_get", req_get(7, 0x100, 8)),
                    ("req_credit", req_credit(3)), ("req_delete", req_delete(9)),
                    ("req_set_time", req_set_time(0x0102030405060708)), ("req_abort", req_abort())]:
        out.append({"name": name, "hex": b.hex(), "decoded": None})
    for m in ctrl:
        out.append({"name": "ctrl_" + type(m).__name__, "hex": pack_ctrl(m).hex(),
                    "decoded": dataclasses.asdict(m)})
    out.append({"name": "data_chunk", "hex": pack_data_chunk(65535, b"ab").hex(),
                "decoded": {"seq": 65535, "payload": "6162"}})
    return out


if __name__ == "__main__":
    with open(sys.argv[1], "w") as fh:
        json.dump(generate_vectors(), fh, indent=2)
        fh.write("\n")
