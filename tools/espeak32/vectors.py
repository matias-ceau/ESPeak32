"""Golden test vectors shared by the Python, C and (later) TypeScript implementations.

`tone_16k.pcm` is the committed source of truth; everything else is derived from it.
Usage: python -m espeak32.vectors <dir> [--regen-pcm]
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

from .codec import adpcm_encode, pcm16_encode
from .container import (
    CODEC_ADPCM,
    CODEC_PCM16,
    UNFINALIZED,
    Header,
    build,
    pack_frame,
    pack_header,
    parse,
)

RATE = 16000
FILE_ID, BOOT_ID, START_US = 1, 2, 0x0102030405060708
PCM_NAME = "tone_16k.pcm"


def tone_samples(n: int = RATE) -> list[int]:
    return [
        int(9000 * math.sin(2 * math.pi * 440 * i / RATE)
            + 3000 * math.sin(2 * math.pi * 1230 * i / RATE))
        for i in range(n)
    ]


def generate(out_dir: Path) -> dict[str, bytes]:
    """Derive every artefact (except the PCM source) from `out_dir/tone_16k.pcm`."""
    raw = (Path(out_dir) / PCM_NAME).read_bytes()
    pcm = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    n = len(pcm)
    adpcm_frames = adpcm_encode(pcm)

    def mk(codec, frames, count):
        return build(codec, RATE, FILE_ID, BOOT_ID, START_US, count, frames)

    files = {
        "tone_16k.adpcm.e32": mk(CODEC_ADPCM, adpcm_frames, n),
        "tone_16k.pcm16.e32": mk(CODEC_PCM16, pcm16_encode(pcm), n),
        "empty.e32": mk(CODEC_ADPCM, [], 0),
    }
    unfinal_header = Header(CODEC_ADPCM, RATE, FILE_ID, BOOT_ID, START_US, UNFINALIZED, 0)
    body = b"".join(pack_frame(b) for b in adpcm_frames[:-1])
    body += pack_frame(adpcm_frames[-1])[: 2 + len(adpcm_frames[-1]) // 2]
    files["tone_16k.unfinalized.e32"] = pack_header(unfinal_header) + body

    entries = []
    for name, data in files.items():
        f = parse(data)
        entries.append({
            "name": name,
            "codec": f.header.codec,
            "sample_rate": f.header.sample_rate,
            "sample_count": f.header.sample_count,
            "finalized": f.finalized,
            "payload_crc32": f"0x{f.header.payload_crc32:08x}",
            "bytes": len(data),
        })
    manifest = {
        "signal": "int(9000*sin(2pi*440n/16000) + 3000*sin(2pi*1230n/16000)), n=0..15999",
        "files": entries,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--regen-pcm", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.regen_pcm:
        s = tone_samples()
        (out / PCM_NAME).write_bytes(struct.pack(f"<{len(s)}h", *s))
    for name, data in generate(out).items():
        (out / name).write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
