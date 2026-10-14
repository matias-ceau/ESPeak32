"""Reference codecs: IMA-ADPCM (WAVE 0x11 blocks, FFmpeg-exact reconstruction) and PCM16."""

from __future__ import annotations

import struct
from typing import Iterable, Sequence

from .container import CODEC_ADPCM, CODEC_OPUS, CODEC_PCM16

BLOCK_BYTES = 256
BLOCK_SAMPLES = 505
PCM_FRAME_SAMPLES = 256

STEP = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
    73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408,
    449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
    2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630,
    9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
    32767,
]
INDEX_ADJ = [-1, -1, -1, -1, 2, 4, 6, 8]


class UnsupportedCodec(ValueError):
    pass


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def _reconstruct(pred: int, index: int, code: int) -> tuple[int, int]:
    d = ((2 * (code & 7) + 1) * STEP[index]) >> 3
    pred = _clamp(pred - d if code & 8 else pred + d, -32768, 32767)
    index = _clamp(index + INDEX_ADJ[code & 7], 0, 88)
    return pred, index


def adpcm_encode(pcm: Sequence[int]) -> list[bytes]:
    blocks: list[bytes] = []
    index = 0
    for start in range(0, len(pcm), BLOCK_SAMPLES):
        chunk = list(pcm[start : start + BLOCK_SAMPLES])
        chunk += [0] * (BLOCK_SAMPLES - len(chunk))
        pred = chunk[0]
        out = bytearray(struct.pack("<hBB", pred, index, 0))
        codes = []
        for s in chunk[1:]:
            diff = s - pred
            code = min(7, abs(diff) * 4 // STEP[index]) | (8 if diff < 0 else 0)
            pred, index = _reconstruct(pred, index, code)
            codes.append(code)
        for i in range(0, len(codes), 2):
            out.append(codes[i] | (codes[i + 1] << 4))
        blocks.append(bytes(out))
    return blocks


def _decode_block(block: bytes) -> list[int]:
    pred, index, _ = struct.unpack("<hBB", block[:4])
    out = [pred]
    for byte in block[4:]:
        for code in (byte & 15, byte >> 4):
            pred, index = _reconstruct(pred, index, code)
            out.append(pred)
    return out


def adpcm_decode(blocks: Iterable[bytes], sample_count: int) -> list[int]:
    out: list[int] = []
    for b in blocks:
        out.extend(_decode_block(b))
    return out[:sample_count]


def pcm16_encode(pcm: Sequence[int]) -> list[bytes]:
    return [
        struct.pack(f"<{len(c)}h", *c)
        for c in (pcm[i : i + PCM_FRAME_SAMPLES] for i in range(0, len(pcm), PCM_FRAME_SAMPLES))
    ]


def pcm16_decode(frames: Iterable[bytes], sample_count: int) -> list[int]:
    out: list[int] = []
    for f in frames:
        out.extend(struct.unpack(f"<{len(f) // 2}h", f))
    return out[:sample_count]


def decode_frames(codec: int, frames: Iterable[bytes], sample_count: int) -> list[int]:
    if codec == CODEC_ADPCM:
        return adpcm_decode(frames, sample_count)
    if codec == CODEC_PCM16:
        return pcm16_decode(frames, sample_count)
    if codec == CODEC_OPUS:
        raise UnsupportedCodec("Opus is not implemented")
    raise UnsupportedCodec(f"unknown codec {codec}")
