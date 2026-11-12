"""`.e32` file container: 32-byte header, `[u16 len][payload]` frames, and (version 2) an end record.

Version 1 finalizes by rewriting the header's sample count and CRC. Version 2 never rewrites the header: it appends a
14-byte end record `[u16 0xFFFF]["E32E"][u32 sample_count][u32 payload_crc32]`, because LittleFS copies a whole file to
change its first bytes. Readers accept both versions; the device writes version 2.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

CODEC_PCM16, CODEC_ADPCM, CODEC_OPUS = 0, 1, 2
HEADER_BYTES = 32
UNFINALIZED = 0xFFFFFFFF
MAGIC = b"E32A"
END_MARKER = 0xFFFF  # never a frame length (frames are at most 512 bytes)
END_MAGIC = b"E32E"
END_BYTES = 14
VERSIONS = (1, 2)
CURRENT_VERSION = 2
_HEADER = struct.Struct("<4sBBHIIQII")
_END = struct.Struct("<H4sII")


class FormatError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    codec: int
    sample_rate: int
    file_id: int
    boot_id: int
    start_us: int
    sample_count: int  # version 2: always UNFINALIZED (the end record holds the real value)
    payload_crc32: int  # version 2: always 0
    version: int = CURRENT_VERSION


@dataclass(frozen=True)
class E32File:
    header: Header
    frames: list[bytes]
    finalized: bool
    crc_ok: bool | None
    truncated: bool  # bytes after the last complete frame (or after the end record) were ignored
    sample_count: int  # from the header (v1) or the end record (v2); UNFINALIZED if not finalized
    payload_crc32: int  # 0 if not finalized


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
    if version not in VERSIONS:
        raise FormatError(f"unsupported version {version}")
    return Header(codec, rate, file_id, boot_id, start_us, count, crc, version)


def pack_frame(payload: bytes) -> bytes:
    return struct.pack("<H", len(payload)) + payload


def pack_end(sample_count: int, payload_crc32: int) -> bytes:
    return _END.pack(END_MARKER, END_MAGIC, sample_count, payload_crc32)


def build(codec: int, sample_rate: int, file_id: int, boot_id: int, start_us: int,
          sample_count: int, frames: list[bytes], version: int = CURRENT_VERSION) -> bytes:
    """A finalized note."""
    body = b"".join(pack_frame(f) for f in frames)
    crc = zlib.crc32(body)
    if version == 1:
        return pack_header(Header(codec, sample_rate, file_id, boot_id, start_us, sample_count, crc, 1)) + body
    if version == 2:
        header = Header(codec, sample_rate, file_id, boot_id, start_us, UNFINALIZED, 0, 2)
        return pack_header(header) + body + pack_end(sample_count, crc)
    raise FormatError(f"unsupported version {version}")


def parse(data: bytes) -> E32File:
    header = unpack_header(data)
    pos = HEADER_BYTES
    frames: list[bytes] = []
    end: tuple[int, int] | None = None
    payload_end = None
    while pos + 2 <= len(data):
        (n,) = struct.unpack_from("<H", data, pos)
        if n == END_MARKER and header.version >= 2:
            if pos + END_BYTES <= len(data) and data[pos + 2 : pos + 6] == END_MAGIC:
                _, _, count, crc = _END.unpack_from(data, pos)
                end, payload_end = (count, crc), pos
                pos += END_BYTES
            break  # an incomplete or garbled end record leaves the note unfinalized
        if pos + 2 + n > len(data):
            break
        frames.append(data[pos + 2 : pos + 2 + n])
        pos += 2 + n
    truncated = pos != len(data)
    if header.version == 1:
        finalized = header.sample_count != UNFINALIZED
        count, crc, payload_end = header.sample_count, header.payload_crc32, pos
    else:
        finalized = end is not None
        count, crc = end if end is not None else (UNFINALIZED, 0)
    crc_ok = (zlib.crc32(data[HEADER_BYTES:payload_end]) == crc) if finalized else None
    return E32File(header, frames, finalized, crc_ok, truncated, count if finalized else UNFINALIZED,
                   crc if finalized else 0)
