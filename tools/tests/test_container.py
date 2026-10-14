import pytest

from espeak32.container import (
    CODEC_ADPCM,
    CODEC_PCM16,
    UNFINALIZED,
    FormatError,
    Header,
    build,
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
    )


def test_pack_header_known_bytes():
    assert pack_header(golden_header()) == GOLDEN
    assert unpack_header(GOLDEN) == golden_header()


@pytest.mark.parametrize(
    "bad",
    [
        b"XXXX" + GOLDEN[4:],
        GOLDEN[:4] + b"\x02" + GOLDEN[5:],
        GOLDEN[:31],
    ],
)
def test_unpack_header_rejects_bad_input(bad):
    with pytest.raises(FormatError):
        unpack_header(bad)


def _build(frames, sample_count=10):
    return build(CODEC_PCM16, 16000, 7, 3, 1234, sample_count, frames)


def test_build_then_parse_roundtrip():
    frames = [b"\x00\x01" * 10, b"\x02\x00" * 5]
    f = parse(_build(frames))
    assert f.finalized and f.crc_ok is True and not f.truncated
    assert f.frames == frames
    assert f.header.sample_count == 10


def test_parse_detects_payload_corruption():
    data = bytearray(_build([b"\x00\x01" * 10]))
    data[40] ^= 0x01
    assert parse(bytes(data)).crc_ok is False


def _unfinalized(frames_bytes):
    h = Header(CODEC_ADPCM, 16000, 1, 1, 0, UNFINALIZED, 0)
    return pack_header(h) + frames_bytes


def test_parse_unfinalized_file():
    data = _unfinalized(pack_frame(b"abcd") + pack_frame(b"efgh"))
    f = parse(data)
    assert not f.finalized and f.crc_ok is None
    assert f.frames == [b"abcd", b"efgh"]


def test_parse_drops_truncated_tail_frame():
    data = _unfinalized(pack_frame(b"abcd") + (20).to_bytes(2, "little") + b"1234567")
    f = parse(data)
    assert f.frames == [b"abcd"] and f.truncated


def test_parse_finalized_file_with_partial_tail():
    f = parse(_build([b"abcd"]) + b"\x09\x00\x01")
    assert f.crc_ok is True and f.truncated and f.frames == [b"abcd"]


def test_empty_note():
    data = build(CODEC_ADPCM, 16000, 1, 1, 0, 0, [])
    assert len(data) == 32
    f = parse(data)
    assert f.frames == [] and f.crc_ok is True
