import asyncio
import json
from pathlib import Path

import pytest

from espeak32 import ble, container
from espeak32.device_model import DeviceModel
from espeak32.sync import ModelTransport, SyncClient, SyncError, note_key, sync_all, wall_ms

VEC = Path(__file__).resolve().parents[2] / "protocol" / "vectors"
TONE = (VEC / "tone_16k.adpcm.e32").read_bytes()
EMPTY = (VEC / "empty.e32").read_bytes()
NOW_MS = 1_700_000_000_000


def device(**kw):
    return DeviceModel({1: TONE, 2: EMPTY}, **kw)


def connector(dev, *first_kw, mtu=64, **kw):
    """connect() factory: the n-th connection uses first_kw[n] if given, else **kw."""
    made: list[ModelTransport] = []

    async def connect():
        opts = first_kw[len(made)] if len(made) < len(first_kw) else kw
        t = ModelTransport(dev, mtu=mtu, **opts)
        made.append(t)
        return t

    connect.made = made
    return connect


def run(dev, out, connect=None, delete=True, **kw):
    return asyncio.run(sync_all(connect or connector(dev), out, delete=delete, now_ms=lambda: NOW_MS, **kw))


def stored(out):
    return sorted(p.name for p in out.glob("*.e32"))


def key_name(file_id, data):
    h = container.unpack_header(data[:32])
    return f"{file_id}_{h.boot_id}_{h.start_us}.e32"


def test_sync_two_notes_byte_exact(tmp_path):
    dev = device()
    rep = run(dev, tmp_path)
    assert (tmp_path / key_name(1, TONE)).read_bytes() == TONE
    assert (tmp_path / key_name(2, EMPTY)).read_bytes() == EMPTY
    assert rep.fetched == [1, 2] and rep.deleted == [1, 2] and rep.skipped == []
    assert dev.notes == {}
    assert not list(tmp_path.glob("*.part"))


def test_keep_on_device_without_delete(tmp_path):
    dev = device()
    rep = run(dev, tmp_path, delete=False)
    assert rep.deleted == [] and set(dev.notes) == {1, 2}


def test_delete_only_after_rename(tmp_path):
    dev = device()
    seen = []

    def on_write(req):
        if req[0] == ble.OP_DELETE:
            fid = int.from_bytes(req[1:5], "little")
            name = key_name(fid, dev.notes[fid])
            seen.append(((tmp_path / name).exists(), (tmp_path / (name + ".part")).exists()))

    run(dev, tmp_path, connect=connector(dev, on_write=on_write))
    assert seen == [(True, False), (True, False)]


@pytest.mark.parametrize("drop_at", [1, 70, 140])  # 141 chunks at MTU 64; 140 = the last one
def test_resume_after_drop(tmp_path, drop_at):
    dev = device()
    connect = connector(dev, {"drop_after_chunks": drop_at})
    rep = run(dev, tmp_path, connect=connect)
    assert (tmp_path / key_name(1, TONE)).read_bytes() == TONE
    assert rep.fetched == [1, 2]
    assert len(connect.made) == 2
    assert connect.made[1].writes[2] == ble.req_get(1, drop_at * 59, 16)  # SET_TIME, LIST, then resume


def test_lost_chunk_detected_by_seq_and_refetched(tmp_path):
    dev = device()
    rep = run(dev, tmp_path, connect=connector(dev, {"drop_chunk": 5}))
    assert (tmp_path / key_name(1, TONE)).read_bytes() == TONE
    assert rep.fetched == [1, 2]


def test_crc_mismatch_refetches_once_then_skips(tmp_path):
    dev = device()
    rep = run(dev, tmp_path, connect=connector(dev, corrupt=lambda seq: seq == 3))
    assert rep.skipped and rep.skipped[0][0] == 1 and "crc" in rep.skipped[0][1]
    assert 1 in dev.notes  # never deleted
    assert not (tmp_path / key_name(1, TONE)).exists()
    assert rep.fetched == [2]


def test_crc_mismatch_once_is_refetched(tmp_path):
    dev = device()
    seen = {"n": 0}

    def corrupt_first_fetch(seq):
        seen["n"] += 1
        return seen["n"] == 4

    rep = run(dev, tmp_path, connect=connector(dev, corrupt=corrupt_first_fetch))
    assert rep.fetched == [1, 2] and (tmp_path / key_name(1, TONE)).read_bytes() == TONE


def test_read_failure_retried_once(tmp_path):
    dev = device()
    dev.fail_read_at = (1, 2000)
    rep = run(dev, tmp_path)
    assert rep.skipped == [(1, "read failure on device")]
    assert rep.fetched == [2] and 1 in dev.notes


def test_busy_note_is_skipped(tmp_path):
    dev = DeviceModel({1: TONE}, busy={3: EMPTY})
    rep = run(dev, tmp_path)
    assert rep.fetched == [1]  # the busy note is not even listed


def test_busy_get_is_skipped(tmp_path):
    dev = device()
    real = dev.request

    def busy_get(req):  # the note started recording between LIST and GET
        if req[0] == ble.OP_GET and req[1] == 2:
            dev.outputs.append(("ctrl", bytes([0x82, ble.STATUS_BUSY])))
            return
        real(req)

    dev.request = busy_get
    rep = run(dev, tmp_path)
    assert rep.fetched == [1] and rep.skipped == [(2, "busy (recording)")] and 2 in dev.notes


def test_mtu_too_small_fails_fast(tmp_path):
    dev = device()
    connect = connector(dev, mtu=23)
    with pytest.raises(SyncError, match="MTU"):
        run(dev, tmp_path, connect=connect, mtu_retry_s=0)
    assert len(connect.made) == 1


def test_complete_local_note_is_not_refetched_only_deleted(tmp_path):
    dev = device()
    # first connection drops when the first DELETE is written, before the device handles it
    connect = connector(dev, {"drop_on_op": ble.OP_DELETE})
    rep = run(dev, tmp_path, connect=connect)
    assert dev.notes == {} and rep.deleted == [1, 2]
    assert connect.made[1].data_delivered == 1  # only the empty note; note 1 was not refetched


def test_delete_ack_lost_after_device_deleted(tmp_path):
    dev = device()
    connect = connector(dev, {"drop_on_op": ble.OP_DELETE, "drop_before": False})
    rep = run(dev, tmp_path, connect=connect)
    assert dev.notes == {} and stored(tmp_path) == sorted([key_name(1, TONE), key_name(2, EMPTY)])
    assert 2 in rep.deleted


def test_reused_file_id_with_new_header_is_a_new_note(tmp_path):
    old = tmp_path / key_name(1, TONE)
    old.write_bytes(TONE)
    h = container.unpack_header(TONE[:32])
    new = container.build(h.codec, h.sample_rate, 1, 99, 1234, 0, [])
    dev = DeviceModel({1: new})
    rep = run(dev, tmp_path)
    assert rep.fetched == [1]
    assert old.read_bytes() == TONE and (tmp_path / "1_99_1234.e32").read_bytes() == new


def test_resume_from_part_file_across_runs(tmp_path):
    dev = device()
    with pytest.raises(SyncError):
        run(dev, tmp_path, connect=connector(dev, {"drop_after_chunks": 50}), attempts=1)
    part = tmp_path / (key_name(1, TONE) + ".part")
    assert part.stat().st_size == 50 * 59
    connect = connector(dev)
    run(dev, tmp_path, connect=connect)
    assert (tmp_path / key_name(1, TONE)).read_bytes() == TONE
    assert connect.made[0].data_delivered == 141 - 50 + 1  # remaining tone chunks + the empty note


def test_clock_json_and_wall_ms(tmp_path):
    dev = device()
    run(dev, tmp_path)
    assert json.loads((tmp_path / "clock.json").read_text()) == {"5": [NOW_MS, 1_000_000]}
    assert wall_ms(5, 3_000_000, {5: (NOW_MS, 1_000_000)}) == NOW_MS + 2000
    assert wall_ms(5, 0, {5: (NOW_MS, 1_000_000)}) == NOW_MS - 1000
    assert wall_ms(6, 0, {5: (NOW_MS, 1_000_000)}) is None


def test_credit_policy(tmp_path):
    dev = DeviceModel({1: TONE})
    connect = connector(dev)
    run(dev, tmp_path, connect=connect, delete=False)
    writes = connect.made[0].writes
    get = next(i for i, w in enumerate(writes) if w[0] == ble.OP_GET)
    assert writes[get][-2:] == (16).to_bytes(2, "little")
    credits = [w for w in writes[get + 1:] if w[0] == ble.OP_CREDIT]
    assert credits and all(w == ble.req_credit(8) for w in credits)
    assert len(credits) == 141 // 8


def test_note_key():
    e = ble.ListEntry(0, 1, 7, 100, 1, 3, 42)
    assert note_key(e) == "7:3:42"


def test_client_info_and_list():
    dev = device()

    async def go():
        t = ModelTransport(dev, mtu=64)
        c = SyncClient(t)
        return await c.info(), await c.list()

    info, entries = asyncio.run(go())
    assert info.file_count == 2
    assert [e.file_id for e in entries] == [1, 2]


def test_note_that_keeps_losing_chunks_is_skipped_not_fatal(tmp_path):
    dev = device()
    rep = run(dev, tmp_path, connect=connector(dev, drop_seq=5))  # every GET loses its 6th chunk
    assert rep.skipped == [(1, "transfer keeps losing chunks")]
    assert rep.fetched == [2] and 1 in dev.notes


def test_done_overtaking_the_last_chunk_is_tolerated(tmp_path):
    # BlueZ AcquireNotify uses one socket per characteristic, so CTRL may overtake DATA.
    dev = device()
    connect = connector(dev, done_early=True)
    rep = run(dev, tmp_path, connect=connect)
    assert rep.fetched == [1, 2] and (tmp_path / key_name(1, TONE)).read_bytes() == TONE
    gets = [w for w in connect.made[0].writes if w[0] == ble.OP_GET]
    assert len(gets) == 2  # one per note: no resume was needed
