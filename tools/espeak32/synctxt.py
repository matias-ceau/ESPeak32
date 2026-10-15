"""Session transcripts for the BLE transfer engine: protocol/vectors/sync.txt.

Grammar (one directive per line): SCENARIO name | CONFIG k=v ... | FILE id vector | BUSY id vector |
FAILREAD id offset | CONNECT mtu | MTU mtu | SEND hex | INFO | DISCONNECT | EXPECT CTRL|DATA|INFO hex | END.
After CONNECT, MTU and SEND the harness pumps until idle; the EXPECT lines that follow an action list all of its
outputs in order. Run `python -m espeak32.synctxt protocol/vectors/sync.txt` to regenerate.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import ble
from .device_model import DeviceConfig, DeviceModel

TONE, EMPTY = "tone_16k.adpcm.e32", "empty.e32"
TWO = {1: TONE, 2: EMPTY}
Step = tuple  # ("connect", mtu) | ("mtu", mtu) | ("send", bytes) | ("info",) | ("disconnect",)


@dataclass
class Scenario:
    name: str
    steps: list[Step]
    files: dict[int, str] = field(default_factory=lambda: dict(TWO))
    busy: dict[int, str] = field(default_factory=dict)
    fail_read: tuple[int, int] | None = None
    config: DeviceConfig = field(default_factory=DeviceConfig)


@dataclass
class ParsedScenario:
    name: str
    lines: list[str]


def _s(*reqs: bytes) -> list[Step]:
    return [("send", r) for r in reqs]


C64: list[Step] = [("connect", 64)]
G, CR = ble.req_get, ble.req_credit

SCENARIOS: list[Scenario] = [
    Scenario("info", C64 + [("info",)]),
    Scenario("set_time", C64 + _s(ble.req_set_time(1_700_000_000_000))),
    Scenario("list_two", C64 + _s(ble.req_list()) + [("info",)], busy={3: EMPTY}),
    Scenario("list_empty", C64 + _s(ble.req_list()), files={}),
    Scenario("get_full_multi_credit", [("connect", 247)] + _s(G(1, 0, 10), CR(10), CR(10), CR(10))),
    Scenario("get_zero_credits_then_credit", C64 + _s(G(2, 0, 0), CR(1))),
    Scenario("get_resume_offset", C64 + _s(G(1, 1000, 4), CR(40), CR(40), CR(40))),
    Scenario("get_offset_equals_size", C64 + _s(G(2, 32, 1))),
    Scenario("get_offset_beyond_size", C64 + _s(G(2, 33, 1))),
    Scenario("get_unknown", C64 + _s(G(9, 0, 1))),
    Scenario("get_busy", C64 + _s(G(3, 0, 1)), busy={3: EMPTY}),
    Scenario("get_replaces_active", C64 + _s(G(1, 0, 2), G(2, 0, 5))),
    Scenario("abort_mid_transfer", C64 + _s(G(1, 0, 2), ble.req_abort(), CR(5))),
    Scenario("credit_without_transfer", C64 + _s(CR(5)) + [("info",)]),
    Scenario("delete_ok_then_list", C64 + _s(ble.req_delete(2), ble.req_list())),
    Scenario("delete_unknown", C64 + _s(ble.req_delete(9))),
    Scenario("delete_busy_recording", C64 + _s(ble.req_delete(3)), busy={3: EMPTY}),
    Scenario("delete_busy_transferring", C64 + _s(G(1, 0, 1), ble.req_delete(1))),
    Scenario("unknown_opcode", C64 + _s(b"\x7f")),
    Scenario("bad_length", C64 + _s(G(1, 0, 1)[:-1] + b"\x00\x00")),
    Scenario("mtu_too_small", [("connect", 23)] + _s(ble.req_list(), CR(5)) + [("mtu", 64)] + _s(ble.req_list())),
    Scenario("disconnect_resume", C64 + _s(G(1, 0, 10)) + [("disconnect",)] + C64 + _s(G(1, 10 * 59, 200))),
    Scenario("read_failure", C64 + _s(G(1, 0, 100)), fail_read=(1, 2000)),
]


def _config_line(c: DeviceConfig) -> str:
    fw = ".".join(map(str, c.fw))
    return (f"CONFIG boot_id={c.boot_id} fw={fw} codecs={c.codecs_mask} battery={c.battery_pct} "
            f"free={c.free_bytes} now_us={c.now_us}")


def _render_one(sc: Scenario, vector_dir: Path) -> list[str]:
    load = lambda m: {i: (vector_dir / n).read_bytes() for i, n in m.items()}  # noqa: E731
    dev = DeviceModel(load(sc.files), sc.config, load(sc.busy))
    dev.fail_read_at = sc.fail_read
    out = [f"SCENARIO {sc.name}", _config_line(sc.config)]
    out += [f"FILE {i} {n}" for i, n in sorted(sc.files.items())]
    out += [f"BUSY {i} {n}" for i, n in sorted(sc.busy.items())]
    if sc.fail_read:
        out.append(f"FAILREAD {sc.fail_read[0]} {sc.fail_read[1]}")
    for step in sc.steps:
        kind = step[0]
        dev.outputs.clear()
        if kind == "info":
            out += ["INFO", f"EXPECT INFO {dev.info().hex()}"]
            continue
        if kind == "connect":
            out.append(f"CONNECT {step[1]}")
            dev.connect(step[1])
        elif kind == "mtu":
            out.append(f"MTU {step[1]}")
            dev.set_mtu(step[1])
        elif kind == "send":
            out.append(f"SEND {step[1].hex()}")
            dev.request(step[1])
        elif kind == "disconnect":
            out.append("DISCONNECT")
            dev.disconnect()
        dev.run_until_idle()
        out += [f"EXPECT {ch.upper()} {msg.hex()}" for ch, msg in dev.outputs]
    out.append("END")
    return out


def render(scenarios: list[Scenario], vector_dir: Path) -> str:
    lines: list[str] = []
    for sc in scenarios:
        lines += _render_one(sc, vector_dir)
    return "\n".join(lines) + "\n"


def parse(text: str) -> list[ParsedScenario]:
    out: list[ParsedScenario] = []
    cur: ParsedScenario | None = None
    for line in text.splitlines():
        if line.startswith("SCENARIO "):
            cur = ParsedScenario(line.split(" ", 1)[1], [])
        elif line == "END":
            if cur is None:
                raise ValueError("END without SCENARIO")
            out.append(cur)
            cur = None
        elif cur is not None:
            cur.lines.append(line)
        elif line:
            raise ValueError(f"line outside a scenario: {line!r}")
    if cur is not None:
        raise ValueError(f"scenario {cur.name} has no END")
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.write_text(render(SCENARIOS, target.parent))
