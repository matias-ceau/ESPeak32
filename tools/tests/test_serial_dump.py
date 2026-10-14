import base64
import wave
from pathlib import Path

import pytest

from espeak32.cli import main
from espeak32.serial_dump import (
    DumpError,
    fetch_file,
    format_dump,
    parse_dump,
    parse_ls,
)

VEC = Path(__file__).resolve().parents[2] / "protocol" / "vectors"
DATA = (VEC / "tone_16k.adpcm.e32").read_bytes()


def noisy(lines):
    out = ["I (1234) rec: hello", "boot: something"]
    for i, ln in enumerate(lines):
        out.append(ln)
        if i % 7 == 0:
            out.append("W (99) rec: noise between lines")
    return out


def test_parse_dump_roundtrip_with_log_noise():
    assert parse_dump(noisy(format_dump(DATA, 1))) == DATA


def test_parse_dump_rejects_bad_base64():
    lines = format_dump(DATA, 1)
    lines[2] = "E32DUMP D !!!notbase64!!!"
    with pytest.raises(DumpError):
        parse_dump(lines)


def test_parse_dump_rejects_missing_end():
    with pytest.raises(DumpError):
        parse_dump(format_dump(DATA, 1)[:-1])


def test_parse_dump_rejects_length_mismatch():
    lines = format_dump(DATA, 1)
    del lines[2]  # drop one data line, keeping BEGIN and END
    with pytest.raises(DumpError):
        parse_dump(lines)


def test_parse_dump_rejects_crc_mismatch():
    lines = format_dump(DATA, 1)
    raw = bytearray(base64.b64decode(lines[1].split(" ", 2)[2]))
    raw[0] ^= 0x01
    lines[1] = "E32DUMP D " + base64.b64encode(bytes(raw)).decode()
    with pytest.raises(DumpError, match="CRC"):
        parse_dump(lines)


def test_parse_dump_reports_device_error():
    with pytest.raises(DumpError, match="busy"):
        parse_dump(["E32DUMP ERR busy"])


def test_parse_ls():
    assert parse_ls(["x", "E32LS 1 8226", "E32LS 2 120", "E32LS END"]) == [(1, 8226), (2, 120)]
    assert parse_ls(["E32LS END"]) == []


class FakeSerial:
    def __init__(self, lines):
        self.lines = [ln.encode() + b"\n" for ln in lines]
        self.written = b""

    def write(self, data):
        self.written += data

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def test_fetch_file_sends_command():
    port = FakeSerial(format_dump(DATA, 3))
    assert fetch_file(port, 3) == DATA
    assert port.written == b"dump 3\n"


def test_cli_dump_writes_file_and_wav(tmp_path):
    port = FakeSerial(noisy(format_dump(DATA, 1)))
    out, wav = tmp_path / "n.e32", tmp_path / "n.wav"
    rc = main(["dump", "--port", "X", "--id", "1", "-o", str(out), "--decode", str(wav)],
              open_port=lambda name, baud: port)
    assert rc == 0 and out.read_bytes() == DATA
    with wave.open(str(wav)) as w:
        assert w.getnframes() == 16000


def test_cli_dump_corruption_exits_3_and_writes_nothing(tmp_path):
    lines = format_dump(DATA, 1)
    lines[1] = "E32DUMP D AAAA"
    out = tmp_path / "n.e32"
    rc = main(["dump", "--port", "X", "--id", "1", "-o", str(out)],
              open_port=lambda name, baud: FakeSerial(lines))
    assert rc == 3 and not out.exists()
