# Handoff: continue ESPeak32 from a session on the machine with the board

Read this first, then `docs/superpowers/specs/2026-10-14-espeak32-voice-recorder-design.md` and
`docs/superpowers/plans/2026-10-14-m0-m1-contract-and-mic.md`. Branch: `claude/diy-plaid-esp32-device-kb1755`
(develop and push there; do not open a PR unless asked).

## Who and how
The user is a psychiatry resident (addiction medicine), prefers Python, and trusts the assistant to drive. They do not
want to be asked routine questions: decide, ledger the decision, keep going. **Tell them exactly when a physical action
is needed** (wiring, flashing, pressing the button, soldering). Android phone only. Enclosure: empty compact-cassette shell.
Audio/text go to third-party models via OpenRouter; never put API keys in the repo.

## State
- M0 (contract) and M1 (mic works) are implemented: `.e32` file format, ADPCM/PCM16 reference codecs, BLE message codec,
  golden vectors, portable C core (byte-exact against the vectors), ESP-IDF S3 recorder, serial `ls/dump/rm`, PC
  `espeak32 ls|dump|rm|decode`, CI, bring-up checklist.
- Local verification: `python3 -m venv .venv && .venv/bin/pip install -e 'tools[dev]' && .venv/bin/pytest tools/tests -q`
  (65 pass; the ffmpeg oracle test runs if ffmpeg is installed); `cmake -S firmware/core -B build/core && cmake --build
  build/core && ctest --test-dir build/core` (5 pass).
- CI (`.github/workflows/ci.yml`): the first run was green on all three jobs including the ESP-IDF 5.4.4 build. Check the
  run for the last fix commit and fix forward if red.
- The firmware has **never run on hardware**. Nothing about audio quality, gain, dump speed or power-cut behaviour is
  verified yet.

## Next, in order
1. Install ESP-IDF 5.4.x on this machine (or use the `espressif/idf:v5.4.4` container), then with the user follow
   `docs/bringup-m1.md`: wire per `hardware/wiring-v0-s3.md` (INMP441 L/R -> GND), flash, record, `espeak32 ls`, `dump
   --decode`, listen to the WAV, run the power-cut check. The console is on the native USB port (USB-Serial-JTAG);
   opening the port with pyserial may reset the chip (DTR/RTS) - check. Record numbers in `docs/measurements.md`.
2. Fix whatever the hardware shows (gain shift, silent-mic detection, dropouts, dump speed), test-first where possible.
3. M2: BLE sync. Brainstorm (superpowers:brainstorming) -> spec -> plan (superpowers:writing-plans) -> execute inline
   with TDD (superpowers:executing-plans) -> one fresh whole-branch review. Scope: NimBLE GATT service + transfer engine
   (credit-windowed GET, resume by offset, CRC, two-phase delete, SET_TIME, encrypted link, advertising windows), Python
   `bleak` CLI, then the TypeScript PWA (Web Bluetooth) tested against a mocked transport using `protocol/vectors/ble.json`.
   Contract: `protocol/PROTOCOL.md`, `protocol/FILE_FORMAT.md`, `tools/espeak32/ble.py`.
4. Later milestones are in the spec section 8 (M3 cloud transcription via OpenRouter `input_audio`, M4 cassette build -
   ask the user for the shell's internal dimensions and photos of their charger/buck modules before then).

## Rulings already made
- ESP-IDF's own console-channel choice is used (sdkconfig.defaults: USB-Serial-JTAG), not a duplicate Kconfig choice.
- ADPCM reconstruction uses FFmpeg's formula `((2*(code&7)+1)*step)>>3` (verified bit-exact with ffmpeg; the classic
  shift formula does not match).
- LittleFS cannot rewrite the header in place cheaply (it copies the file). The sink syncs once a second and only
  rewrites the header if free space >= file size + 64 KiB; otherwise the note stays unfinalized (still decodable, no
  CRC). A trailer-based finalization (contract change) was NOT done: revisit if long notes end up unfinalized.
- No host test of the real LittleFS sink (would need littlefs's RAM block device); those fixes are only proven on hardware.

## Deferred minors (from the final review)
Stuck-high mic data line not flagged as silent; `ls`/`rmall` capped at 128 notes; failed mount silently formats the
partition; `joltwallet/littlefs` version unpinned (CI resolved 1.22.3); a failed TRANSFER_DONE decodes ambiguously in
`ble.py`; `abs()` on int32 in the encoder; USB-CDC console falls into the UART branch in `console.c`.

## Not done on purpose (spec items for later)
Audio before the button press (first word), LED patterns for low battery/storage full, deep sleep and the long-press
state machine (M4), Opus, SD, Wi-Fi.
