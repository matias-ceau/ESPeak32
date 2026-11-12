import json
from pathlib import Path

from espeak32.container import parse
from espeak32.vectors import generate

VEC = Path(__file__).resolve().parents[2] / "protocol" / "vectors"


def test_committed_vectors_match_generator():
    generated = generate(VEC)
    assert generated, "generator produced nothing"
    for name, data in generated.items():
        assert (VEC / name).read_bytes() == data, name


def test_pcm_vector_has_16000_samples():
    assert (VEC / "tone_16k.pcm").stat().st_size == 32000


def test_manifest_matches_files():
    manifest = json.loads((VEC / "manifest.json").read_text())
    assert manifest["files"]
    assert {e["version"] for e in manifest["files"]} == {1, 2}
    for entry in manifest["files"]:
        f = parse((VEC / entry["name"]).read_bytes())
        assert f.header.version == entry["version"]
        assert f.finalized == entry["finalized"]
        assert f.header.codec == entry["codec"]
        if entry["finalized"]:
            assert f"0x{f.payload_crc32:08x}" == entry["payload_crc32"]
            assert f.sample_count == entry["sample_count"]
            assert f.crc_ok is True


def test_unfinalized_vectors_parse_as_unfinalized_and_truncated():
    for name in ("tone_16k.unfinalized.e32", "v1/tone_16k.unfinalized.e32"):
        f = parse((VEC / name).read_bytes())
        assert not f.finalized and f.truncated and f.crc_ok is None, name


def test_v1_and_v2_vectors_carry_the_same_audio():
    for name in ("tone_16k.adpcm.e32", "tone_16k.pcm16.e32", "empty.e32"):
        v2, v1 = parse((VEC / name).read_bytes()), parse((VEC / "v1" / name).read_bytes())
        assert (v2.frames, v2.sample_count, v2.payload_crc32) == (v1.frames, v1.sample_count, v1.payload_crc32)
