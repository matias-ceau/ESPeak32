import zlib

import pytest

from espeak32.container import (
    CODEC_ADPCM,
    CODEC_PCM16,
    END_BYTES,
    UNFINALIZED,
    FormatError,
    Header,
    build,
    pack_end,
    pack_frame,
    pack_header,
    parse,
    unpack_header,
)

GOLDEN = bytes.fromhex(
    "45333241 01 01 803e 01000000 02000000 0807060504030201 f9010000 efbeadde"
)


def golden_header() -> Header:
    return Header(
        codec=1,
        sample_rate=16000,
        file_id=1,
        boot_id=2,
        start_us=0x0102030405060708,
        sample_count=505,
        payload_crc32=0xDEADBEEF,
        version=1,
    )


def test_pack_header_known_bytes():
    assert pack_header(golden_header()) == GOLDEN
    assert unpack_header(GOLDEN) == golden_header()


def test_end_record_known_bytes():
    assert pack_end(505, 0xDEADBEEF) == bytes.fromhex("ffff 45333245 f9010000 efbeadde")
    assert len(pack_end(0, 0)) == END_BYTES


@pytest.mark.parametrize(
    "bad",
    [
        b"XXXX" + GOLDEN[4:],
        GOLDEN[:4] + b"\x03" + GOLDEN[5:],
        GOLDEN[:4] + b"\x00" + GOLDEN[5:],
        GOLDEN[:31],
    ],
)
def test_unpack_header_rejects_bad_input(bad):
    with pytest.raises(FormatError):
        unpack_header(bad)


def _build(frames, sample_count=10, version=2):
    return build(CODEC_PCM16, 16000, 7, 3, 1234, sample_count, frames, version)


@pytest.mark.parametrize("version", [1, 2])
def test_build_then_parse_roundtrip(version):
    frames = [b"\x00\x01" * 10, b"\x02\x00" * 5]
    f = parse(_build(frames, version=version))
    assert f.header.version == version
    assert f.finalized and f.crc_ok is True and not f.truncated
    assert f.frames == frames
    assert f.sample_count == 10 and f.payload_crc32 == zlib.crc32(b"".join(pack_frame(x) for x in frames))


def test_v2_header_is_never_finalized_in_place():
    h = parse(_build([b"ab"])).header
    assert (h.sample_count, h.payload_crc32) == (UNFINALIZED, 0)


@pytest.mark.parametrize("version", [1, 2])
def test_parse_detects_payload_corruption(version):
    data = bytearray(_build([b"\x00\x01" * 10], version=version))
    data[40] ^= 0x01
    assert parse(bytes(data)).crc_ok is False


def _unfinalized(frames_bytes, version=2):
    h = Header(CODEC_ADPCM, 16000, 1, 1, 0, UNFINALIZED, 0, version)
    return pack_header(h) + frames_bytes


@pytest.mark.parametrize("version", [1, 2])
def test_parse_unfinalized_file(version):
    data = _unfinalized(pack_frame(b"abcd") + pack_frame(b"efgh"), version)
    f = parse(data)
    assert not f.finalized and f.crc_ok is None and not f.truncated
    assert f.frames == [b"abcd", b"efgh"]
    assert (f.sample_count, f.payload_crc32) == (UNFINALIZED, 0)


@pytest.mark.parametrize("version", [1, 2])
def test_parse_drops_truncated_tail_frame(version):
    data = _unfinalized(pack_frame(b"abcd") + (20).to_bytes(2, "little") + b"1234567", version)
    f = parse(data)
    assert f.frames == [b"abcd"] and f.truncated


@pytest.mark.parametrize("version", [1, 2])
def test_parse_finalized_file_with_partial_tail(version):
    f = parse(_build([b"abcd"], version=version) + b"\x09\x00\x01")
    assert f.crc_ok is True and f.truncated and f.frames == [b"abcd"]


@pytest.mark.parametrize("cut", range(1, END_BYTES))
def test_v2_partial_end_record_leaves_the_note_unfinalized(cut):
    full = _build([b"abcd", b"efgh"])
    f = parse(full[:-cut])  # power cut while the end record was being written
    assert not f.finalized and f.crc_ok is None and f.truncated
    assert f.frames == [b"abcd", b"efgh"]


def test_v2_garbled_end_record_leaves_the_note_unfinalized():
    data = bytearray(_build([b"abcd"]))
    data[-11] ^= 0x01  # inside the "E32E" magic
    f = parse(bytes(data))
    assert not f.finalized and f.truncated and f.frames == [b"abcd"]


def test_v1_reads_0xffff_as_a_truncated_frame_not_an_end_record():
    data = _unfinalized(pack_frame(b"abcd") + pack_end(1, 2), version=1)
    f = parse(data)
    assert not f.finalized and f.truncated and f.frames == [b"abcd"]


@pytest.mark.parametrize("version,size", [(1, 32), (2, 32 + END_BYTES)])
def test_empty_note(version, size):
    data = build(CODEC_ADPCM, 16000, 1, 1, 0, 0, [], version)
    assert len(data) == size
    f = parse(data)
    assert f.frames == [] and f.crc_ok is True and f.sample_count == 0
