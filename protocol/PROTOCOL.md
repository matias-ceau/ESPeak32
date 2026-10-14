# ESPeak32 BLE protocol (version 1)

Normative reference implementation: `tools/espeak32/ble.py`; golden messages: `protocol/vectors/ble.json`.
All integers are little-endian. The ATT MTU must be at least 64 bytes, otherwise the device answers status `5 (MTU)`.
All characteristics require an encrypted link; the device is connectable only during short advertising windows.

## GATT

| Characteristic | UUID | Properties |
|---|---|---|
| Service | `8f05e6c5-7b93-4a53-b175-b3416b3a0d20` | |
| INFO | `8f05e6c6-7b93-4a53-b175-b3416b3a0d20` | read |
| CTRL | `8f05e6c7-7b93-4a53-b175-b3416b3a0d20` | write + notify |
| DATA | `8f05e6c8-7b93-4a53-b175-b3416b3a0d20` | notify |

## INFO (26 bytes)

`proto_version u8, battery_pct u8, fw_major u8, fw_minor u8, fw_patch u8, codecs_mask u8 (bit0 PCM16, bit1 ADPCM,
bit2 Opus), free_bytes u32, boot_id u32, ticks_us u64, file_count u32`.
(`file_count` is an addition to the design spec's field list; the file list needs it.)

## CTRL requests: `[op u8][args]`

| Op | Name | Args |
|---|---|---|
| 1 | LIST | none |
| 2 | GET | `file_id u32, offset u32, credits u16` |
| 3 | CREDIT | `credits u16` (grants more DATA chunks; **no response**) |
| 4 | DELETE | `file_id u32` |
| 5 | SET_TIME | `unix_ms u64` |
| 6 | ABORT | none |

(`CREDIT` is an addition to the design spec's command list; the credit window needs it.)

## CTRL notifications: `[op | 0x80][status u8][body]`

- LIST: one notification per file, body `index u16, total u16, file_id u32, size u32, codec u8, boot_id u32,
  start_us u64`. With no files: one notification with `index = 0, total = 0` and no further fields.
- GET ack: body `file_id u32, total_size u32`.
- DELETE: body `file_id u32`. SET_TIME: body `ticks_us u64` (device clock when handled). ABORT: empty body.
- `0x83 TRANSFER_DONE`: body `file_id u32, file_crc32 u32` (CRC-32 of the whole stored file from byte 0).
- Any non-zero status carries no body.

Status: `0 OK, 1 UNKNOWN_OPCODE, 2 BAD_ARGS, 3 NOT_FOUND, 4 BUSY, 5 MTU, 6 IO`.

## DATA notifications: `[seq u16][payload]`

`seq` starts at 0 for each GET and wraps modulo 65536. The payload is a slice of the stored `.e32` file starting at the
requested offset.

## Sync sequence

1. `SET_TIME`, then `LIST`.
2. For each file: `GET(file_id, offset, credits)`. The device sends at most `credits` DATA chunks, then waits for
   `CREDIT`. The app sends `CREDIT` as it consumes chunks (Web Bluetooth has no notification back-pressure).
3. After the last byte the device sends `TRANSFER_DONE`; the app checks the CRC.
4. Only after the app has stored the file and verified the CRC does it send `DELETE` (two-phase delete: an interrupted
   sync loses nothing).
5. Resume: after a dropped link, `GET` again with `offset` = bytes already stored.
