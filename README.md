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
