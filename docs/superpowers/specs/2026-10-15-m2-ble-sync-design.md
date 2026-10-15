# M2 — BLE Sync: Design Spec

**Date:** 2026-10-15
**Status:** Self-approved under the user's standing instruction ("make routine decisions yourself and record them");
open to the user's review on return. Decisions are also listed in `docs/DECISIONS.md`.
**Parent spec:** `docs/superpowers/specs/2026-10-14-espeak32-voice-recorder-design.md` (sections 4.1, 4.5, 4.6, 5, 6, 9).
**Contract:** `protocol/PROTOCOL.md` (v1), `protocol/FILE_FORMAT.md`, `tools/espeak32/ble.py`.

## 0. Brief

**Asked for (handoff and user):** M2 = NimBLE GATT service and transfer engine (credit-windowed GET, resume by offset,
CRC, two-phase delete, SET_TIME, encrypted link, advertising windows); a Python `bleak` CLI; the TypeScript PWA (Web
Bluetooth) tested against a mocked transport. Everything must be testable without the board; flashing and on-device
checks wait for the user.

**Assumed (not stated):**
- Success means the parent spec's criterion 2: a note reaches the phone without loss even if the link drops mid-transfer.
- The M2 PWA is the *sync screen*: connect, sync, list synced notes, play them and save a WAV. Transcription, summaries,
  settings beyond "delete after sync" and the offline job queue are M3.
- One device per phone. No multi-device bookkeeping.
- No deep sleep yet (M4): the device stays powered on USB; advertising windows only bound when it is connectable.

## 1. Scope

In: transfer engine and button classifier in portable C; NimBLE glue; protocol clarifications below; a Python reference
device model and shared session vectors; Python sync client and `espeak32 ble …` CLI; PWA under `app/`; CI jobs; an M2
bring-up checklist.

Out: deep sleep and wake, battery sense (INFO reports `battery_pct = 255`, unknown), first-word pre-roll audio, LED
patterns beyond on/off/blink, Opus, background sync, the Capacitor wrapper, multi-device support, GitHub Pages deploy
that runs on its own (a manual workflow is provided; see 7).

## 2. Protocol clarifications (PROTOCOL.md v1 stays wire-compatible)

These fill behaviour PROTOCOL.md leaves open. Only the first item changes how a byte sequence is interpreted.

1. **Transfer failure.** If a read fails mid-transfer the device sends `[0x83][status]` (TRANSFER_DONE with a non-zero
   status, no body) and cancels the transfer. `ble.py` decodes it as a new `TransferFailed(status)` message (today it
   decodes ambiguously as `ErrorAck(op=CREDIT)`; this closes that deferred minor).
2. **Chunk size.** DATA payload = `mtu - 5` bytes (3 bytes ATT notification header, 2 bytes `seq`), capped at 507. The
   last chunk may be shorter. Clients use the received length; they never assume a size.
3. **GET.** `offset > size` → `BAD_ARGS`. Unknown id → `NOT_FOUND`. The note being recorded → `BUSY`. `offset == size` →
   GET ack, then TRANSFER_DONE at once. A GET while a transfer is active replaces it (the old one stops silently; `seq`
   restarts at 0). `credits = 0` is valid: nothing flows until CREDIT.
4. **CREDIT.** Adds to the outstanding credit, saturating at 65535. Without an active transfer it is ignored. It never
   gets a response (unchanged).
5. **TRANSFER_DONE ordering.** Sent after the last DATA chunk has been handed to the stack. Notifications share one ATT
   bearer, so they arrive in order; clients still check the byte count (see 5.3).
6. **ABORT.** Cancels the active transfer if any; always answered with the ABORT ack.
7. **DELETE.** The note being recorded or the note under an active transfer → `BUSY`.
8. **LIST, INFO.** The note being recorded is excluded from LIST and from `file_count`. A note whose header does not
   parse is still listed, with `codec = 255, boot_id = 0, start_us = 0`, so it can be fetched and inspected.
9. **Request length** must match the opcode exactly, otherwise `BAD_ARGS` for that opcode. An empty write is ignored.
10. **MTU.** While the negotiated MTU is below 64, every request except CREDIT is answered with status `MTU`.
11. **Disconnect** cancels the active transfer and its credits.
12. **SET_TIME.** The device answers with its current `ticks_us` and keeps nothing (time conversion is the app's job).
13. **Wall time (clients).** For a note with `(boot_id, start_us)`, take the latest stored SET_TIME pair
    `(unix_ms, ticks_us)` recorded for the same `boot_id`: `wall_ms = unix_ms + (start_us - ticks_us) // 1000`. No pair
    for that boot → unknown time.

## 3. Shared verification: device model and session vectors

`tools/espeak32/device_model.py` is the **reference device**: a pure-Python object with exactly the engine's API
(`connect(mtu)`, `disconnect()`, `request(bytes)`, `pump() -> bool`, `info() -> bytes`) over in-memory notes, emitting
`("ctrl"|"data", bytes)` outputs. It generates `protocol/vectors/sync.txt`, a line-oriented session transcript that
C, Python and TypeScript all parse without a JSON library (the `#` comments below are illustrative; the file has none):

```
SCENARIO get_resume_offset
CONFIG boot_id=5 fw=0.2.0 codecs=3 battery=255 free=2500000 now_us=1000000
FILE 1 tone_16k.adpcm.e32          # note id 1 holds that committed vector file
BUSY 3 empty.e32                   # note 3 exists but is being recorded
CONNECT 64
SEND 0201000000e80300000400        # GET(1, offset 1000, 4 credits); then the harness pumps until idle
EXPECT CTRL 82000100000060200000   # GET ack: id 1, size 8288; outputs listed in order, CTRL or DATA, hex
EXPECT DATA 0000…
INFO
EXPECT INFO 01ff…
DISCONNECT
END
```

Scenarios cover: info; set_time; list with notes, empty list, busy note excluded; full GET in several credit grants;
GET with `credits = 0` then CREDIT; resume at an offset (CRC still over the whole file); `offset == size`; `offset >
size`; unknown id; busy note; a new GET replacing an active one; ABORT mid-transfer; CREDIT without a transfer; DELETE
ok, unknown and busy (recording and under transfer); unknown opcode; wrong request length; MTU below 64; disconnect
mid-transfer then reconnect and resume; a read failure mid-transfer (`FAILREAD <id> <offset>` directive) giving
`[0x83][06]`.

Consumers: the C engine replays every scenario byte for byte (`firmware/core/test/test_xfer.c`); the TypeScript mock
device replays them too (`app/test/mockDevice.test.ts`); a Python drift guard checks the committed file equals the
generator's output. Python and TypeScript clients are then tested against their device model, with fault injection.

## 4. Firmware

### 4.1 `firmware/core/e32_xfer` (portable, host-tested)

```c
#define E32_XFER_INFO_BYTES 26
#define E32_XFER_MIN_MTU 64
#define E32_XFER_MAX_PAYLOAD 507
enum { E32_XFER_OK = 0, E32_XFER_ENOENT = -1, E32_XFER_EBUSY = -2, E32_XFER_EIO = -3 };
typedef struct {
  void *ctx;
  size_t (*list)(void *ctx, uint32_t *ids, size_t max);                     /* complete notes, ascending */
  int (*stat)(void *ctx, uint32_t id, uint32_t *size);                       /* OK, ENOENT, EBUSY */
  int (*read)(void *ctx, uint32_t id, uint32_t off, uint8_t *buf, size_t len); /* OK or EIO */
  int (*remove)(void *ctx, uint32_t id);                                     /* OK, ENOENT, EBUSY, EIO */
  int (*send)(void *ctx, int channel, const uint8_t *msg, size_t len);       /* channel 0 CTRL, 1 DATA; nonzero = link lost */
  uint64_t (*now_us)(void *ctx);
  uint32_t (*free_bytes)(void *ctx);
  uint8_t (*battery_pct)(void *ctx);                                         /* 255 = unknown */
} e32_xfer_io_t;
typedef struct { uint32_t boot_id; uint8_t fw[3]; uint8_t codecs_mask; } e32_xfer_config_t;
void e32_xfer_init(e32_xfer_t *x, const e32_xfer_io_t *io, const e32_xfer_config_t *cfg);
void e32_xfer_connect(e32_xfer_t *x, uint16_t mtu);
void e32_xfer_set_mtu(e32_xfer_t *x, uint16_t mtu);
void e32_xfer_disconnect(e32_xfer_t *x);
void e32_xfer_request(e32_xfer_t *x, const uint8_t *req, size_t len);  /* answers synchronously through io->send */
bool e32_xfer_pump(e32_xfer_t *x);   /* sends at most one DATA chunk or the final TRANSFER_DONE; true if it sent */
void e32_xfer_info(e32_xfer_t *x, uint8_t out[E32_XFER_INFO_BYTES]);
```

`stat` returning `EBUSY` means "being recorded". The engine itself knows which note it is transferring (DELETE busy
rule). On a resumed GET the engine first reads `[0, offset)` to seed the CRC. All calls come from one task; `send`
blocks until the stack accepts the notification and returns nonzero only if the link is gone (the engine then drops the
transfer).

### 4.2 `firmware/core/e32_button` (portable, host-tested)

Input: raw button level and `now_ms`, every 10 ms. Debounce 30 ms. Output actions: `START`, `STOP`, `CANCEL`,
`ADVERTISE` (long window), `CLEAR_BONDS`.
- Idle, press → `START` at once (recording begins, so the first word is not lost to the press classification).
- That same press held 1.5 s → `CANCEL` (the recorder closes and deletes the note); held 10 s → `CLEAR_BONDS` once.
- Released after `CANCEL` but before 10 s → `ADVERTISE`. Released after `CLEAR_BONDS` → nothing.
- Released before 1.5 s → nothing (recording continues). Recording, a new press → `STOP`.

### 4.3 ESP-IDF glue (`firmware/main`, build-checked only)

- `ble_gatt.{h,c}`: NimBLE host, GATT table (INFO read + encrypted read; CTRL write + encrypted write + notify; DATA
  notify), LE Secure Connections Just Works with bonding stored in NVS, device name `ESPeak32`, the 128-bit service UUID
  in the advertisement and the name in the scan response. A transfer task owns the engine and drains a queue of
  `{connect, mtu, request, disconnect}` events, pumping when idle. `send` uses `ble_gatts_notify_custom`; on mbuf
  exhaustion it waits and retries until the link drops.
  API: `esp_err_t ble_start(void)`, `void ble_advertise_for(uint32_t ms)`, `void ble_clear_bonds(void)`.
- Advertising windows: `ble_advertise_for(60 s)` after a note is saved, `120 s` on `ADVERTISE`, and a fresh 60 s
  window after every disconnect (so a dropped link can resume). A connection holds the window open.
- `recorder.c` uses `e32_button`; `recorder_active_id()` (0 when idle) backs `stat`/`remove` busy answers.
- `store.{h,c}` gains `store_size(id, *size)` and `store_read(id, off, buf, len)` (keeps one cached `FILE*`).
- `sdkconfig.defaults`: Bluetooth + NimBLE, peripheral role only, one connection, NVS persistence, preferred MTU 247.
- LED: on while recording, slow blink while advertising, fast blink on error (as in M1), three quick flashes on bond
  clear.

## 5. Python (`tools/`)

### 5.1 `espeak32/sync.py`

- `Transport` protocol (async): `mtu`, `read_info()`, `write_ctrl(b)`, `next_ctrl(timeout)`, `next_data(timeout)`,
  `close()`; raises `LinkLost`.
- `SyncClient(transport, window=16)`: `set_time(unix_ms)`, `list()`, `fetch(entry, sink)`, `delete(id)`.
- Credit policy (both clients): GET with `window` credits; after every `window // 2` chunks consumed, send
  `CREDIT(window // 2)`.
- Integrity: chunk `seq` must equal the expected value; a gap, a stall (no chunk for 5 s while
  credits are outstanding), `TransferFailed` (retried once per note per sync) or TRANSFER_DONE with fewer bytes than the GET ack's size (after a 2 s grace for in-flight
  chunks) aborts and resumes with GET at the stored offset. TRANSFER_DONE with all bytes → CRC over the whole file must
  equal `file_crc32` and the container must parse; otherwise the partial file is discarded and refetched from 0, once.
- `sync_all(connect, out_dir, delete, now_ms)`: SET_TIME, LIST, fetch each note into `<id:08d>.e32.part`, fsync,
  rename to `.e32` after verification, record the time pair in `out_dir/clock.json`, DELETE only after the rename
  (two-phase). On `LinkLost` it reconnects through `connect()` and resumes, up to 3 attempts.

### 5.2 `espeak32/ble_transport.py` and CLI

`BleakTransport` (bleak >= 1.0, optional extra `ble`) implements `Transport`; it requests pairing when the first
encrypted read fails. CLI: `espeak32 ble scan | info | list | get --id N -o F | rm --id N | sync --out DIR [--delete]
[--wav]`, with `--address` (default: first device advertising the service) and `--window`. Exit codes: 0 ok, 3
protocol/transfer error, 4 device not found.

### 5.3 Tests

`DeviceModel` behind an in-memory `FakeTransport` with fault injection (drop the link after N chunks, drop one chunk,
fail a read). Tests: full sync of two notes; resume after a drop at several points including inside the last chunk and
between TRANSFER_DONE and DELETE; a dropped chunk detected by `seq`; CRC mismatch refetch; DELETE never sent before the
file is renamed; `clock.json` and wall-time conversion. `bleak` is never imported by the test suite.

## 6. PWA (`app/`)

Vite 8, TypeScript 5.9, Vitest 5, Playwright 1.64; no UI framework. Modules:

- `src/format/`: `crc32.ts`, `container.ts`, `adpcm.ts` (decoder), `wav.ts` — checked against `protocol/vectors`.
- `src/ble/`: `protocol.ts` (codec, checked against `ble.json`), `transport.ts` (interface), `webBluetooth.ts`,
  `syncClient.ts` (same rules as 5.1). Reconnect: `navigator.bluetooth.getDevices()` when available, otherwise the
  chooser on a user gesture.
- `src/store/db.ts` (IndexedDB): `notes` (key `"<file_id>:<boot_id>:<start_us>"`, header fields, bytes, wall time),
  `segments` (64 KiB pieces of an in-progress note, so a resume survives an app restart), `clock` (latest SET_TIME pair
  per boot), `settings` (`deleteAfterSync`, default true).
- `src/time.ts` (wall time, section 2.13). `src/ui/`: one screen with Connect/Sync, progress, the synced notes (time,
  duration, Play, Save WAV) and the delete-after-sync toggle.
- `public/`: web manifest, icon, service worker that caches the app shell.

Tests: Vitest for every module (`fake-indexeddb` for the store); `test/mockDevice.ts`, a TypeScript device model that
replays `sync.txt` exactly, then drives `syncClient` with the same fault injection as Python; one Playwright test in
headless Chromium with a fake `navigator.bluetooth` backed by the mock device: connect, sync two notes with a link drop,
see them listed, play one.

## 7. CI and delivery

CI adds: `app` (Node 22: `npm ci`, typecheck, `vitest run`, `vite build`, Playwright Chromium e2e). The existing jobs
cover the new C and Python code. A `pages.yml` workflow builds the app and deploys it to GitHub Pages **only when run
manually** (`workflow_dispatch`), because publishing is the user's call; Pages must also be enabled in the repository
settings. For a first phone test without Pages: `npm run dev -- --host` plus `adb reverse tcp:5173 tcp:5173` gives the
phone a secure `localhost` origin.

`docs/bringup-m2.md`: flash, pair from the PWA and from `espeak32 ble`, sync, cut the link mid-transfer (walk away or
toggle Bluetooth), confirm the resume, confirm DELETE only after the note is saved, measure throughput and MTU, and record
the numbers in `docs/measurements.md`.

## 8. Error handling summary

| Failure | Detected by | Outcome |
|---|---|---|
| Link drop mid-transfer | transport `LinkLost` / GATT disconnect | partial bytes kept; reconnect; GET at stored offset |
| Lost or reordered chunk | `seq` gap | ABORT, GET at stored offset |
| Flash read error | device → `[0x83][06]` | client retries the GET once, then reports the note as failed and keeps it on the device |
| Corrupt stored note | CRC or container parse | refetch from 0 once; then keep it, flag it, never DELETE |
| Note being recorded | `BUSY` | skipped this sync |
| MTU < 64 | status `MTU` | client reports "phone negotiated too small an MTU" |
| Pairing refused | encrypted read fails | client reports pairing needed; CLI offers `--pair` |

## 9. Risks (need the board or the phone)

Chrome-on-Android pairing behaviour with Just Works on an encrypted read; real throughput per window size; NimBLE mbuf
pool sizing under sustained notifications; `getDevices()` support on the user's phone; LittleFS read speed for the CRC
seed on resume.
