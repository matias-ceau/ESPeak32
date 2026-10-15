import zlib
from pathlib import Path

from espeak32 import ble
from espeak32.container import pack_header, Header
from espeak32.device_model import DeviceConfig, DeviceModel
from espeak32.synctxt import SCENARIOS, parse, render

VEC = Path(__file__).resolve().parents[2] / "protocol" / "vectors"
TONE = (VEC / "tone_16k.adpcm.e32").read_bytes()
EMPTY = (VEC / "empty.e32").read_bytes()


def model(**kw):
    m = DeviceModel({1: TONE, 2: EMPTY}, **kw)
    return m


def ctrl(m):
    return [ble.decode_ctrl(b) for ch, b in m.outputs if ch == "ctrl"]


def data(m):
    return [ble.unpack_data_chunk(b) for ch, b in m.outputs if ch == "data"]


def fetch_all(m, file_id, offset=0, credits=1000):
    m.request(ble.req_get(file_id, offset, credits))
    m.run_until_idle()
    return b"".join(p for _, p in data(m))


def test_full_get_reassembles_file_and_crc():
    m = model()
    m.connect(64)
    assert fetch_all(m, 1) == TONE
    msgs = ctrl(m)
    assert msgs[0] == ble.GetAck(1, len(TONE))
    assert msgs[-1] == ble.TransferDone(1, zlib.crc32(TONE))


def test_chunk_payload_is_mtu_minus_5():
    for mtu, size in ((64, 59), (600, 507)):
        m = model()
        m.connect(mtu)
        m.request(ble.req_get(1, 0, 1))
        m.run_until_idle()
        assert len(data(m)[0][1]) == size


def test_credit_window_limits_chunks():
    m = model()
    m.connect(64)
    m.request(ble.req_get(1, 0, 3))
    m.run_until_idle()
    assert len(data(m)) == 3
    m.request(ble.req_credit(2))
    m.run_until_idle()
    assert [s for s, _ in data(m)] == [0, 1, 2, 3, 4]


def test_seq_restarts_per_get_and_wraps():
    big = pack_header(Header(1, 16000, 9, 5, 0, 0, 0)) + bytes(59 * 65537)
    m = DeviceModel({9: big})
    m.connect(64)
    m.request(ble.req_get(9, 0, 65535))
    m.run_until_idle()
    m.request(ble.req_credit(10))
    m.run_until_idle()
    seqs = [s for s, _ in data(m)]
    assert seqs[0] == 0 and seqs[65535] == 65535 and seqs[65536] == 0
    m.outputs.clear()
    m.request(ble.req_get(9, 0, 1))
    m.run_until_idle()
    assert data(m)[0][0] == 0


def test_resume_crc_covers_whole_file():
    m = model()
    m.connect(64)
    assert fetch_all(m, 1, offset=1000) == TONE[1000:]
    assert ctrl(m)[-1] == ble.TransferDone(1, zlib.crc32(TONE))


def test_list_excludes_busy_and_info_counts():
    m = DeviceModel({1: TONE, 2: EMPTY}, busy={3: EMPTY})
    m.connect(64)
    m.request(ble.req_list())
    assert [e.file_id for e in ctrl(m)] == [1, 2]
    assert ctrl(m)[0].total == 2
    info = ble.unpack_info(m.info())
    assert info.file_count == 2 and info.battery_pct == 255


def test_bad_header_listed_with_codec_255():
    m = DeviceModel({4: b"garbage"})
    m.connect(64)
    m.request(ble.req_list())
    assert ctrl(m) == [ble.ListEntry(0, 1, 4, 7, 255, 0, 0)]


def test_disconnect_cancels():
    m = model()
    m.connect(64)
    m.request(ble.req_get(1, 0, 2))
    m.run_until_idle()
    m.disconnect()
    m.connect(64)
    m.outputs.clear()
    m.request(ble.req_credit(5))
    m.run_until_idle()
    assert m.outputs == []


def test_read_failure_sends_transfer_failed():
    m = model()
    m.fail_read_at = (1, 200)
    m.connect(64)
    m.request(ble.req_get(1, 0, 100))
    m.run_until_idle()
    assert ctrl(m)[-1] == ble.TransferFailed(ble.STATUS_IO)
    assert sum(len(p) for _, p in data(m)) == 177  # 3 full chunks; the 4th covers offset 200


def test_mtu_too_small():
    m = model()
    m.connect(23)
    m.request(ble.req_list())
    assert ctrl(m) == [ble.ErrorAck(ble.OP_LIST, ble.STATUS_MTU)]


def test_committed_sync_txt_matches_generator():
    assert render(SCENARIOS, VEC) == (VEC / "sync.txt").read_text()


def test_parse_roundtrip_counts():
    parsed = parse((VEC / "sync.txt").read_text())
    assert len(parsed) >= 20
    for sc in parsed:
        assert any(line.startswith("EXPECT") for line in sc.lines), sc.name
    assert {sc.name for sc in parsed} == {sc.name for sc in SCENARIOS}


def test_default_config():
    assert DeviceConfig().battery_pct == 255
