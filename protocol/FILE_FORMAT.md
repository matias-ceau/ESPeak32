# `.e32` file format (version 2; version 1 still read)

All multi-byte integers are little-endian. One file holds one voice note. The device writes version 2 (firmware
>= 0.3.0); readers accept versions 1 and 2. Reference implementation: `tools/espeak32/container.py`; vectors:
`protocol/vectors/` (version 2) and `protocol/vectors/v1/` (version 1).

## Header (32 bytes)

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 4 | magic | ASCII `E32A` |
| 4 | 1 | version | `2` (`1` in older notes) |
| 5 | 1 | codec | `0` PCM16, `1` IMA-ADPCM, `2` Opus (reserved) |
| 6 | 2 | sample_rate | Hz (`16000`) |
| 8 | 4 | file_id | |
| 12 | 4 | boot_id | |
| 16 | 8 | start_us | microseconds since boot at record start |
| 24 | 4 | sample_count | version 1: PCM samples encoded, `0xFFFFFFFF` = **unfinalized**. Version 2: always `0xFFFFFFFF` (see the end record) |
| 28 | 4 | payload_crc32 | version 1: CRC-32 (IEEE, same as `zlib.crc32`) over every byte of all **complete** frames, length prefixes included; `0` if unfinalized. Version 2: always `0` |

## Frames

After the header: `[u16 len][len bytes]`, repeated. A trailing partial frame is ignored by readers and by the CRC.
PCM16 frames carry up to 512 bytes (256 samples; the last frame may be shorter). ADPCM frames carry exactly one
256-byte block. A frame length is never `0xFFFF`.

## End record (version 2)

After the last frame the writer appends 14 bytes:

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 2 | marker | `0xFFFF` |
| 2 | 4 | magic | ASCII `E32E` |
| 6 | 4 | sample_count | PCM samples encoded |
| 10 | 4 | payload_crc32 | CRC-32 over every byte of all frames before the end record, length prefixes included |

A reader that meets the `0xFFFF` marker stops reading frames. If the 14 bytes are all there and the magic matches, the
note is finalized with these values; otherwise (power cut while writing it, or damage) the note is unfinalized. Bytes
after the end record are ignored and reported as truncated.

## Finalization

- **Version 2 (current):** the writer writes the header once, appends frames, then appends the end record. The file is
  never rewritten: LittleFS copies a whole file to change its first bytes, which costs time at every save and needs
  as much free space as the note itself (a long note on a nearly full device could never be finalized). After a failed
  write the writer adds no end record, because the failed write may have left a partial frame.
- **Version 1:** the writer appended an unfinalized header, then frames, then rewrote the header with the real
  `sample_count` and CRC.

Either way, a note without its finalization (power loss) is decodable from its complete frames; there is no CRC check.
An empty note is the header plus an end record with `sample_count = 0` and CRC `0` (46 bytes); in version 1, a finalized
32-byte header with `sample_count = 0` and CRC `0`.

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
