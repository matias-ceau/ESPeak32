import json
from pathlib import Path

import pytest

from espeak32 import ble
from espeak32.ble import (
    AbortAck,
    DeleteAck,
    ErrorAck,
    GetAck,
    Info,
    ListEntry,
    ProtocolError,
    SetTimeAck,
    TransferDone,
    decode_ctrl,
    pack_ctrl,
)

VEC = Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "ble.json"


def test_pack_info_golden():
    info = Info(1, 87, (0, 1, 0), 0b011, 2_500_000, 5, 1_000_000, 3)
    golden = bytes.fromhex("01 57 00 01 00 03 a0252600 05000000 40420f0000000000 03000000")
    assert ble.pack_info(info) == golden and len(golden) == 26
    assert ble.unpack_info(golden) == info


def test_req_get_golden():
    assert ble.req_get(7, 0x100, 8) == bytes.fromhex("02 07000000 00010000 0800")


def test_simple_requests_golden():
    assert ble.req_set_time(0x0102030405060708) == bytes.fromhex("05 0807060504030201")
    assert ble.req_abort() == b"\x06"
    assert ble.req_list() == b"\x01"
    assert ble.req_credit(3) == bytes.fromhex("03 0300")
    assert ble.req_delete(9) == bytes.fromhex("04 09000000")


@pytest.mark.parametrize(
    "msg",
    [
        ListEntry(0, 2, 5, 1000, 1, 3, 77),
        ListEntry(0, 0, 0, 0, 0, 0, 0),
        GetAck(5, 1000),
        DeleteAck(5),
        SetTimeAck(123456789),
        AbortAck(),
        TransferDone(5, 0xCAFEBABE),
        ErrorAck(ble.OP_GET, ble.STATUS_NOT_FOUND),
    ],
)
def test_ctrl_roundtrip_each_message(msg):
    assert decode_ctrl(pack_ctrl(msg)) == msg


def test_no_files_list_golden():
    assert pack_ctrl(ListEntry(0, 0, 0, 0, 0, 0, 0)) == bytes.fromhex("81 00 0000 0000")


def test_transfer_done_has_op_0x83():
    assert pack_ctrl(TransferDone(1, 2))[0] == 0x83


def test_error_status_decodes_to_error_ack():
    assert decode_ctrl(b"\x82\x03") == ErrorAck(ble.OP_GET, ble.STATUS_NOT_FOUND)


@pytest.mark.parametrize("bad", [b"", b"\x82", b"\x82\x00\x01", b"\x7f\x00", b"\x81\x00\x00"])
def test_decode_rejects_short_and_unknown(bad):
    with pytest.raises(ProtocolError):
        decode_ctrl(bad)


def test_data_chunk_seq_wrap():
    assert ble.pack_data_chunk(65535, b"ab") == bytes.fromhex("ffff 6162")
    assert ble.unpack_data_chunk(bytes.fromhex("ffff 6162")) == (65535, b"ab")
    with pytest.raises(ProtocolError):
        ble.pack_data_chunk(65536, b"")


def test_ble_vectors_in_sync():
    assert json.loads(VEC.read_text()) == ble.generate_vectors()
