# Handoff: continue ESPeak32 from a session on the machine with the board

Read this first, then `docs/superpowers/specs/2026-10-14-espeak32-voice-recorder-design.md` and
`docs/superpowers/plans/2026-10-14-m0-m1-contract-and-mic.md`. Work lands on `main`; the 2026-11-12 work is on branch
`ccr-6a4b7b57-w4vr2t` (draft PR) until merged.

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
  - App: `cd app && npm ci && npm test && npm run build && PW_CHROMIUM=/usr/bin/chromium npx playwright test`
    (the e2e run also builds and serves the production bundle for the offline test).
- **2026-10-18, validated on hardware (ESP32-S3 DevKit + INMP441, toggle switch, on-board WS2812 LED):** recording,
  LittleFS storage, USB `dump` (47 KiB/s), playback; BLE pairing (Just Works, bonded with the PC), PC sync of 4 notes
  at 35.5 KiB/s byte-identical to the USB dumps, and resume after a link cut mid-transfer. Numbers in
  `docs/measurements.md`. The PC side needed BlueZ 5.87 workarounds (no UUID discovery filter, a pairing agent in
  `tools/espeak32/bluez_agent.py`, duplicate-notification filter); see `docs/DECISIONS.md`. The `adv [s]` console
  command opens an advertising window over USB, so tests need no physical action.
- The user does not want to flash or touch the board once it is wired: flash and test remotely (`idf.py -p
  /dev/ttyACM0 flash`), ask only for unavoidable physical actions. Play audio through the Behringer UMC202HD.
- **2026-11-12 (cloud session, no hardware; firmware 0.3.0, build-checked in CI only):**
  - File format v2: notes end with a 14-byte end record instead of a header rewrite (LittleFS copied the whole file to
    rewrite it). Python, C and the app read v1 and v2. `protocol/FILE_FORMAT.md`, `docs/DECISIONS.md`.
  - Recording: 320 ms I2S DMA ring, DMA overruns counted and logged at every save (`overruns=N`), no free-space walk
    inside the recording loop.
  - App: strict IndexedDB durability before a device delete; the service worker precaches the bundle, so the app opens
    offline after one visit (an e2e test covers it; it found and fixed a `Vary: Origin` cache miss).
  - ESP32-C3 Super Mini target: `sdkconfig.defaults.esp32c3`, `partitions_4mb.csv`, push button on GPIO3, I2S on
    GPIO5/6/7, blue LED on GPIO8 (active low), CI builds both targets. Wiring: `hardware/wiring-c3-supermini.md`.

## Next, in order
1. **Update the phone app before syncing firmware 0.3.0 notes.** An app older than file format v2 rejects v2 notes
   (it skips them and does not delete them from the device, so nothing is lost). Serve the new build where the phone
   installed it from and open the app online once.
2. **C3 Super Mini bring-up.** The user wires it per `hardware/wiring-c3-supermini.md` (momentary push button on
   GPIO3, INMP441 on GPIO5/6/7). Flash with `idf.py set-target esp32c3`, then run `docs/bringup-m1.md` and
   `docs/bringup-m2.md`. Check: the LED polarity (self-test blinks, dark while idle), `overruns=0` on every save,
   app size (`idf.py size`) and free heap with BLE up, phone sync.
3. **Firmware 0.3.0 on the S3 too:** a note recorded until the storage is full must decode without the "not
   finalized" warning, with `overruns=0`.
4. Remaining M2 checks: two-phase delete (`espeak32 ble sync --delete`), bond reset (`unpair`).
5. **Pairing only on demand** (decided 2026-11-12, see `docs/DECISIONS.md`): accept new bonds only in the 120 s
   long-press window, not in the 60 s after every note. Needs the board to test; do it during the C3 bring-up.
6. M3: transcription and summary through OpenRouter (`input_audio`), recordings UI, settings, offline queue. Spec
   section 8; needs a live API key from the user for the format/size-limit spike (spec risk 5). Phone sync works
   (user, before 2026-11-12); phone model, MTU and KB/s were not recorded.
7. **Before deep sleep (M4), a clock that survives it:** today `boot_id` increments on every start and `start_us`
   counts from boot, so once every wake is a boot, notes not synced in their own wake window show "unknown time".
   Keep `boot_id` across deep-sleep wakes (`esp_reset_reason() == ESP_RST_DEEPSLEEP`) and take `start_us` and the
   SET_TIME ticks from a clock that keeps running through deep sleep (the RTC-backed system time, `gettimeofday`).
8. M4 cassette build: ask the user for the shell's internal dimensions and photos of their charger/buck modules first.
   GitHub Pages hosting for the app (`pages.yml`, needs Pages enabled) remains the user's call.

## Rulings already made
Later decisions are in `docs/DECISIONS.md`.

- ESP-IDF's own console-channel choice is used (sdkconfig.defaults: USB-Serial-JTAG), not a duplicate Kconfig choice.
- ADPCM uses the reference IMA shift arithmetic (bit-exact with FFmpeg >= 9). It was FFmpeg 6.1's multiply form
  until 2026-10-15; see `docs/DECISIONS.md` for why it changed.
- Notes are append-only (file format v2, 2026-11-12): an end record replaces the header rewrite, which LittleFS
  implemented by copying the whole file. The sink syncs once a second, so a power cut keeps a decodable note.
- No host test of the real LittleFS sink (would need littlefs's RAM block device); it is only proven on hardware.

## Deferred minors (from the final review)
Stuck-high mic data line not flagged as silent; `ls`/`rmall` capped at 128 notes; failed mount silently formats the
partition; USB-CDC console falls into the UART branch in `console.c`.

## Not done on purpose (spec items for later)
Audio before the button press (first word), LED patterns for low battery/storage full, deep sleep and the long-press
state machine (M4), Opus, SD, Wi-Fi.
