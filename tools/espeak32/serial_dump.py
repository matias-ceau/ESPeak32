"""Parse and drive the firmware's serial `ls` / `dump` / `rm` console commands."""

from __future__ import annotations

import base64
import binascii
import zlib
from typing import Iterable

CHUNK = 90


class DumpError(RuntimeError):
    pass


def format_dump(data: bytes, file_id: int) -> list[str]:
    """The firmware's dump output for `data` (used by tests and simulators)."""
    lines = [f"E32DUMP BEGIN {file_id} {len(data)}"]
    for i in range(0, len(data), CHUNK):
        lines.append("E32DUMP D " + base64.b64encode(data[i : i + CHUNK]).decode())
    lines.append(f"E32DUMP END {zlib.crc32(data):08x}")
    return lines


def parse_dump(lines: Iterable[str]) -> bytes:
    expected: int | None = None
    buf = bytearray()
    end_crc: int | None = None
    for raw in lines:
        line = raw.strip()
        if not line.startswith("E32DUMP "):
            continue
        parts = line.split(" ", 3)
        kind = parts[1]
        if kind == "ERR":
            raise DumpError(f"device error: {parts[2] if len(parts) > 2 else 'unknown'}")
        if kind == "BEGIN":
            expected = int(parts[3])
        elif kind == "D":
            try:
                buf += base64.b64decode(parts[2], validate=True)
            except (binascii.Error, IndexError) as e:
                raise DumpError(f"bad base64 data line: {e}") from e
        elif kind == "END":
            end_crc = int(parts[2], 16)
            break
    if expected is None or end_crc is None:
        raise DumpError("dump incomplete (missing BEGIN or END)")
    if len(buf) != expected:
        raise DumpError(f"length mismatch: got {len(buf)} bytes, expected {expected}")
    if zlib.crc32(bytes(buf)) != end_crc:
        raise DumpError("CRC mismatch")
    return bytes(buf)


def parse_ls(lines: Iterable[str]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for raw in lines:
        parts = raw.split()
        if len(parts) >= 2 and parts[0] == "E32LS":
            if parts[1] == "END":
                break
            out.append((int(parts[1]), int(parts[2])))
    return out


def _read_until(port, stop) -> list[str]:
    lines: list[str] = []
    while True:
        raw = port.readline()
        if not raw:
            break
        line = raw.decode(errors="replace").strip()
        lines.append(line)
        if stop(line):
            break
    return lines


def fetch_ls(port) -> list[tuple[int, int]]:
    port.write(b"ls\n")
    return parse_ls(_read_until(port, lambda ln: ln.startswith("E32LS END")))


def fetch_file(port, file_id: int) -> bytes:
    port.write(f"dump {file_id}\n".encode())
    lines = _read_until(port, lambda ln: ln.startswith(("E32DUMP END", "E32DUMP ERR")))
    return parse_dump(lines)


def remove_file(port, file_id: int) -> None:
    port.write(f"rm {file_id}\n".encode())
    lines = _read_until(port, lambda ln: ln.startswith("E32RM"))
    for ln in lines:
        if ln.startswith("E32RM OK"):
            return
        if ln.startswith("E32RM ERR"):
            raise DumpError(f"device error: {ln.split(' ', 2)[2]}")
    raise DumpError("no reply to rm")
