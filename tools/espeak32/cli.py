"""`espeak32` command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from . import ble
from .ble_transport import DeviceNotFound
from .codec import UnsupportedCodec
from .container import FormatError
from .decode import decode_e32
from .serial_dump import DumpError, fetch_file, fetch_ls, remove_file
from .sync import LinkLost, NoteSkipped, SyncClient, SyncError, sync_all
from .wav import write_wav


def _decode_to_wav(data: bytes, output: str, force: bool) -> int:
    try:
        result = decode_e32(data)
    except (FormatError, UnsupportedCodec) as e:
        print(f"error: cannot decode: {e}", file=sys.stderr)
        return 4
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if result.crc_ok is False and not force:
        print("error: CRC mismatch (use --force to decode anyway)", file=sys.stderr)
        return 2
    write_wav(output, result.samples, result.sample_rate)
    return 0


def _cmd_decode(args, open_port=None) -> int:
    return _decode_to_wav(Path(args.input).read_bytes(), args.output, args.force)


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
        return _decode_to_wav(data, args.decode, False)
    return 0


def _cmd_rm(args, open_port) -> int:
    try:
        remove_file(open_port(args.port, args.baud), args.id)
    except DumpError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    return 0


# ---- BLE ----

async def _with_client(args, body):
    t = await args.connect_ble(args.address, args.pair)
    try:
        return await body(SyncClient(t, args.window))
    finally:
        await t.close()


async def _ble_info(args) -> int:
    async def body(c: SyncClient) -> int:
        i = await c.info()
        battery = "unknown" if i.battery_pct == 255 else f"{i.battery_pct} %"
        print(f"firmware: {'.'.join(map(str, i.fw))}\nprotocol: {i.proto_version}\nbattery: {battery}\n"
              f"free: {i.free_bytes} bytes\nnotes: {i.file_count}\nboot_id: {i.boot_id}")
        return 0
    return await _with_client(args, body)


async def _ble_list(args) -> int:
    async def body(c: SyncClient) -> int:
        for e in await c.list():
            print(f"{e.file_id}\t{e.size}\tcodec={e.codec}\tboot={e.boot_id}\tstart_us={e.start_us}")
        return 0
    return await _with_client(args, body)


async def _ble_get(args) -> int:
    async def body(c: SyncClient) -> int:
        entry = next((e for e in await c.list() if e.file_id == args.id), None)
        if entry is None:
            print(f"error: note {args.id} not on the device", file=sys.stderr)
            return 3
        part = Path(args.output + ".part")
        try:
            await c.fetch(entry, part)
        except NoteSkipped as e:
            print(f"error: note {args.id} not fetched ({type(e).__name__})", file=sys.stderr)
            return 3
        os.replace(part, args.output)
        return 0
    return await _with_client(args, body)


async def _ble_rm(args) -> int:
    async def body(c: SyncClient) -> int:
        if not await c.delete(args.id):
            print(f"error: note {args.id} is being recorded", file=sys.stderr)
            return 3
        return 0
    return await _with_client(args, body)


async def _ble_sync(args) -> int:
    out = Path(args.out)
    report = await sync_all(lambda: args.connect_ble(args.address, args.pair), out, args.delete,
                            lambda: int(time.time() * 1000), args.window)
    for fid, why in report.skipped:
        print(f"warning: note {fid} skipped: {why}", file=sys.stderr)
    print(f"fetched {len(report.fetched)}, deleted {len(report.deleted)}, skipped {len(report.skipped)}")
    if args.wav:
        for e32 in sorted(out.glob("*.e32")):
            wav = e32.with_suffix(".wav")
            if not wav.exists() and _decode_to_wav(e32.read_bytes(), str(wav), False) != 0:
                print(f"warning: {e32.name} not decoded", file=sys.stderr)
    return 0


async def _ble_scan(args) -> int:
    for address, name, rssi in await args.scan_ble(args.timeout):
        print(f"{address}\t{name}\t{rssi}")
    return 0


def _cmd_ble(args, open_port=None) -> int:
    try:
        return asyncio.run(args.ble_func(args))
    except DeviceNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except (SyncError, LinkLost, ble.ProtocolError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


def _add_ble(sub) -> None:
    b = sub.add_parser("ble", help="talk to the device over Bluetooth LE (needs tools[ble])")
    b.set_defaults(func=_cmd_ble)
    bsub = b.add_subparsers(dest="ble_cmd", required=True)

    def cmd(name, func, help):
        p = bsub.add_parser(name, help=help)
        p.add_argument("--address", help="device address (default: first ESPeak32 found)")
        p.add_argument("--window", type=int, default=16, help="DATA chunks in flight (credit window)")
        p.add_argument("--pair", action="store_true", help="pair explicitly before syncing")
        p.set_defaults(ble_func=func)
        return p

    s = bsub.add_parser("scan", help="list advertising ESPeak32 devices")
    s.add_argument("--timeout", type=float, default=5.0)
    s.set_defaults(ble_func=_ble_scan)
    cmd("info", _ble_info, "show device information")
    cmd("list", _ble_list, "list notes on the device")
    g = cmd("get", _ble_get, "download one note")
    g.add_argument("--id", type=int, required=True)
    g.add_argument("-o", "--output", required=True)
    r = cmd("rm", _ble_rm, "delete one note on the device")
    r.add_argument("--id", type=int, required=True)
    y = cmd("sync", _ble_sync, "download every note (resumable); optionally delete them from the device")
    y.add_argument("--out", required=True, help="directory for .e32 files and clock.json")
    y.add_argument("--delete", action="store_true", help="delete each note once it is stored and verified")
    y.add_argument("--wav", action="store_true", help="also decode every note to WAV")


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
    _add_ble(sub)
    return p


def _default_connect_ble(address, pair):
    from .ble_transport import connect_bleak

    return connect_bleak(address, pair)


def _default_scan_ble(timeout):
    from .ble_transport import scan_bleak

    return scan_bleak(timeout)


def main(argv: Sequence[str] | None = None,
         open_port: Callable[[str, int], object] | None = None,
         connect_ble: Callable | None = None, scan_ble: Callable | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.connect_ble = connect_ble or _default_connect_ble
    args.scan_ble = scan_ble or _default_scan_ble
    return args.func(args, open_port or _default_open_port)


if __name__ == "__main__":
    sys.exit(main())
