# Handoff: continue ESPeak32 from a session on the machine with the board

Read this first, then `docs/superpowers/specs/2026-10-14-espeak32-voice-recorder-design.md` and
`docs/superpowers/plans/2026-10-14-m0-m1-contract-and-mic.md`. Branch: `claude/diy-plaid-esp32-device-kb1755`
(develop and push there; do not open a PR unless asked).

## Who and how
The user is a psychiatry resident (addiction medicine), prefers Python, and trusts the assistant to drive. They do not
want to be asked routine questions: decide, ledger the decision, keep going. **Tell them exactly when a physical action
is needed** (wiring, flashing, pressing the button, soldering). Android phone only. Enclosure: empty compact-cassette shell.
Audio/text go to third-party models via OpenRouter; never put API keys in the repo.

## State (2026-10-15)
- M0 (contract) and M1 (mic works) are implemented: `.e32` file format, ADPCM/PCM16 reference codecs, BLE message codec,
  golden vectors, portable C core, ESP-IDF S3 recorder, serial `ls/dump/rm`, PC `espeak32 ls|dump|rm|decode`, CI,
  bring-up checklist.
- M2 (BLE sync) is implemented and tested without hardware (spec `docs/superpowers/specs/2026-10-15-m2-ble-sync-design.md`,
  plan `docs/superpowers/plans/2026-10-15-m2-ble-sync.md`): protocol behaviour rules in `protocol/PROTOCOL.md`; Python
  reference device model generating `protocol/vectors/sync.txt`; C transfer engine `e32_xfer` and button classifier
  `e32_button` (host-tested; the engine replays sync.txt byte for byte); NimBLE GATT service with LE Secure
  Connections bonding and advertising windows (build-checked only); resumable sync client and `espeak32 ble …` CLI
  (bleak, optional extra); PWA in `app/` (Vite + TypeScript, IndexedDB, Web Bluetooth, play/save WAV) with unit tests
  and a Playwright e2e test against a fake `navigator.bluetooth`.
- Local verification:
  - Python: `uv venv .venv && uv pip install --python .venv -e 'tools[dev]' && .venv/bin/python -m pytest tools/tests -q`
    (the ffmpeg oracle test needs ffmpeg >= 9).
  - C: `cmake -S firmware/core -B build/core && cmake --build build/core && ctest --test-dir build/core` (7 tests).
  - Firmware: see `docs/DECISIONS.md` for the IDF 5.4.4 command on this machine (Python 3.12 shim).
  - App: `cd app && npm ci && npm test && npm run build && PW_CHROMIUM=/usr/bin/chromium npx playwright test`.
- The firmware has **never run on hardware**. Nothing about audio quality, gain, BLE pairing, throughput, dump speed or
  power-cut behaviour is verified yet.

## Next, in order
1. With the user: `docs/bringup-m1.md` (wire, flash, record, dump, listen, power-cut check), then `docs/bringup-m2.md`
   (pair, sync from PC and phone, resume after a drop, two-phase delete, long press, bond reset). Record numbers in
   `docs/measurements.md`. Console is on the native USB port; opening it with pyserial may reset the chip (DTR/RTS).
2. Fix whatever the hardware shows (gain, silent-mic detection, dropouts, MTU timing, mbuf pool, window size),
   test-first where possible.
3. M3: transcription and summary through OpenRouter (`input_audio`), recordings UI, settings, offline queue. Spec
   section 8; needs a live API key from the user for the format/size-limit spike (spec risk 5).
4. M4 cassette build: ask the user for the shell's internal dimensions and photos of their charger/buck modules first.

## Rulings already made
Later decisions are in `docs/DECISIONS.md`.

- ESP-IDF's own console-channel choice is used (sdkconfig.defaults: USB-Serial-JTAG), not a duplicate Kconfig choice.
- ADPCM uses the reference IMA shift arithmetic (bit-exact with FFmpeg >= 9). It was FFmpeg 6.1's multiply form
  until 2026-10-15; see `docs/DECISIONS.md` for why it changed.
- LittleFS cannot rewrite the header in place cheaply (it copies the file). The sink syncs once a second and only
  rewrites the header if free space >= file size + 64 KiB; otherwise the note stays unfinalized (still decodable, no
  CRC). A trailer-based finalization (contract change) was NOT done: revisit if long notes end up unfinalized.
- No host test of the real LittleFS sink (would need littlefs's RAM block device); those fixes are only proven on hardware.

## Deferred minors (from the final review)
Stuck-high mic data line not flagged as silent; `ls`/`rmall` capped at 128 notes; failed mount silently formats the
partition; USB-CDC console falls into the UART branch in `console.c`.

## Not done on purpose (spec items for later)
Audio before the button press (first word), LED patterns for low battery/storage full, deep sleep and the long-press
state machine (M4), Opus, SD, Wi-Fi.
