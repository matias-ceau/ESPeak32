# M0 + M1: Contract and "Mic Works" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the shared file-format and BLE-message contract with a Python reference implementation and golden test vectors (M0), plus an ESP32-S3 firmware that records INMP441 audio to flash and a PC tool that dumps it over serial and decodes it to WAV (M1).

**Architecture:** `tools/espeak32` (Python) is the reference implementation and generates committed binary vectors in `protocol/vectors/`. Portable C in `firmware/core` reproduces the encoder byte-for-byte against those vectors on the host. The ESP-IDF app in `firmware/main` wires `core` to I2S and LittleFS and exposes `ls`/`dump`/`rm` on the serial console. `espeak32 dump|decode` runs on the PC.

**Tech Stack:** Python >= 3.10 (pytest, pyserial, stdlib only otherwise), C11 + CMake/ctest, ESP-IDF 5.4.x with `joltwallet/littlefs`, ffmpeg (optional test oracle), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-14-espeak32-voice-recorder-design.md` (sections 4.2–4.5, 5, 6.1, 6.3, 7, 8 M0/M1, 9, 10).

## Global Constraints

- Capture: INMP441, **16 kHz mono**, I2S std RX with DMA; the **32-bit slot is reduced to its top 16 bits**, then a **DC-blocking filter and a fixed gain**; L/R pin tied to GND (left channel).
- Codec ids stored per file: **0 = PCM16, 1 = IMA-ADPCM (64 kbps, 8 KB/s), 2 = Opus (reserved; no implementation in this plan)**.
- One file per note: header (magic, format version, codec id, sample rate, `boot_id`, start ticks, CRC) followed by a frame stream; **file ids are a monotonically increasing `u32` kept in NVS**.
- Audio lives in a **LittleFS partition in flash**.
- Firmware is C on ESP-IDF; **pure logic lives in a portable `core/` with no ESP dependencies** so it builds and tests on a host. Board differences live under `boards/` (only `s3` in this plan).
- Python is used for host tooling, tested with pytest.
- Repository layout is fixed by spec section 7 (`docs/ hardware/ protocol/ firmware/ tools/ app/`).
- All multi-byte integers in files and BLE messages are **little-endian**.
- Commit messages end with the attribution trailers already used on this branch.

## Review Focus

Failure modes the spec implies but a straight reading of the tasks would not test. Each has an owning test.

1. **Storage fills mid-note** (ENOSPC). The writer must stop, finalize what it appended, and leave a file that still parses with a valid CRC. Tests: Task 1 `test_parse_finalized_file_with_partial_tail`, Task 7 `writer_sink_full_midway_still_finalizes`.
2. **Power loss mid-note.** An unfinalized file must still decode, with a warning. Tests: Task 1 `test_parse_unfinalized_file`, Task 3 `test_decode_unfinalized_decodes_available_samples_with_warning`.
3. **Corrupted or interrupted serial dump.** The PC tool must fail loudly instead of writing a silently bad file. Tests: Task 9 `test_parse_dump_*`.
4. **Zero-length or one-sample note** (accidental double tap). It must yield a valid file and a valid (possibly empty) WAV. Tests: Task 3 `test_decode_empty_note_writes_empty_wav`, Task 7 `writer_empty_note` and `writer_one_sample_note`.
5. **Clipping and unplugged mic.** Gain must saturate instead of wrapping, and an all-zero input must not crash and must be detectable so the firmware can warn. Tests: Task 7 `dsp_gain_shift_saturates_not_wraps`, `dsp_peak_of_silence_is_zero`.

## Contract (decisions made by this plan; Tasks 1, 2 and 5 write them into `protocol/`)

### File format `.e32` (header is 32 bytes)

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

After the header: frames `[u16 len][len bytes]`, repeated. A trailing partial frame is ignored by readers and by the CRC. PCM16 frames carry up to 512 bytes (256 samples; the last frame may be shorter). ADPCM frames carry exactly one 256-byte block. An empty note is a finalized 32-byte header with `sample_count = 0` and CRC `0`.

### IMA-ADPCM block (WAVE format 0x11, mono, block align 256, 505 samples per block)

- Block header (4 bytes): predictor `i16` = the block's first PCM sample (stored exactly); step index `u8` = encoder index at block start; reserved `0`.
- Then 252 bytes: byte `i` holds sample `2i+1` in the **low** nibble and sample `2i+2` in the **high** nibble.
- Tables: standard 89-entry IMA step table (7 … 32767); `INDEX_ADJ = [-1,-1,-1,-1,2,4,6,8]` indexed by `code & 7`; index clamped to 0..88; initial index 0, carried across blocks.
- **Reconstruction (decoder, and encoder's own tracking):** `d = ((2*(code & 7) + 1) * step) >> 3`; `pred = clamp16(pred - d if code & 8 else pred + d)`. This is FFmpeg's formula; a scratch spike confirmed FFmpeg decodes these blocks bit-exactly and that the classic shift-based formula does not match.
- **Encoder quantiser:** `diff = s - pred; code = min(7, abs(diff) * 4 // step) | (8 if diff < 0 else 0)`.
- The last block is zero-padded to 505 samples; decoders trim to `sample_count`.

### Serial dump lines (firmware -> PC; all other lines, such as ESP log output, are ignored)

```
E32LS <id> <bytes>                 one per file, ascending id
E32LS END
E32DUMP BEGIN <id> <bytes>
E32DUMP D <base64>                 at most 90 raw bytes per line
E32DUMP END <crc32 of the whole file, 8 lowercase hex digits>
E32DUMP ERR <reason>               reasons: notfound, busy, io
E32RM OK <id>   |   E32RM ERR <reason>
```

### BLE messages (full detail in `protocol/PROTOCOL.md`, written in Task 5)

- UUIDs: service `8f05e6c5-7b93-4a53-b175-b3416b3a0d20`; INFO `…e6c6…`, CTRL `…e6c7…`, DATA `…e6c8…`, with the other groups identical to the service UUID.
- INFO (read, 26 bytes): `proto_version u8, battery_pct u8, fw_major u8, fw_minor u8, fw_patch u8, codecs_mask u8 (bit0 PCM16, bit1 ADPCM, bit2 Opus), free_bytes u32, boot_id u32, ticks_us u64, file_count u32`.
- CTRL requests `[op u8][args]`: `1 LIST`; `2 GET file_id u32, offset u32, credits u16`; `3 CREDIT credits u16` (grants more chunks; has no response); `4 DELETE file_id u32`; `5 SET_TIME unix_ms u64`; `6 ABORT`.
- CTRL notifications `[op|0x80][status u8][body]`:
  - LIST: one per file, body `index u16, total u16, file_id u32, size u32, codec u8, boot_id u32, start_us u64`. With no files: a single notification with `index=0,total=0` and no further fields.
  - GET ack: body `file_id u32, total_size u32`.
  - DELETE: body `file_id u32`.
  - SET_TIME: body `ticks_us u64` (the device clock when the command was handled).
  - ABORT: empty body.
  - `0x83 TRANSFER_DONE`: body `file_id u32, file_crc32 u32` (CRC-32 of the whole stored file from byte 0).
- Status: `0 OK, 1 UNKNOWN_OPCODE, 2 BAD_ARGS, 3 NOT_FOUND, 4 BUSY, 5 MTU, 6 IO`. The ATT MTU must be at least 64 bytes or the device answers `5`.
- DATA notification: `[seq u16][payload]`; `seq` starts at 0 for each GET and wraps modulo 65536.

## File Structure

```
.gitignore, README.md
protocol/FILE_FORMAT.md, PROTOCOL.md, vectors/{tone_16k.pcm, tone_16k.adpcm.e32, tone_16k.pcm16.e32,
                                              tone_16k.unfinalized.e32, empty.e32, manifest.json, ble.json}
tools/pyproject.toml
tools/espeak32/{__init__,container,codec,wav,decode,vectors,ble,serial_dump,cli}.py
tools/tests/test_{container,codec,decode,vectors,ble,serial_dump}.py
firmware/core/{CMakeLists.txt, include/e32_*.h, src/e32_*.c, test/*.c}     host-testable C
firmware/{CMakeLists.txt, sdkconfig.defaults, partitions.csv}
firmware/main/{CMakeLists.txt, idf_component.yml, Kconfig.projbuild, main.c, audio_capture.*, store.*, recorder.*, console.*}
hardware/{bom.md, wiring-v0-s3.md}
docs/{bringup-m1.md, measurements.md}
.github/workflows/ci.yml
```

---

### Task 1: Python scaffold and file container

**Files:**
- Create: `.gitignore`, `README.md`, `tools/pyproject.toml`, `tools/espeak32/__init__.py`, `tools/espeak32/container.py`, `tools/tests/test_container.py`, `protocol/FILE_FORMAT.md`

**Interfaces:**
- Produces (`espeak32.container`):
  ```python
  CODEC_PCM16, CODEC_ADPCM, CODEC_OPUS = 0, 1, 2
  HEADER_BYTES = 32
  UNFINALIZED = 0xFFFFFFFF
  class FormatError(ValueError): ...
  @dataclass(frozen=True)
  class Header: codec: int; sample_rate: int; file_id: int; boot_id: int; start_us: int; sample_count: int; payload_crc32: int; version: int = 1
  @dataclass(frozen=True)
  class E32File: header: Header; frames: list[bytes]; finalized: bool; crc_ok: bool | None; truncated: bool
  def pack_header(h: Header) -> bytes
  def unpack_header(b: bytes) -> Header            # raises FormatError on short input, bad magic, version != 1
  def pack_frame(payload: bytes) -> bytes          # u16 length prefix + payload
  def build(codec: int, sample_rate: int, file_id: int, boot_id: int, start_us: int, sample_count: int, frames: list[bytes]) -> bytes   # finalized file with the correct CRC
  def parse(data: bytes) -> E32File                # crc_ok is None when unfinalized
  ```

- [ ] **Step 1: Scaffold.** `.gitignore` (`.venv/`, `__pycache__/`, `*.egg-info/`, `build/`, `sdkconfig`, `sdkconfig.old`, `managed_components/`, `dependencies.lock`). `README.md` skeleton: what the project is, status (M0/M1 in progress), the directory layout, and a **Privacy** paragraph stating that audio and text will be sent to third-party model providers through OpenRouter and that identifiable patient information must not be dictated. `tools/pyproject.toml`: setuptools, name `espeak32-tools`, `requires-python >=3.10`, dependency `pyserial>=3.5`, extra `dev = ["pytest>=8"]`, script `espeak32 = "espeak32.cli:main"`, packages `["espeak32"]`. `__init__.py` holds `__version__ = "0.1.0"`.
  Run: `python3 -m venv .venv && .venv/bin/pip install -e 'tools[dev]' && .venv/bin/pytest tools/tests -q`
  Expected: install succeeds; pytest reports no tests collected.
- [ ] **Step 2: Write the failing tests** in `tools/tests/test_container.py`:
  - `test_pack_header_known_bytes`: `Header(codec=1, sample_rate=16000, file_id=1, boot_id=2, start_us=0x0102030405060708, sample_count=505, payload_crc32=0xDEADBEEF)` packs to `bytes.fromhex("45333241 01 01 803e 01000000 02000000 0807060504030201 f9010000 efbeadde")`; `unpack_header` of those bytes returns the same `Header`.
  - `test_unpack_header_rejects_bad_input`: wrong magic, version 2, and 31-byte input each raise `FormatError`.
  - `test_build_then_parse_roundtrip`: two frames; parse gives `finalized=True`, `crc_ok=True`, `truncated=False`, frames equal, `header.sample_count` as passed.
  - `test_parse_detects_payload_corruption`: flip one bit inside a frame payload -> `crc_ok is False`.
  - `test_parse_unfinalized_file`: header with `sample_count=UNFINALIZED`, CRC 0, plus two frames -> `finalized=False`, `crc_ok is None`, both frames returned.
  - `test_parse_drops_truncated_tail_frame`: unfinalized file whose last frame declares 20 bytes but has 7 -> that frame is excluded and `truncated=True`.
  - `test_parse_finalized_file_with_partial_tail`: a finalized file with the CRC over the complete frames, then 3 stray bytes -> `crc_ok=True`, `truncated=True`.
  - `test_empty_note`: `build(..., sample_count=0, frames=[])` is exactly 32 bytes; parse gives `frames == []`, `crc_ok=True`.
- [ ] **Step 3: Run `.venv/bin/pytest tools/tests/test_container.py -q`.** Expected: FAIL (`ModuleNotFoundError: espeak32.container`).
- [ ] **Step 4: Implement `container.py`** per the Interfaces block and the Contract table. CRC with `zlib.crc32` over the complete-frame bytes; `parse` walks frames until the data runs out or a declared length overruns.
- [ ] **Step 5: Run the tests.** Expected: all PASS.
- [ ] **Step 6: Write `protocol/FILE_FORMAT.md`** from the Contract "File format" section (header table, frame rules, finalization and truncation semantics, empty-note rule). Codec details are appended in Task 2.
- [ ] **Step 7: Commit.** `git add .gitignore README.md tools protocol/FILE_FORMAT.md && git commit -m "feat(tools): scaffold Python package and .e32 container"`

---

### Task 2: Reference codecs (IMA-ADPCM and PCM16)

**Files:**
- Create: `tools/espeak32/codec.py`, `tools/tests/test_codec.py`
- Modify: `protocol/FILE_FORMAT.md` (append the "IMA-ADPCM block" and PCM16 sections from the Contract)

**Interfaces:**
- Consumes: `espeak32.container.CODEC_*`.
- Produces (`espeak32.codec`):
  ```python
  BLOCK_BYTES = 256; BLOCK_SAMPLES = 505; PCM_FRAME_SAMPLES = 256
  class UnsupportedCodec(ValueError): ...
  def adpcm_encode(pcm: Sequence[int]) -> list[bytes]                         # list of 256-byte blocks; [] for empty input
  def adpcm_decode(blocks: Iterable[bytes], sample_count: int) -> list[int]
  def pcm16_encode(pcm: Sequence[int]) -> list[bytes]                         # frames of up to 512 bytes
  def pcm16_decode(frames: Iterable[bytes], sample_count: int) -> list[int]
  def decode_frames(codec: int, frames: Iterable[bytes], sample_count: int) -> list[int]   # raises UnsupportedCodec for codec 2 or unknown
  ```

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_codec.py`. Test signal: `int(9000*sin(2π·440·n/16000) + 3000*sin(2π·1230·n/16000))` for `n` in `range(2020)`.
  - `test_adpcm_golden_first_bytes`: pcm `[0, 7] + [0]*503` -> one block; `len == 256`, `block[:4] == bytes(4)`, `block[4] == 0xB4`.
  - `test_adpcm_silence_is_all_zero`: 505 zeros -> block of 256 zero bytes.
  - `test_adpcm_pads_and_trims`: 1000 samples -> 2 blocks; `adpcm_decode(blocks, 1000)` returns 1000 samples.
  - `test_adpcm_first_sample_of_each_block_is_exact`: decoded `[0]` and `[505]` equal the input.
  - `test_adpcm_roundtrip_snr_at_least_20db` on the test signal (spike measured 24.1 dB).
  - `test_adpcm_matches_ffmpeg` (skip when `ffmpeg` is not on PATH): wrap the blocks in a WAV with format tag `0x11`, 1 channel, 16000 Hz, block align 256, 4 bits, `cbSize=2`, `wSamplesPerBlock=505`, plus a `fact` chunk; run `ffmpeg -v error -i f.wav -f s16le -acodec pcm_s16le out.raw`; the result equals `adpcm_decode` exactly.
  - `test_adpcm_extremes_do_not_overflow`: alternating `±32767` for 1010 samples encodes and decodes with all outputs inside int16.
  - `test_adpcm_empty_input`: `adpcm_encode([]) == []`.
  - `test_pcm16_frames`: 600 samples -> frame lengths `[512, 512, 176]`; roundtrip is exact.
  - `test_decode_frames_rejects_opus`: codec 2 raises `UnsupportedCodec`.
- [ ] **Step 2: Run `.venv/bin/pytest tools/tests/test_codec.py -q`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement `codec.py`** following the Contract: shared `_reconstruct(pred, index, code)` used by encoder and decoder, so they cannot drift.
- [ ] **Step 4: Run the tests.** Expected: all PASS (the ffmpeg test passes here, since ffmpeg 6.1 is installed).
- [ ] **Step 5: Append the codec sections to `protocol/FILE_FORMAT.md`, then commit.** `git add tools protocol && git commit -m "feat(tools): IMA-ADPCM and PCM16 reference codecs"`

---

### Task 3: Decode pipeline, WAV output and `espeak32 decode`

**Files:**
- Create: `tools/espeak32/wav.py`, `tools/espeak32/decode.py`, `tools/espeak32/cli.py`, `tools/tests/test_decode.py`

**Interfaces:**
- Consumes: `container.parse`, `codec.decode_frames`, `codec.BLOCK_SAMPLES`.
- Produces:
  ```python
  # wav.py
  def write_wav(path_or_file, samples: Sequence[int], sample_rate: int) -> None      # 16-bit mono PCM WAV
  # decode.py
  @dataclass
  class DecodeResult: sample_rate: int; samples: list[int]; warnings: list[str]; crc_ok: bool | None
  def decode_e32(data: bytes) -> DecodeResult
  # cli.py
  def main(argv: Sequence[str] | None = None) -> int
  # command: espeak32 decode IN.e32 -o OUT.wav [--force]
  # exit codes: 0 ok, 2 CRC mismatch (no output unless --force)
  ```
  For an unfinalized file `decode_e32` takes the sample count from the frames (ADPCM: `blocks * 505`; PCM16: sum of frame bytes / 2) and appends the warning `"file not finalized (recording was interrupted)"`. A truncated tail adds a warning containing `"truncated"`. An empty note adds `"empty recording"`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_decode.py`:
  - `test_decode_roundtrip_wav`: build an ADPCM `.e32` from the tone, decode to a WAV file, read it with stdlib `wave`: 1 channel, sample width 2, rate 16000, `nframes == sample_count`.
  - `test_decode_unfinalized_decodes_available_samples_with_warning`: unfinalized ADPCM file with 3 full blocks -> 1515 samples and a warning containing `"not finalized"`.
  - `test_decode_crc_mismatch_exit_code_2`: corrupt one payload bit; `main(["decode", in, "-o", out])` returns 2 and `out` does not exist; with `--force` it returns 0 and writes the file.
  - `test_decode_empty_note_writes_empty_wav`: returns 0; WAV has 0 frames; stderr contains `"empty recording"`.
  - `test_decode_pcm16_file`: PCM16 `.e32` decodes to the original samples.
- [ ] **Step 2: Run `.venv/bin/pytest tools/tests/test_decode.py -q`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement the three modules.** `cli.py` uses `argparse` with subcommands; later tasks add `ls`, `dump`, `rm`. Warnings go to stderr.
- [ ] **Step 4: Run the full suite `.venv/bin/pytest tools/tests -q`.** Expected: all PASS.
- [ ] **Step 5: Commit.** `git add tools && git commit -m "feat(tools): decode .e32 to WAV via espeak32 decode"`

---

### Task 4: Golden vectors and drift guard

**Files:**
- Create: `tools/espeak32/vectors.py`, `tools/tests/test_vectors.py`, `protocol/vectors/*` (generated, committed)

**Interfaces:**
- Consumes: `container.build/pack_header/pack_frame`, `codec.*`.
- Produces: `generate(out_dir: Path) -> dict[str, bytes]` (reads `tone_16k.pcm` from `out_dir`, returns every derived artefact keyed by filename); CLI `python -m espeak32.vectors <dir> [--regen-pcm]`.
- Vector set (all with `file_id=1, boot_id=2, start_us=0x0102030405060708, sample_rate=16000`):
  - `tone_16k.pcm`: 16000 raw little-endian int16 samples, the test signal from Task 2 for `n` in `range(16000)`. This is the committed source of truth, so no cross-platform `sin()` rounding can cause drift.
  - `tone_16k.adpcm.e32` (codec 1) and `tone_16k.pcm16.e32` (codec 0), both finalized with `sample_count=16000`.
  - `tone_16k.unfinalized.e32`: the ADPCM file with `sample_count=0xFFFFFFFF`, CRC 0, and the last frame cut in half.
  - `empty.e32`: ADPCM, finalized, zero frames.
  - `manifest.json`: per file `{name, codec, sample_rate, sample_count, finalized, payload_crc32 (hex string), bytes}`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_vectors.py`:
  - `test_committed_vectors_match_generator`: `generate(protocol/vectors)` output equals the committed bytes for every file except `tone_16k.pcm`.
  - `test_pcm_vector_has_16000_samples`: file size is 32000 bytes.
  - `test_manifest_matches_files`: for each finalized entry, `container.parse(file).header.payload_crc32` equals the manifest value.
  - `test_unfinalized_vector_parses_as_unfinalized_and_truncated`.
- [ ] **Step 2: Run `.venv/bin/pytest tools/tests/test_vectors.py -q`.** Expected: FAIL (import error / missing files).
- [ ] **Step 3: Implement `vectors.py`.** Then run `.venv/bin/python -m espeak32.vectors protocol/vectors --regen-pcm` once to create the files.
- [ ] **Step 4: Run the full suite.** Expected: all PASS; `git status` shows only the new vector files.
- [ ] **Step 5: Commit.** `git add tools protocol/vectors && git commit -m "feat(protocol): golden test vectors with drift guard"`

---

### Task 5: BLE message codec and PROTOCOL.md

**Files:**
- Create: `tools/espeak32/ble.py`, `tools/tests/test_ble.py`, `protocol/PROTOCOL.md`, `protocol/vectors/ble.json`

**Interfaces:**
- Produces (`espeak32.ble`):
  ```python
  SERVICE_UUID = "8f05e6c5-7b93-4a53-b175-b3416b3a0d20"   # INFO_UUID/CTRL_UUID/DATA_UUID: first group e6c6/e6c7/e6c8
  OP_LIST, OP_GET, OP_CREDIT, OP_DELETE, OP_SET_TIME, OP_ABORT = 1, 2, 3, 4, 5, 6
  EV_TRANSFER_DONE = 0x83
  STATUS_OK, STATUS_UNKNOWN_OPCODE, STATUS_BAD_ARGS, STATUS_NOT_FOUND, STATUS_BUSY, STATUS_MTU, STATUS_IO = range(7)
  class ProtocolError(ValueError): ...
  @dataclass(frozen=True) class Info: proto_version: int; battery_pct: int; fw: tuple[int, int, int]; codecs_mask: int; free_bytes: int; boot_id: int; ticks_us: int; file_count: int
  def pack_info(i: Info) -> bytes;  def unpack_info(b: bytes) -> Info
  def req_list() -> bytes;  def req_get(file_id: int, offset: int, credits: int) -> bytes;  def req_credit(credits: int) -> bytes
  def req_delete(file_id: int) -> bytes;  def req_set_time(unix_ms: int) -> bytes;  def req_abort() -> bytes
  # CTRL notifications, all frozen dataclasses; every one except ErrorAck implies status OK:
  #   ListEntry(index, total, file_id, size, codec, boot_id, start_us) | GetAck(file_id, total_size) | DeleteAck(file_id)
  #   | SetTimeAck(ticks_us) | AbortAck() | TransferDone(file_id, file_crc32) | ErrorAck(op, status)   # op is the request opcode without the 0x80 bit
  CtrlMessage = ListEntry | GetAck | DeleteAck | SetTimeAck | AbortAck | TransferDone | ErrorAck
  def pack_ctrl(msg: CtrlMessage) -> bytes       # ListEntry with total == 0 emits only the 4-byte index/total body
  def decode_ctrl(msg: bytes) -> CtrlMessage     # a no-files LIST decodes to ListEntry(0, 0, 0, 0, 0, 0, 0); any non-OK status decodes to ErrorAck
  def pack_data_chunk(seq: int, payload: bytes) -> bytes;  def unpack_data_chunk(b: bytes) -> tuple[int, bytes]
  def generate_vectors() -> dict     # JSON-serialisable list of {name, hex, decoded}
  ```

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_ble.py`:
  - `test_pack_info_golden`: `Info(1, 87, (0,1,0), 0b011, 2_500_000, 5, 1_000_000, 3)` packs to `bytes.fromhex("01 57 00 01 00 03 a0252600 05000000 40420f0000000000 03000000")` (26 bytes); unpack returns the same value.
  - `test_req_get_golden`: `req_get(7, 0x100, 8) == bytes.fromhex("02 07000000 00010000 0800")`.
  - `test_req_set_time_golden`: `req_set_time(0x0102030405060708) == bytes.fromhex("05 0807060504030201")`; `req_abort() == b"\x06"`; `req_list() == b"\x01"`.
  - `test_ctrl_roundtrip_each_message`: `decode_ctrl(pack_ctrl(m)) == m` for one instance of every message type, including a populated `ListEntry` and the no-files `ListEntry(0, 0, 0, 0, 0, 0, 0)` (whose packed form is exactly `bytes.fromhex("81 00 0000 0000")`: opcode `0x81`, status `0`, `index u16 = 0`, `total u16 = 0`).
  - `test_transfer_done_has_op_0x83`: first byte is `0x83`.
  - `test_error_status_decodes_to_error_ack`: `b"\x82\x03"` -> `ErrorAck(op=OP_GET, status=STATUS_NOT_FOUND)`.
  - `test_decode_rejects_short_and_unknown`: truncated bodies and opcode `0x7f` raise `ProtocolError`.
  - `test_data_chunk_seq_wrap`: `pack_data_chunk(65535, b"ab") == bytes.fromhex("ffff 6162")`; `pack_data_chunk(65536, ...)` raises `ProtocolError`.
  - `test_ble_vectors_in_sync`: `generate_vectors()` equals the JSON in `protocol/vectors/ble.json`.
- [ ] **Step 2: Run `.venv/bin/pytest tools/tests/test_ble.py -q`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement `ble.py`** per the Contract "BLE messages". Then generate `protocol/vectors/ble.json` (`python -m espeak32.ble protocol/vectors/ble.json`).
- [ ] **Step 4: Write `protocol/PROTOCOL.md`**: the Contract "BLE messages" section made normative, plus the sequence for a sync (`SET_TIME` -> `LIST` -> `GET` + `CREDIT`s -> `TRANSFER_DONE` -> app persists and verifies CRC -> `DELETE`), the resume-by-offset rule, and the credit rule (the device sends at most `credits` DATA chunks, then waits for `CREDIT`). Note that `CREDIT` and the `file_count` field in INFO are additions to the spec's command list that the credit window and the file list need.
- [ ] **Step 5: Run the full suite.** Expected: all PASS.
- [ ] **Step 6: Commit.** `git add tools protocol && git commit -m "feat(protocol): BLE message codec, vectors and PROTOCOL.md"`

---

### Task 6: C core, part 1: CRC-32, header/frame packing, ADPCM encoder

**Files:**
- Create: `firmware/core/CMakeLists.txt`, `firmware/core/include/{e32_crc32.h,e32_container.h,e32_adpcm.h}`, `firmware/core/src/{e32_crc32.c,e32_container.c,e32_adpcm.c}`, `firmware/core/test/{test_util.h,test_crc32.c,test_container.c,test_adpcm.c}`

**Interfaces:**
- Produces:
  ```c
  // e32_crc32.h
  uint32_t e32_crc32_update(uint32_t crc, const uint8_t *data, size_t len);   // crc starts at 0; chained calls equal one call (zlib semantics)
  // e32_container.h
  #define E32_HEADER_BYTES 32
  #define E32_UNFINALIZED 0xFFFFFFFFu
  enum { E32_CODEC_PCM16 = 0, E32_CODEC_ADPCM = 1, E32_CODEC_OPUS = 2 };
  typedef struct { uint8_t version, codec; uint16_t sample_rate; uint32_t file_id, boot_id; uint64_t start_us; uint32_t sample_count, payload_crc32; } e32_header_t;
  void   e32_header_pack(const e32_header_t *h, uint8_t out[E32_HEADER_BYTES]);
  int    e32_header_unpack(const uint8_t in[E32_HEADER_BYTES], e32_header_t *h);   // 0 ok, -1 bad magic, -2 bad version
  size_t e32_frame_pack(const uint8_t *payload, uint16_t len, uint8_t *out);       // writes u16 len + payload, returns len + 2
  // e32_adpcm.h
  #define E32_ADPCM_BLOCK_BYTES 256
  #define E32_ADPCM_BLOCK_SAMPLES 505
  typedef struct { uint8_t index; } e32_adpcm_enc_t;
  void e32_adpcm_enc_init(e32_adpcm_enc_t *st);                                    // index = 0
  void e32_adpcm_encode_block(e32_adpcm_enc_t *st, const int16_t pcm[E32_ADPCM_BLOCK_SAMPLES], uint8_t out[E32_ADPCM_BLOCK_BYTES]);
  ```
- CMake: a static library `e32core` (C11, `-Wall -Wextra -Werror`), `enable_testing()`, one executable and one `add_test` per file in `test/`, and `-DE32_VECTOR_DIR="<abs path to protocol/vectors>"` as a compile definition. `test_util.h` provides `CHECK(cond)`, `CHECK_EQ_U64(a, b)`, `read_file(path, &len)` (**fails the test if the file is missing or empty**, so a vector that was never read can never pass silently), and a memory sink with a capacity limit that appends all-or-nothing (used from Task 7).

- [ ] **Step 1: Write the failing tests.**
  - `test_crc32.c`: `e32_crc32_update(0, "123456789", 9) == 0xCBF43926`; update over two halves equals one call; `e32_crc32_update(0, NULL, 0) == 0`.
  - `test_container.c`: `header_pack` of the Task 1 golden header produces the same 32 bytes as the Python test; unpack roundtrips; bad magic returns `-1`; version 2 returns `-2`; `e32_frame_pack({1,2,3}, 3, out)` returns 5 and writes `03 00 01 02 03`.
  - `test_adpcm.c`: `golden_first_bytes` (pcm `[0,7,0…]` -> `out[0..3] == 0`, `out[4] == 0xB4`); `silence_block_is_zero`; `matches_vector`: read `tone_16k.pcm`, encode all blocks with carried state (zero-padding the last), and compare each against the frame payloads of `tone_16k.adpcm.e32` (skip the 32-byte header, walk `u16 len + payload`).
- [ ] **Step 2: Build and run.** `cmake -S firmware/core -B build/core && cmake --build build/core && ctest --test-dir build/core --output-on-failure`
  Expected: build FAILS (missing sources).
- [ ] **Step 3: Implement the three C files** per the Contract. The encoder uses a single `reconstruct()` helper for its own tracking; `abs(diff) * 4 / step` in `int32_t`.
- [ ] **Step 4: Rebuild and run ctest.** Expected: 100% tests passed.
- [ ] **Step 5: Commit.** `git add firmware/core && git commit -m "feat(core): CRC-32, header packing and ADPCM encoder in portable C"`

---

### Task 7: C core, part 2: DSP front-end and note writer

**Files:**
- Create: `firmware/core/include/{e32_dsp.h,e32_writer.h}`, `firmware/core/src/{e32_dsp.c,e32_writer.c}`, `firmware/core/test/{test_dsp.c,test_writer.c}`
- Modify: `firmware/core/CMakeLists.txt` (new sources and tests)

**Interfaces:**
- Consumes: Task 6 headers.
- Produces:
  ```c
  // e32_dsp.h
  typedef struct { int32_t prev_in, prev_out; int gain_shift; } e32_dsp_t;
  void    e32_dsp_init(e32_dsp_t *st, int gain_shift);                                 // gain_shift 0..6
  void    e32_dsp_process(e32_dsp_t *st, const int32_t *slots, int16_t *out, size_t n);
  int16_t e32_peak_abs(const int16_t *pcm, size_t n);                                  // max |sample| saturated to 32767; 0 for n == 0
  // e32_writer.h
  typedef struct { int (*append)(void *ctx, const uint8_t *data, size_t len);          // 0 ok, nonzero error
                   int (*rewrite_header)(void *ctx, const uint8_t header[E32_HEADER_BYTES]);
                   void *ctx; } e32_sink_t;
  typedef struct e32_writer { /* implementation-defined; stack-allocatable, under 2 KB */ } e32_writer_t;
  int e32_writer_open(e32_writer_t *w, uint8_t codec, uint16_t sample_rate, uint32_t file_id,
                      uint32_t boot_id, uint64_t start_us, e32_sink_t sink);           // 0 ok, -1 unsupported codec, -2 sink error
  int e32_writer_push(e32_writer_t *w, const int16_t *pcm, size_t n);                  // 0 ok; -2 sticky sink error
  int e32_writer_close(e32_writer_t *w);                                               // always attempts rewrite_header; returns 0 or the first sticky error
  ```
- DSP per sample: `x = slot >> 16` (arithmetic shift, so the top 16 bits); `y = x - prev_in + ((prev_out * 32604) >> 15)` (a DC blocker with R about 0.995); `out = clamp16(y * (1 << gain_shift))`; update `prev_in = x`, `prev_out = y` (the pre-gain value).
- Writer semantics: `open` appends an unfinalized header (`sample_count = E32_UNFINALIZED`, CRC 0). `push` buffers samples; for each full block (ADPCM 505 samples, PCM16 256 samples) it encodes, appends `[u16 len][payload]` as one `append` call, and CRCs those bytes. `close` flushes a partial block (ADPCM zero-padded to 505, PCM16 written short), then calls `rewrite_header` with the finalized header. `sample_count` is the number of samples actually pushed, capped to the samples in fully appended frames after a sink error; the CRC covers complete frames only.

- [ ] **Step 1: Write the failing tests.**
  - `test_dsp.c`: `dsp_constant_input_decays_to_zero` (4000 slots of `1000 << 16`, shift 0 -> `abs(out[3999]) <= 1`); `dsp_gain_shift_saturates_not_wraps` (gain_shift 3: slot `0x7FFF0000` -> 32767 and slot `0x80000000` -> -32768 on a fresh state); `dsp_peak_of_silence_is_zero` (1000 zero slots process without fault, every output is 0, and `e32_peak_abs` of them is 0); `dsp_peak_abs_basic` (`{-5, 3, 4}` -> 5; `n == 0` -> 0); `dsp_peak_abs_saturates` (a buffer containing `-32768` -> 32767).
  - `test_writer.c`: `writer_matches_vector_byte_exact_adpcm` (push `tone_16k.pcm` in chunks cycling through sizes 160, 1, 1000, 333; memory-sink bytes equal `tone_16k.adpcm.e32`; header args `file_id=1, boot_id=2, start_us=0x0102030405060708`); `writer_matches_vector_byte_exact_pcm16` (vs `tone_16k.pcm16.e32`); `writer_empty_note` (open then close equals `empty.e32`); `writer_one_sample_note` (one pushed sample gives a 32-byte header plus one 258-byte ADPCM frame and `sample_count == 1`); `writer_rejects_opus` (`-1`); `writer_sink_full_midway_still_finalizes` (sink capacity 2000 bytes: `push` eventually returns `-2`; `close` returns `-2` yet `rewrite_header` was called once; the header `sample_count == 505 * (complete frames appended)` and `payload_crc32` equals the CRC of the complete-frame bytes held in the sink).
- [ ] **Step 2: Build and run ctest.** Expected: FAIL (missing sources).
- [ ] **Step 3: Implement `e32_dsp.c` and `e32_writer.c`.**
- [ ] **Step 4: Rebuild and run ctest.** Expected: 100% tests passed (crc32, container, adpcm, dsp, writer).
- [ ] **Step 5: Commit.** The byte-exact `writer_matches_vector_byte_exact_*` tests are the C-versus-Python cross-check; no further step is needed. `git add firmware/core && git commit -m "feat(core): DSP front-end and streaming note writer"`

---

### Task 8: ESP-IDF recorder firmware (ESP32-S3) and v0 hardware docs

**Files:**
- Create: `firmware/CMakeLists.txt`, `firmware/sdkconfig.defaults`, `firmware/partitions.csv`, `firmware/main/{CMakeLists.txt,idf_component.yml,Kconfig.projbuild,main.c,audio_capture.h,audio_capture.c,store.h,store.c,recorder.h,recorder.c}`, `hardware/bom.md`, `hardware/wiring-v0-s3.md`
- Modify: `firmware/core/CMakeLists.txt` (when `IDF_PATH` is set, register as an ESP-IDF component with the same sources; otherwise keep the host library and tests)

**Interfaces:**
- Consumes: `e32_dsp_*`, `e32_writer_*`, `e32_sink_t`.
- Produces (used by Task 9):
  ```c
  // audio_capture.h
  esp_err_t audio_capture_start(void);                                   // I2S std RX, 16 kHz, 32-bit slot, left channel, DMA
  int       audio_capture_read(int32_t *slots, size_t max_slots, uint32_t timeout_ms);   // slots read, or -1 on error
  void      audio_capture_stop(void);
  // store.h
  esp_err_t store_init(void);                                            // NVS + LittleFS mounted at "/audio"; increments and persists boot_id
  uint32_t  store_boot_id(void);
  uint32_t  store_next_file_id(void);                                    // monotonic, persisted in NVS key "next_id", first value 1
  bool      store_sink_open(uint32_t file_id, e32_sink_t *sink, void **handle);   // creates /audio/%08u.e32 ("w+b")
  void      store_sink_close(void *handle);
  size_t    store_free_bytes(void);
  size_t    store_list(uint32_t *ids, size_t max);                       // ascending ids, returns count
  bool      store_path(uint32_t id, char *out, size_t out_len);
  esp_err_t store_delete(uint32_t id);
  // recorder.h
  bool recorder_is_recording(void);
  void recorder_run(void);                                               // never returns
  ```
- Kconfig (`ESPEAK32_*`): `PIN_I2S_BCLK=4`, `PIN_I2S_WS=5`, `PIN_I2S_SD=6`, `PIN_BUTTON=7` (active low, internal pull-up), `PIN_LED=8`, `MIC_GAIN_SHIFT=2` (range 0..6), `CODEC` choice (ADPCM default, PCM16 for debugging), `MAX_NOTE_SECONDS=300`.
- `partitions.csv` (8 MB flash): `nvs, data, nvs, 0x9000, 0x6000`; `phy_init, data, phy, 0xf000, 0x1000`; `factory, app, factory, 0x10000, 0x180000`; `audio, data, littlefs, 0x190000, 0x660000`. `sdkconfig.defaults`: target `esp32s3`, 8 MB flash, partition table `partitions.csv`.
- Recorder behaviour: button polled every 10 ms with 30 ms debounce; press while idle starts a note (`store_next_file_id`, open sink, `e32_writer_open` with `start_us = esp_timer_get_time()`); each loop reads 320 slots, runs the DSP, pushes to the writer; LED on while recording. A press while recording, `MAX_NOTE_SECONDS`, `store_free_bytes()` dropping below 64 KiB (headroom, because LittleFS rewrites the header copy-on-write and needs free space for it), or a writer error stops the note and calls `e32_writer_close`; an error also blinks the LED fast for 3 s. If the peak of the first 2 s of a note is at most 2, log a warning that the mic appears silent and to check wiring (SD, WS, BCLK, and L/R tied to GND). On stop, log `saved note id=<id> samples=<n> bytes=<n>`.

- [ ] **Step 1: Create the project files** above. Pin the `joltwallet/littlefs` version in `idf_component.yml` (compatible with IDF 5.4; use the newest release the component registry lists for it). Keep application logic out of `main.c` beyond `store_init(); audio_capture_start(); recorder_run();`.
- [ ] **Step 2: Write the hardware docs.** `hardware/bom.md`: parts used in v0 with the exact modules from the spec (ESP32-S3 dev board, INMP441, tact switch, LED + 330 Ω resistor, USB cable; battery parts listed as "not used in v0"). `hardware/wiring-v0-s3.md`: pin table matching the Kconfig defaults (INMP441 VDD->3V3, GND->GND, SCK->GPIO4, WS->GPIO5, SD->GPIO6, **L/R->GND**), button GPIO7 to GND, LED GPIO8 through 330 Ω to GND; a warning to avoid strapping pins (0, 3, 45, 46), USB pins (19, 20) and flash/PSRAM pins; a note that boards such as the S3 camera board need different pins set through `idf.py menuconfig`.
- [ ] **Step 3: Build.** If Docker works: `docker run --rm -v "$PWD":/p -w /p/firmware espressif/idf:<v5.4.x tag> idf.py set-target esp32s3 build` (verify the tag exists first with `docker manifest inspect`). Otherwise rely on the CI job from Task 10.
  Expected: `Project build complete`, and `firmware/build/*.bin` exist. Host `ctest` from Task 7 still passes (`cmake --build build/core && ctest --test-dir build/core`).
- [ ] **Step 4: Commit.** `git add firmware hardware && git commit -m "feat(firmware): S3 recorder app with I2S capture, LittleFS store and v0 wiring docs"`

---

### Task 9: Serial `ls`/`dump`/`rm` on the device and `espeak32 ls|dump|rm` on the PC

**Files:**
- Create: `firmware/main/console.{h,c}`, `tools/espeak32/serial_dump.py`, `tools/tests/test_serial_dump.py`
- Modify: `firmware/main/main.c` (start the console before `recorder_run`, which must run in its own task), `firmware/main/Kconfig.projbuild` (console choice: USB-Serial-JTAG default, UART with baud 921600), `tools/espeak32/cli.py` (subcommands)

**Interfaces:**
- Firmware (`console.h`): `void console_start(void);` spawns the `esp_console` REPL task and returns (so `app_main` can then call `recorder_run()`); it registers the commands `ls`, `dump <id>`, `rm <id>`, `rmall` on `esp_console`. Output follows the Contract "Serial dump lines". `dump` and `rm` of the active note answer `E32DUMP ERR busy`; unknown ids answer `ERR notfound`. `dump` prints base64 lines with `mbedtls_base64_encode` and the final CRC from `e32_crc32_update` over the whole file.
- Python (`serial_dump.py`):
  ```python
  class DumpError(RuntimeError): ...
  def parse_ls(lines: Iterable[str]) -> list[tuple[int, int]]                 # [(id, bytes)]
  def parse_dump(lines: Iterable[str]) -> bytes                               # validates length and CRC; ignores non-E32 lines
  def format_dump(data: bytes, file_id: int) -> list[str]                     # the firmware's output format, used by tests and any simulator
  def fetch_ls(port) -> list[tuple[int, int]];  def fetch_file(port, file_id: int) -> bytes;  def remove_file(port, file_id: int) -> None
  # `port` is any object with write(bytes) and readline() -> bytes (b"" on timeout); pyserial's Serial satisfies it
  ```
  CLI: `espeak32 ls --port P [--baud 115200]`; `espeak32 dump --port P --id N -o FILE.e32 [--decode FILE.wav] [--baud 115200]`; `espeak32 rm --port P --id N [--baud 115200]`; exit code 3 on `DumpError`. The entry point becomes `main(argv: Sequence[str] | None = None, open_port: Callable[[str, int], Port] | None = None) -> int`, where `open_port(port_name, baud)` defaults to `serial.Serial(port_name, baudrate=baud, timeout=2)`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_serial_dump.py` (use a `FakeSerial` that replays prepared lines):
  - `test_parse_dump_roundtrip_with_log_noise`: `format_dump(tone_16k.adpcm.e32 bytes, 1)` with ESP log lines (`I (1234) rec: ...`) interleaved -> equals the original bytes.
  - `test_parse_dump_rejects_bad_base64`, `test_parse_dump_rejects_missing_end`, `test_parse_dump_rejects_length_mismatch`, `test_parse_dump_rejects_crc_mismatch` (each raises `DumpError`).
  - `test_parse_dump_reports_device_error`: `E32DUMP ERR busy` -> `DumpError` whose message contains `busy`.
  - `test_parse_ls`: two `E32LS` lines and `E32LS END` -> `[(1, 8226), (2, 120)]`; an empty list is `[]`.
  - `test_cli_dump_writes_file_and_wav`: `main(["dump", ...])` with an injected port factory writes the `.e32` and a WAV; exit code 0.
  - `test_cli_dump_corruption_exits_3_and_writes_nothing`.
- [ ] **Step 2: Run `.venv/bin/pytest tools/tests/test_serial_dump.py -q`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement `serial_dump.py` and the CLI subcommands.** The port factory defaults to `serial.Serial(port, baudrate=args.baud, timeout=2)` and is injectable for tests; send `ls\n`, `dump N\n`, `rm N\n`.
- [ ] **Step 4: Run the full Python suite.** Expected: all PASS.
- [ ] **Step 5: Implement `console.c` and wire it in; rebuild the firmware as in Task 8 Step 3.** Expected: `Project build complete`.
- [ ] **Step 6: Commit.** `git add firmware tools && git commit -m "feat: serial ls/dump/rm on device and PC"`

---

### Task 10: CI and the M1 bring-up checklist

**Files:**
- Create: `.github/workflows/ci.yml`, `docs/bringup-m1.md`, `docs/measurements.md`
- Modify: `README.md` (quick start for the tools and firmware)

**Interfaces:**
- CI jobs on push and pull request:
  - `python`: setup-python 3.13, `sudo apt-get install -y ffmpeg`, `pip install -e 'tools[dev]'`, `pytest tools/tests -q`.
  - `core`: `cmake -S firmware/core -B build/core && cmake --build build/core && ctest --test-dir build/core --output-on-failure`.
  - `firmware-s3`: container `espressif/idf:<v5.4.x tag>`, `cd firmware && idf.py set-target esp32s3 && idf.py build`, then upload the `.bin` files as an artifact.

- [ ] **Step 1: Write `ci.yml`.** Pin the IDF container tag to the newest 5.4.x tag that exists on Docker Hub.
- [ ] **Step 2: Write `docs/bringup-m1.md`**, a checklist the user runs on real hardware:
  1. Wire per `hardware/wiring-v0-s3.md`; flash (`idf.py -p <port> flash monitor`).
  2. Confirm the boot log shows LittleFS mounted and a new `boot_id`.
  3. Press the button, speak for about 10 s at 20 cm, press again; the log shows `saved note id=1 ...`.
  4. `espeak32 ls --port <port>` lists id 1.
  5. `espeak32 dump --port <port> --id 1 -o note.e32 --decode note.wav`; listen to `note.wav`.
  6. Fill `docs/measurements.md`: silence RMS, speech peak, and whether the level looks right (adjust `MIC_GAIN_SHIFT`); dump time for the note.
  7. Troubleshooting table: silent-mic warning -> check SD/WS/BCLK and L/R->GND; clipped audio -> lower gain shift; garbled audio -> check codec option and re-dump; dump too slow on a UART bridge -> raise the baud to 921600.
  Acceptance for M1: an intelligible voice note on the PC, produced end to end.
- [ ] **Step 3: Write the `docs/measurements.md` template** (table with date, board, codec, gain shift, silence RMS, speech peak, note length, dump seconds, notes) and update the README quick start.
- [ ] **Step 4: Commit and push.** `git add .github docs README.md && git commit -m "ci: test tools and core, build S3 firmware; add M1 bring-up checklist" && git push -u origin claude/diy-plaid-esp32-device-kb1755`
- [ ] **Step 5: Verify CI.** Using the GitHub tools (`actions_list`, `get_job_logs`), confirm the three jobs pass for the pushed commit. If `firmware-s3` fails, fix forward in a new commit; do not skip or disable it.

---

## Not in this plan

BLE GATT implementation, advertising windows, pairing and the button state machine with deep sleep (M2/M4); the C3 target and power work (M4); Opus, SD and the Wi-Fi channel (M5); the PWA and its TypeScript consumption of `protocol/vectors` (M2/M3). The Python `ble.py` codec exists now so those milestones build against a fixed, tested contract.
