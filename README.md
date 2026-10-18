# ESPeak32

A DIY, cassette-shell-sized AI voice-note recorder built from cheap parts (ESP32 + INMP441 mic), with an
Android companion app that syncs recordings over BLE and transcribes/summarises them through OpenRouter.

Status: M0 (contract) and M1 (mic works) implemented; M2 (BLE sync: firmware, PC CLI, phone app) implemented and
tested without hardware. Nothing has run on the board yet. See `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Layout

```
docs/       specs, plans, build guides, measurements
hardware/   BOM and wiring
protocol/   file format, BLE protocol, shared test vectors
firmware/   ESP-IDF project and portable C core
tools/      Python reference implementation and PC tools
app/        companion PWA (Vite + TypeScript, Web Bluetooth)
```

## Privacy

Audio and text are sent to third-party model providers through OpenRouter for transcription and summarisation.
Do not dictate identifiable patient information.

## Quick start (M1)

```bash
python3 -m venv .venv && .venv/bin/pip install -e 'tools[dev]'
.venv/bin/pytest tools/tests -q                        # Python reference + vectors
cmake -S firmware/core -B build/core && cmake --build build/core && ctest --test-dir build/core
cd firmware && idf.py set-target esp32s3 && idf.py build    # needs ESP-IDF 5.4
```

Record, dump and decode a note: see `docs/bringup-m1.md`.

## Sync over Bluetooth LE from a PC (M2)

```sh
.venv/bin/pip install -e 'tools[ble]'           # adds bleak
espeak32 ble scan                                # devices currently advertising
espeak32 ble info                                # pairs (Just Works) on first use
espeak32 ble sync --out notes/ --wav             # resumable; keeps the notes on the device
espeak32 ble sync --out notes/ --delete          # deletes each note only after it is stored and verified
```

The device is connectable for 60 s after a note is saved, or for 120 s after a quick on-off flick of the switch (1.5 s hold with a push button). Exit codes: 0 ok,
3 protocol or transfer error, 4 no device found.

## Phone app (M2)

```sh
cd app && npm ci
npm test                   # unit tests (format, protocol, mock device, sync client, storage)
npx playwright test        # end-to-end with a fake Bluetooth device (PW_CHROMIUM=/usr/bin/chromium to use a system Chromium)
npm run dev -- --host      # development server
```

Web Bluetooth needs Chrome on Android and a secure origin. Two ways to open the app on the phone:

- **USB, no hosting:** connect the phone with USB debugging on, run `adb reverse tcp:5173 tcp:5173` and open
  `http://localhost:5173/` in Chrome on the phone (localhost counts as secure).
- **GitHub Pages:** enable Pages (Settings -> Pages -> Source: GitHub Actions), then run the "pages" workflow by hand.
  Nothing is published until you do.
