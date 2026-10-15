import sys
import wave
from pathlib import Path

from espeak32.ble_transport import DeviceNotFound
from espeak32.cli import main
from espeak32.device_model import DeviceModel
from espeak32.sync import ModelTransport

VEC = Path(__file__).resolve().parents[2] / "protocol" / "vectors"
TONE = (VEC / "tone_16k.adpcm.e32").read_bytes()
EMPTY = (VEC / "empty.e32").read_bytes()


def fake_connect(dev):
    async def connect(address, pair):
        return ModelTransport(dev, mtu=64)

    return connect


async def not_found(address, pair):
    raise DeviceNotFound("no ESPeak32 advertising nearby")


def test_cli_ble_list_prints_notes(capsys):
    dev = DeviceModel({1: TONE, 2: EMPTY})
    assert main(["ble", "list"], connect_ble=fake_connect(dev)) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [ln.split("\t")[:2] for ln in lines] == [["1", "8288"], ["2", "32"]]


def test_cli_ble_info(capsys):
    dev = DeviceModel({1: TONE, 2: EMPTY})
    assert main(["ble", "info"], connect_ble=fake_connect(dev)) == 0
    out = capsys.readouterr().out
    assert "notes: 2" in out and "battery: unknown" in out and "firmware: 0.2.0" in out


def test_cli_ble_sync_writes_files_and_wav(tmp_path):
    dev = DeviceModel({1: TONE, 2: EMPTY})
    assert main(["ble", "sync", "--out", str(tmp_path), "--wav"], connect_ble=fake_connect(dev)) == 0
    wavs = sorted(tmp_path.glob("*.wav"))
    assert len(wavs) == 2
    frames = sorted(wave.open(str(w)).getnframes() for w in wavs)
    assert frames == [0, 16000]
    assert set(dev.notes) == {1, 2}  # kept without --delete


def test_cli_ble_sync_delete_flag(tmp_path):
    dev = DeviceModel({1: TONE, 2: EMPTY})
    assert main(["ble", "sync", "--out", str(tmp_path), "--delete"], connect_ble=fake_connect(dev)) == 0
    assert dev.notes == {}


def test_cli_ble_get_and_rm(tmp_path):
    dev = DeviceModel({1: TONE, 2: EMPTY})
    out = tmp_path / "n.e32"
    assert main(["ble", "get", "--id", "1", "-o", str(out)], connect_ble=fake_connect(dev)) == 0
    assert out.read_bytes() == TONE
    assert main(["ble", "rm", "--id", "1"], connect_ble=fake_connect(dev)) == 0
    assert set(dev.notes) == {2}
    assert main(["ble", "get", "--id", "9", "-o", str(out)], connect_ble=fake_connect(dev)) == 3


def test_cli_ble_device_not_found_exit_4(capsys):
    assert main(["ble", "list"], connect_ble=not_found) == 4
    assert "no ESPeak32" in capsys.readouterr().err


def test_cli_ble_scan(capsys):
    async def scan(timeout):
        return [("AA:BB", "ESPeak32", -60)]

    assert main(["ble", "scan"], scan_ble=scan) == 0
    assert "AA:BB\tESPeak32\t-60" in capsys.readouterr().out


def test_bleak_not_imported():
    assert "bleak" not in sys.modules
