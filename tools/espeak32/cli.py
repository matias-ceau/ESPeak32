"""`espeak32` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from .decode import decode_e32
from .serial_dump import DumpError, fetch_file, fetch_ls, remove_file
from .wav import write_wav


def _cmd_decode(args, open_port=None) -> int:
    result = decode_e32(Path(args.input).read_bytes())
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if result.crc_ok is False and not args.force:
        print("error: CRC mismatch (use --force to decode anyway)", file=sys.stderr)
        return 2
    write_wav(args.output, result.samples, result.sample_rate)
    return 0


def _default_open_port(name: str, baud: int):
    import serial

    return serial.Serial(name, baudrate=baud, timeout=2)


def _cmd_ls(args, open_port) -> int:
    try:
        for file_id, size in fetch_ls(open_port(args.port, args.baud)):
            print(f"{file_id}\t{size}")
    except DumpError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    return 0


def _cmd_dump(args, open_port) -> int:
    try:
        data = fetch_file(open_port(args.port, args.baud), args.id)
    except DumpError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    Path(args.output).write_bytes(data)
    if args.decode:
        result = decode_e32(data)
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)
        write_wav(args.decode, result.samples, result.sample_rate)
    return 0


def _cmd_rm(args, open_port) -> int:
    try:
        remove_file(open_port(args.port, args.baud), args.id)
    except DumpError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    return 0


def _add_port(p) -> None:
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="espeak32")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help="decode an .e32 file to WAV")
    d.add_argument("input")
    d.add_argument("-o", "--output", required=True)
    d.add_argument("--force", action="store_true", help="write output even if the CRC mismatches")
    d.set_defaults(func=_cmd_decode)

    ls = sub.add_parser("ls", help="list notes on the device")
    _add_port(ls)
    ls.set_defaults(func=_cmd_ls)

    dp = sub.add_parser("dump", help="download a note over serial")
    _add_port(dp)
    dp.add_argument("--id", type=int, required=True)
    dp.add_argument("-o", "--output", required=True)
    dp.add_argument("--decode", metavar="WAV", help="also decode to this WAV file")
    dp.set_defaults(func=_cmd_dump)

    rm = sub.add_parser("rm", help="delete a note on the device")
    _add_port(rm)
    rm.add_argument("--id", type=int, required=True)
    rm.set_defaults(func=_cmd_rm)
    return p


def main(argv: Sequence[str] | None = None,
         open_port: Callable[[str, int], object] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, open_port or _default_open_port)


if __name__ == "__main__":
    sys.exit(main())
