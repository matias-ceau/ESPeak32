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
