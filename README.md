# ESPeak32

A DIY, cassette-shell-sized AI voice-note recorder built from cheap parts (ESP32 + INMP441 mic), with an
Android companion app that syncs recordings over BLE and transcribes/summarises them through OpenRouter.

Status: M0 (contract) and M1 (mic works) in progress. See `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## Layout

```
docs/       specs, plans, build guides, measurements
hardware/   BOM and wiring
protocol/   file format, BLE protocol, shared test vectors
firmware/   ESP-IDF project and portable C core
tools/      Python reference implementation and PC tools
app/        companion PWA (later milestone)
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

The device is connectable for 60 s after a note is saved, or for 120 s after a 1.5 s press. Exit codes: 0 ok,
3 protocol or transfer error, 4 no device found.
