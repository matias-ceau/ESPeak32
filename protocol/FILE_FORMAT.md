# `.e32` file format (version 1)

All multi-byte integers are little-endian. One file holds one voice note.

## Header (32 bytes)

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 4 | magic | ASCII `E32A` |
| 4 | 1 | version | `1` |
| 5 | 1 | codec | `0` PCM16, `1` IMA-ADPCM, `2` Opus (reserved) |
| 6 | 2 | sample_rate | Hz (`16000`) |
| 8 | 4 | file_id | |
| 12 | 4 | boot_id | |
| 16 | 8 | start_us | microseconds since boot at record start |
| 24 | 4 | sample_count | PCM samples encoded; `0xFFFFFFFF` = **unfinalized** |
| 28 | 4 | payload_crc32 | CRC-32 (IEEE, same as `zlib.crc32`) over every byte of all **complete** frames, length prefixes included; `0` if unfinalized |

## Frames

After the header: `[u16 len][len bytes]`, repeated. A trailing partial frame is ignored by readers and by the CRC.
PCM16 frames carry up to 512 bytes (256 samples; the last frame may be shorter). ADPCM frames carry exactly one
256-byte block.

## Finalization

The writer appends an unfinalized header, then frames, then rewrites the header with the real `sample_count` and CRC.
A file whose header is still unfinalized (power loss) is decodable from its complete frames; there is no CRC check.
An empty note is a finalized 32-byte header with `sample_count = 0` and CRC `0`.

## PCM16 (codec 0)

Raw little-endian signed 16-bit samples. Each frame holds up to 256 samples (512 bytes); the last frame may be shorter.

## IMA-ADPCM (codec 1)

WAVE format 0x11, mono, block align 256, 505 samples per block. Each frame is one 256-byte block.

- Block header (4 bytes): predictor `i16` = the block's first PCM sample (stored exactly); step index `u8` = encoder
  index at block start; reserved `0`.
- Then 252 bytes: byte `i` holds sample `2i+1` in the **low** nibble and sample `2i+2` in the **high** nibble.
- Tables: standard 89-entry IMA step table (7 … 32767); `INDEX_ADJ = [-1,-1,-1,-1,2,4,6,8]` indexed by `code & 7`;
  index clamped to 0..88; initial index 0, carried across blocks.
- Reconstruction (decoder and encoder's own tracking) is the reference IMA shift arithmetic:
  `d = step >> 3; if code & 4: d += step; if code & 2: d += step >> 1; if code & 1: d += step >> 2`;
  `pred = clamp16(pred - d if code & 8 else pred + d)`. FFmpeg >= 9 decodes these blocks bit-exactly. FFmpeg 6.1-8.x
  used `((2*(code & 7) + 1) * step) >> 3`, which rounds differently; do not use those versions as an oracle.
- Encoder quantiser (reference IMA successive approximation): `code = 8 if diff < 0 else 0; diff = abs(diff)`; then for
  `(bit, part)` in `(4, step), (2, step >> 1), (1, step >> 2)`: if `diff >= part`, set `bit` and subtract `part`.
- The last block is zero-padded to 505 samples; decoders trim to `sample_count`.

## Opus (codec 2)

Reserved; not implemented yet.
