import math
import wave

from espeak32.cli import main
from espeak32.codec import adpcm_encode, pcm16_encode
from espeak32.container import (
    CODEC_ADPCM,
    CODEC_PCM16,
    UNFINALIZED,
    Header,
    build,
    pack_frame,
    pack_header,
)
from espeak32.decode import decode_e32


def tone(n):
    return [int(9000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(n)]


def adpcm_file(n=1000):
    return build(CODEC_ADPCM, 16000, 1, 1, 0, n, adpcm_encode(tone(n)))


def test_decode_roundtrip_wav(tmp_path):
    src, out = tmp_path / "a.e32", tmp_path / "a.wav"
    src.write_bytes(adpcm_file(1000))
    assert main(["decode", str(src), "-o", str(out)]) == 0
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.getnframes() == 1000


def test_decode_unfinalized_decodes_available_samples_with_warning():
    blocks = adpcm_encode(tone(3 * 505))
    data = pack_header(Header(CODEC_ADPCM, 16000, 1, 1, 0, UNFINALIZED, 0)) + b"".join(
        pack_frame(b) for b in blocks
    )
    r = decode_e32(data)
    assert len(r.samples) == 1515
    assert any("not finalized" in w for w in r.warnings)


def test_decode_crc_mismatch_exit_code_2(tmp_path):
    data = bytearray(adpcm_file())
    data[40] ^= 0x01
    src, out = tmp_path / "a.e32", tmp_path / "a.wav"
    src.write_bytes(bytes(data))
    assert main(["decode", str(src), "-o", str(out)]) == 2
    assert not out.exists()
    assert main(["decode", str(src), "-o", str(out), "--force"]) == 0
    assert out.exists()


def test_decode_empty_note_writes_empty_wav(tmp_path, capsys):
    src, out = tmp_path / "e.e32", tmp_path / "e.wav"
    src.write_bytes(build(CODEC_ADPCM, 16000, 1, 1, 0, 0, []))
    assert main(["decode", str(src), "-o", str(out)]) == 0
    with wave.open(str(out)) as w:
        assert w.getnframes() == 0
    assert "empty recording" in capsys.readouterr().err


def test_decode_pcm16_file():
    pcm = tone(600)
    data = build(CODEC_PCM16, 16000, 1, 1, 0, 600, pcm16_encode(pcm))
    assert decode_e32(data).samples == pcm
