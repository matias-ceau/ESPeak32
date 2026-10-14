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
    for entry in manifest["files"]:
        f = parse((VEC / entry["name"]).read_bytes())
        assert f.finalized == entry["finalized"]
        assert f.header.codec == entry["codec"]
        if entry["finalized"]:
            assert f"0x{f.header.payload_crc32:08x}" == entry["payload_crc32"]
            assert f.header.sample_count == entry["sample_count"]


def test_unfinalized_vector_parses_as_unfinalized_and_truncated():
    f = parse((VEC / "tone_16k.unfinalized.e32").read_bytes())
    assert not f.finalized and f.truncated and f.crc_ok is None
