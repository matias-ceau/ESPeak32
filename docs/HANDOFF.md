# Handoff: continue ESPeak32 from a session on the machine with the board

Read this first, then `docs/superpowers/specs/2026-10-14-espeak32-voice-recorder-design.md` and
`docs/superpowers/plans/2026-10-14-m0-m1-contract-and-mic.md`. Branch: `claude/diy-plaid-esp32-device-kb1755`
(develop and push there; do not open a PR unless asked).

## Who and how
The user is a psychiatry resident (addiction medicine), prefers Python, and trusts the assistant to drive. They do not
want to be asked routine questions: decide, ledger the decision, keep going. **Tell them exactly when a physical action
is needed** (wiring, flashing, pressing the button, soldering). Android phone only. Enclosure: empty compact-cassette shell.
Audio/text go to third-party models via OpenRouter; never put API keys in the repo.

## State (2026-10-18)
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
- **2026-10-18, validated on hardware (ESP32-S3 DevKit + INMP441, toggle switch, on-board WS2812 LED):** recording,
  LittleFS storage, USB `dump` (47 KiB/s), playback; BLE pairing (Just Works, bonded with the PC), PC sync of 4 notes
  at 35.5 KiB/s byte-identical to the USB dumps, and resume after a link cut mid-transfer. Numbers in
  `docs/measurements.md`. The PC side needed BlueZ 5.87 workarounds (no UUID discovery filter, a pairing agent in
  `tools/espeak32/bluez_agent.py`, duplicate-notification filter); see `docs/DECISIONS.md`. The `adv [s]` console
  command opens an advertising window over USB, so tests need no physical action.
- The user does not want to flash or touch the board once it is wired: flash and test remotely (`idf.py -p
  /dev/ttyACM0 flash`), ask only for unavoidable physical actions. Play audio through the Behringer UMC202HD.

## Next, in order
1. **Port to the ESP32-C3 Super Mini** (the actual build). The user will wire it. This time with a **momentary push
   button** (the `e32_button` push mode, `ESPEAK32_BUTTON_PUSH`), not the toggle switch. Check the C3 pins (I2S,
   button, LED: the Super Mini has a plain blue LED on GPIO8, not an RGB one), add a C3 target/sdkconfig and a CI
   build, then redo the M1/M2 bring-up on it.
2. **App local to the phone**, not served from the PC: the PWA was tested at `https://kirves.tail4ddf7b.ts.net:8443/`
   (tailscale serve, temporary). Make it installable and fully offline on Android (service worker, manifest), hosted
   once (GitHub Pages: `pages.yml`, needs Pages enabled) and then run from the home screen; or package it. Still to
   test: the phone sync itself.
3. Remaining M2 checks: two-phase delete (`espeak32 ble sync --delete`), bond reset (`unpair`).
4. M3: transcription and summary through OpenRouter (`input_audio`), recordings UI, settings, offline queue. Spec
   section 8; needs a live API key from the user for the format/size-limit spike (spec risk 5).
5. M4 cassette build: ask the user for the shell's internal dimensions and photos of their charger/buck modules first.

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
