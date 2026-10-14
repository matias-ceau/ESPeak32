# ESPeak32 — Design Spec

**Date:** 2026-10-14
**Status:** Draft for user review
**Scope:** System-level design. Each sub-project (M0–M5 below) gets its own implementation plan.

## 1. Purpose and intent

Build a credit-card-sized voice-note recorder in the spirit of the Plaud Note,
using only parts the author already owns. The user presses a button, speaks,
and the device records and goes back to sleep. Later, an Android companion app
pulls the recordings over Bluetooth Low Energy (BLE), transcribes them, and
produces a summary using cloud inference through OpenRouter.

The repository contains everything required to reproduce the device: hardware
build data, ESP32 firmware, and, as its main part, the companion phone app.

**Success criteria**

1. A card-sized prototype records a voice note, and the note survives power-off
   and deep sleep.
2. The phone app syncs the note over BLE without data loss, even if the link
   drops mid-transfer.
3. The app produces a transcript and a summary of the note through OpenRouter.
4. The finished device fits roughly within a metal card holder footprint
   (target in section 6.4).
5. Everything needed to rebuild it (BOM, wiring, firmware, app) is in the repo.

## 2. Decisions

| Topic | Decision |
|---|---|
| Use case | Personal voice notes, near-field (device held or clipped close to the speaker). Not meetings, not clinical encounters, not phone calls. |
| Phone | Android only. |
| Architecture | Store-and-sync over BLE: record to local storage, deep sleep, sync on demand. The transfer protocol is transport-agnostic so a Wi-Fi bulk channel can be added later. |
| App stack | Progressive web app (PWA) in TypeScript using Web Bluetooth, served over HTTPS (GitHub Pages) and run in Chrome on Android. Foreground sync only in v1. A Capacitor wrapper is the upgrade path for background sync. |
| Microphone | INMP441 (I2S MEMS) is primary. MAX9814 (analog, auto gain) is the fallback. KY-037/038 and LM393 sound sensors are not audio-grade and are not used. |
| Boards | Develop on ESP32-S3. The card build uses an ESP32-C3 SuperMini or an S3 mini. Firmware targets both chips. The classic ESP32 DevKit is a spare (too large). The S3 camera/SD board is an optional long-recording variant; the camera is unused. |
| Languages | Firmware in C (ESP-IDF). App in TypeScript. Python for host tooling: protocol reference implementation, `bleak` CLI, test vectors, converters. |
| Cloud | OpenRouter. Transcription uses an audio-capable chat model via a base64 `input_audio` part (OpenRouter has no Whisper-style endpoint). Summaries use a text chat model. Model IDs are user-configurable. |

**Out of scope for v1:** phone-call capture, text-to-speech, iOS, live
transcription, Wi-Fi sync, camera use, speaker diarisation, background sync.

## 3. System overview

```
 [button] -> ESP32 (INMP441 -> I2S -> ADPCM/Opus -> flash or SD)
                                   |
                                   +-- BLE GATT --> PWA (Chrome, Android)
                                                      |-> IndexedDB (audio, text, settings)
                                                      |-> OpenRouter (transcribe, summarise)
```

Three independently testable units share one contract: the device firmware, the
phone app, and the protocol and file format between them. The contract lives in
`protocol/` and is verified by shared test vectors (section 9).

## 4. Device behaviour

### 4.1 States and button

States: `DEEP_SLEEP -> RECORDING -> SAVING -> ADVERTISING -> SYNCING -> DEEP_SLEEP`.

- **Idle, short press (under 1.5 s):** start recording.
- **Recording, any press:** stop and save.
- **Idle, long press (1.5 s up to 10 s):** advertise for 120 s without recording, so the phone can sync on demand.
- **Idle, hold 10 s or more:** clear all BLE bonds (LED confirms).
- After a recording is saved, the device advertises for 60 s, then returns to deep sleep. If the phone connects, it stays awake until the transfer ends or the link drops.
- There are no periodic radio wake-ups. The radio is on only after a recording or on demand. This is the main battery-life measure.
- The first spoken word must not be clipped: capture starts at wake, before the press is classified. If the press turns out to be a long press, the buffered audio is discarded.

### 4.2 Capture

INMP441, 16 kHz mono, I2S standard-mode RX with DMA. The 32-bit slot is reduced
to its top 16 bits, followed by a DC-blocking filter and a fixed gain. The L/R
pin is tied to ground (left channel). Maximum note length is capped by free
storage.

### 4.3 Codec (pluggable; the codec id is stored in each file)

| Id | Codec | Bit rate | Notes |
|---|---|---|---|
| 0 | PCM16 | 256 kbps | Debug only. |
| 1 | IMA-ADPCM | 64 kbps (8 KB/s) | Baseline. Runs on every target. |
| 2 | Opus (SILK, fixed-point) | 16 kbps (2 KB/s) | Real-time on the S3 per published benchmarks. Must be benchmarked on the C3 before it becomes that target's default. |

### 4.4 Storage and file format

Flash uses a LittleFS partition. The S3 camera/SD variant uses an SD card with
FATFS. Each note is one file with a header (magic, format version, codec id,
sample rate, `boot_id`, start ticks, CRC) followed by a frame stream. File ids
are a monotonically increasing `u32` kept in NVS. Exact byte layouts are fixed in
`protocol/PROTOCOL.md` during M0.

Approximate capacity of the audio partition:

| Target | Storage | ADPCM | Opus |
|---|---|---|---|
| C3 SuperMini | 4 MB flash (about 2.5 MB audio) | about 5 min | about 20 min |
| S3 | 8 MB flash (about 6 MB audio) | about 12 min | about 50 min |
| S3 + SD | SD card | hours | hours |

### 4.5 Time

The device has no wall clock. The phone sends `SET_TIME` on connect. Each file
carries `(boot_id, ticks)`; the app converts to wall time with the latest
`(phone_time, ticks)` pair for the same `boot_id`. Files from a boot the app
never synchronised are shown as "unknown time" and ordered by file id.

### 4.6 Security

All characteristics require an encrypted link (LE Secure Connections, Just Works
bonding, bonds stored in NVS). The device is connectable only during the short
advertising windows in 4.1, so someone nearby cannot pull recordings. Just Works
does not defend against an active man-in-the-middle during pairing; this is
accepted for v1 and documented.

### 4.7 User interface

One tact button and one LED. The LED is lit only while recording or advertising,
with distinct blink patterns for low battery and storage full.

## 5. BLE protocol

A custom 128-bit service. The normative spec is `protocol/PROTOCOL.md`.

- **INFO (read):** protocol version, firmware version, battery percentage, free space, supported codecs, `boot_id`, current ticks.
- **CTRL (write + notify):** `LIST`, `GET(file_id, offset)`, `DELETE(file_id)`, `SET_TIME`, `ABORT`.
- **DATA (notify):** `[seq][payload]` chunks. Transfer is credit-windowed: the app grants N chunks at a time, because Web Bluetooth gives no notification back-pressure. Each file carries a CRC32. Transfers are resumable by offset.
- **Two-phase delete:** the app stores the file in IndexedDB and verifies the CRC before sending `DELETE`. An interrupted sync loses nothing.
- **Throughput budget:** 20–60 KB/s, to be measured on the target phone. A 5-minute Opus note is about 0.6 MB (10–30 s). A 5-minute ADPCM note is about 2.4 MB (about 1 min).

## 6. Components

### 6.1 Firmware (`firmware/`)

ESP-IDF, NimBLE. Pure logic lives in a portable `core/` library with no ESP
dependencies (ADPCM, file container, protocol framing, state machine) so it can
be built and tested on a host machine. Modules: `audio_capture`, `codec`,
`store`, `ble_gatt` (service and transfer engine), `ui` (button and LED),
`power` (deep sleep, battery sense, wake handling), `timebase`. Board
differences (pins, flash layout) live in `boards/s3` and `boards/c3`.

### 6.2 Phone app (`app/`)

Vite, TypeScript, vitest, Playwright. Modules with hard boundaries:

- `ble/` — a `Transport` interface, a Web Bluetooth implementation, and the protocol client. Reconnect tries `getDevices()` (experimental in Chrome) and falls back to the `requestDevice()` chooser on a user gesture.
- `audio/` — ADPCM decoder, Opus decode via WebCodecs `AudioDecoder`, PCM to WAV, and chunking of long notes before upload.
- `store/` — IndexedDB: recordings, transcripts, summaries, settings, job queue.
- `ai/` — OpenRouter client. `transcribe(audio)` sends chunked `input_audio`; `summarise(text)` sends a text prompt. Model IDs and prompt templates come from settings. Retry with backoff; offline queue.
- `ui/` — Sync, recordings list, detail view (playback, transcript, summary, copy and share), settings (API key, models, language, prompts).

A service worker caches the app shell. The API key is stored only on the device,
never in the repository. The README states that audio and text are sent to
third-party model providers through OpenRouter and warns against dictating
identifiable patient information.

### 6.3 Python tools (`tools/`)

`pyproject.toml` with pytest. Contents: reference implementation of the file
format and ADPCM, a `bleak` CLI (list, get, delete, decode to WAV), and an
OpenRouter audio smoke test.

### 6.4 Hardware (`hardware/`)

- **Power:** LiPo -> TP4056-type charger module -> 3.3 V buck -> module 3V3 pin, bypassing the dev-board LDO (and removing power LEDs). The 5 V boost converter is not needed. USB programming is done with the battery disconnected by a slide switch. The battery-sense divider must not consume the deep-sleep budget (high-value divider with a capacitor, or MOSFET-gated).
- **Wiring:** INMP441 on I2S (BCLK, WS, SD); button on an RTC-capable GPIO for deep-sleep wake; LED through a resistor. Separate pin tables for S3 and C3.
- **Form-factor budget:** footprint no larger than 86 x 54 mm and thickness 10 mm or less (stretch goal 8 mm). The battery sits beside the board rather than on top, pin headers are removed, and parts are soldered directly to the protoboard. The final numbers come from measuring the user's parts and card holder. A 3 mm Plaud-thin build is not achievable with these parts.
- **Enclosure:** parametric OpenSCAD for 3D printing, plus a no-printer variant.
- **Power figures are measured, not assumed.** Targets: deep sleep in the tens of microamps; recording around 25–40 mA on the C3.

## 7. Repository layout

```
README.md      what and why, quick start, privacy note
docs/          specs, build guides, measurements
hardware/      bom.md, wiring/, power.md, enclosure/
protocol/      PROTOCOL.md, file-format spec, shared test vectors (JSON)
firmware/      ESP-IDF project; core/ (portable C); boards/{s3,c3}
tools/         Python tooling (pyproject, pytest)
app/           PWA
```

## 8. Milestones

Each milestone gets its own spec, plan and implementation cycle.

1. **M0 — Contract:** repo scaffold, `PROTOCOL.md`, file format, test vectors, Python reference implementation.
2. **M1 — Mic works:** firmware records to flash on the S3; the recording is dumped to a PC and decoded to WAV with Python. Breadboard hardware v0. If the S3 camera board has an onboard PDM mic (as on XIAO ESP32S3 Sense), it offers a zero-wiring bring-up path.
3. **M2 — BLE sync:** GATT service and transfer engine; Python `bleak` CLI; PWA sync screen, first against a mock transport and then the real device.
4. **M3 — Cloud:** transcription and summary pipeline, recordings UI, settings, offline queue.
5. **M4 — Card build:** C3 port, deep sleep and power measurement, protoboard layout, enclosure, runtime test.
6. **M5 — Optional:** Opus as default, SD variant, Wi-Fi bulk channel, Capacitor wrapper.

M0 -> M1 -> M2 is the critical path. M3 can start against recorded test vectors once M0 lands.

## 9. Verification strategy

- **Shared test vectors** in `protocol/vectors/*.json` are consumed by C (host-built `firmware/core` tests), Python (pytest) and TypeScript (vitest), so all three implementations of ADPCM, the container and the framing are cross-checked.
- **App:** vitest unit tests. Playwright in headless Chromium with a mocked `navigator.bluetooth` and a mocked OpenRouter runs an end-to-end test of sync, decode, transcribe, and summary display.
- **Firmware:** host unit tests for `core/`. ESP-IDF builds for `esp32s3` and `esp32c3`, run locally if the toolchain can be installed in the development environment and otherwise in GitHub Actions. An on-device bring-up checklist lives in `docs/`.
- **Real-world acceptance (run by the user):** record a 60-second note, sync it, and see the transcript and summary. Measure idle and recording current and record it in `docs/measurements.md`.

## 10. Risks and early spikes

These are cheap experiments to run on real hardware before committing further.

1. INMP441 capture quality, checked with a serial WAV dump (M1).
2. BLE throughput and MTU from Chrome on the user's actual phone (M2).
3. `getDevices()` reconnect behaviour on that phone. The chooser fallback is designed in either way.
4. Opus encoding speed on the C3. ADPCM stays the default until it is measured.
5. Which OpenRouter models accept which audio formats (WAV versus Ogg/Opus) and their size limits. This drives chunking in `audio/` and needs a live API key to verify.
6. Real deep-sleep current with the user's exact charger and buck modules.

## 11. Inputs needed from the user (not blocking the design)

- Internal dimensions of the metal card holder (before M4).
- Exact model or photo of the charger and 3.3 V buck modules (before M4).
- Exact model of the S3 camera/SD board and whether it has an onboard microphone (before M1, optional).
- Which of the owned microphones is the "small round thin directional" one, if it is not the INMP441 (optional).
