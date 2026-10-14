"""`espeak32` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .decode import decode_e32
from .wav import write_wav


def _cmd_decode(args) -> int:
    result = decode_e32(Path(args.input).read_bytes())
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if result.crc_ok is False and not args.force:
        print("error: CRC mismatch (use --force to decode anyway)", file=sys.stderr)
        return 2
    write_wav(args.output, result.samples, result.sample_rate)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="espeak32")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decode", help="decode an .e32 file to WAV")
    d.add_argument("input")
    d.add_argument("-o", "--output", required=True)
    d.add_argument("--force", action="store_true", help="write output even if the CRC mismatches")
    d.set_defaults(func=_cmd_decode)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
