import math
import shutil
import struct
import subprocess

import pytest

from espeak32.codec import (
    BLOCK_BYTES,
    BLOCK_SAMPLES,
    UnsupportedCodec,
    adpcm_decode,
    adpcm_encode,
    decode_frames,
    pcm16_decode,
    pcm16_encode,
)


def tone(n):
    return [
        int(9000 * math.sin(2 * math.pi * 440 * i / 16000)
            + 3000 * math.sin(2 * math.pi * 1230 * i / 16000))
        for i in range(n)
    ]


def test_adpcm_golden_first_bytes():
    (block,) = adpcm_encode([0, 7] + [0] * 503)
    assert len(block) == BLOCK_BYTES == 256
    assert block[:4] == bytes(4)
    assert block[4] == 0xB4


def test_adpcm_silence_is_all_zero():
    (block,) = adpcm_encode([0] * BLOCK_SAMPLES)
    assert block == bytes(256)


def test_adpcm_pads_and_trims():
    blocks = adpcm_encode(tone(1000))
    assert len(blocks) == 2
    assert len(adpcm_decode(blocks, 1000)) == 1000


def test_adpcm_first_sample_of_each_block_is_exact():
    pcm = tone(1010)
    out = adpcm_decode(adpcm_encode(pcm), 1010)
    assert out[0] == pcm[0] and out[505] == pcm[505]


def test_adpcm_roundtrip_snr_at_least_20db():
    pcm = tone(2020)
    out = adpcm_decode(adpcm_encode(pcm), 2020)
    err = sum((a - b) ** 2 for a, b in zip(pcm, out)) / len(pcm)
    sig = sum(a * a for a in pcm) / len(pcm)
    assert 10 * math.log10(sig / err) >= 20


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_adpcm_matches_ffmpeg(tmp_path):
    pcm = tone(2020)
    blocks = adpcm_encode(pcm)
    data = b"".join(blocks)

    def chunk(tag, body):
        return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")

    fmt = struct.pack("<HHIIHHHH", 0x11, 1, 16000, 16000 * 256 // 505, 256, 4, 2, 505)
    body = (b"WAVE" + chunk(b"fmt ", fmt) + chunk(b"fact", struct.pack("<I", 2020))
            + chunk(b"data", data))
    wav = tmp_path / "t.wav"
    wav.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    raw = tmp_path / "o.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-f", "s16le",
                    "-acodec", "pcm_s16le", str(raw)], check=True)
    b = raw.read_bytes()
    ff = list(struct.unpack(f"<{len(b) // 2}h", b))
    assert ff == adpcm_decode(blocks, len(ff))
    assert len(ff) == 2020


def test_adpcm_extremes_do_not_overflow():
    pcm = [32767 if i % 2 == 0 else -32767 for i in range(1010)]
    out = adpcm_decode(adpcm_encode(pcm), 1010)
    assert all(-32768 <= s <= 32767 for s in out)


def test_adpcm_empty_input():
    assert adpcm_encode([]) == []


def test_pcm16_frames():
    pcm = tone(600)
    frames = pcm16_encode(pcm)
    assert [len(f) for f in frames] == [512, 512, 176]
    assert pcm16_decode(frames, 600) == pcm


def test_decode_frames_rejects_opus():
    with pytest.raises(UnsupportedCodec):
        decode_frames(2, [], 0)
