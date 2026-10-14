"""`.e32` file container: 32-byte header followed by `[u16 len][payload]` frames."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

CODEC_PCM16, CODEC_ADPCM, CODEC_OPUS = 0, 1, 2
HEADER_BYTES = 32
UNFINALIZED = 0xFFFFFFFF
MAGIC = b"E32A"
_HEADER = struct.Struct("<4sBBHIIQII")


class FormatError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    codec: int
    sample_rate: int
    file_id: int
    boot_id: int
    start_us: int
    sample_count: int
    payload_crc32: int
    version: int = 1


@dataclass(frozen=True)
class E32File:
    header: Header
    frames: list[bytes]
    finalized: bool
    crc_ok: bool | None
    truncated: bool


def pack_header(h: Header) -> bytes:
    return _HEADER.pack(
        MAGIC, h.version, h.codec, h.sample_rate, h.file_id, h.boot_id,
        h.start_us, h.sample_count, h.payload_crc32,
    )


def unpack_header(b: bytes) -> Header:
    if len(b) < HEADER_BYTES:
        raise FormatError("header too short")
    magic, version, codec, rate, file_id, boot_id, start_us, count, crc = _HEADER.unpack(
        b[:HEADER_BYTES]
    )
    if magic != MAGIC:
        raise FormatError("bad magic")
    if version != 1:
        raise FormatError(f"unsupported version {version}")
    return Header(codec, rate, file_id, boot_id, start_us, count, crc, version)


def pack_frame(payload: bytes) -> bytes:
    return struct.pack("<H", len(payload)) + payload


def build(codec: int, sample_rate: int, file_id: int, boot_id: int, start_us: int,
          sample_count: int, frames: list[bytes]) -> bytes:
    body = b"".join(pack_frame(f) for f in frames)
    header = Header(codec, sample_rate, file_id, boot_id, start_us, sample_count,
                    zlib.crc32(body))
    return pack_header(header) + body


def parse(data: bytes) -> E32File:
    header = unpack_header(data)
    pos = HEADER_BYTES
    frames: list[bytes] = []
    while pos + 2 <= len(data):
        (n,) = struct.unpack_from("<H", data, pos)
        if pos + 2 + n > len(data):
            break
        frames.append(data[pos + 2 : pos + 2 + n])
        pos += 2 + n
    truncated = pos != len(data)
    finalized = header.sample_count != UNFINALIZED
    crc_ok = (zlib.crc32(data[HEADER_BYTES:pos]) == header.payload_crc32) if finalized else None
    return E32File(header, frames, finalized, crc_ok, truncated)
