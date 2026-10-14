"""Decode `.e32` bytes into PCM samples."""

from __future__ import annotations

from dataclasses import dataclass, field

from .codec import BLOCK_SAMPLES, decode_frames
from .container import CODEC_ADPCM, parse


@dataclass
class DecodeResult:
    sample_rate: int
    samples: list[int]
    warnings: list[str] = field(default_factory=list)
    crc_ok: bool | None = None


def decode_e32(data: bytes) -> DecodeResult:
    f = parse(data)
    warnings: list[str] = []
    if f.finalized:
        count = f.header.sample_count
    else:
        warnings.append("file not finalized (recording was interrupted)")
        if f.header.codec == CODEC_ADPCM:
            count = len(f.frames) * BLOCK_SAMPLES
        else:
            count = sum(len(fr) for fr in f.frames) // 2
    if f.truncated:
        warnings.append("truncated trailing frame ignored")
    samples = decode_frames(f.header.codec, f.frames, count)
    if not samples:
        warnings.append("empty recording")
    return DecodeResult(f.header.sample_rate, samples, warnings, f.crc_ok)
