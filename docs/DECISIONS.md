# Decision ledger

Routine decisions taken without asking, newest last. Each entry: date, decision, why, consequence.

## 2026-10-15 — ADPCM uses the reference IMA arithmetic, not FFmpeg 6.1's multiply form

- **Evidence:** on a machine with FFmpeg 9.0.2, `test_adpcm_matches_ffmpeg` failed (1920 of 2020 samples off by about 1 LSB).
  FFmpeg 6.1-8.0 decode 4-bit IMA WAV with `adpcm_ima_expand_nibble(.., 3)` (`((2*code+1)*step)>>3`); FFmpeg 9.0 switched
  to `ff_adpcm_ima_qt_expand_nibble`, the reference IMA shift arithmetic also used by Microsoft and Apple decoders.
- **Decision:** the contract follows the reference IMA arithmetic for reconstruction and the matching successive-
  approximation quantiser. Python, C and the committed vectors were changed together; FFmpeg >= 9 is the oracle, and the
  oracle test skips on older FFmpeg. CI installs a static FFmpeg 9 build (BtbN) so the oracle still runs there.
- **Why now:** no device has written a file yet, so the format change costs nothing today. Tying the contract to one
  FFmpeg version's rounding would have broken again on the next upgrade.
- **Side effect:** removes the `abs()` on int32 in the C encoder (a deferred minor).

## 2026-10-15 — ESP-IDF installed natively, not via Docker

The user's account is not in the `docker` group, and changing system groups is not routine. ESP-IDF v5.4.4 is installed
under `~/esp/esp-idf-v5.4.4` (`install.sh esp32s3`); CI keeps using the `espressif/idf:v5.4.4` container.

Local build on this machine (the shell's `python3` is a uv virtualenv, which `install.sh` refuses, and IDF 5.4 is not
validated on Python 3.14): IDF's Python env uses uv's CPython 3.12 through a shim directory:
`env -u VIRTUAL_ENV PATH=$HOME/esp/py312-shim:/usr/bin:/bin bash -c '. ~/esp/esp-idf-v5.4.4/export.sh && cd firmware && idf.py build'`.
First local build (2026-10-15): clean, 0 warnings, app 0x502c0 bytes (79 % of the 1.5 MB app partition free).

## 2026-10-15 — `joltwallet/littlefs` pinned to `~1.22.3`

The version CI and the local build both resolved. Closes a deferred minor; `~` allows patch releases only.

## 2026-10-15 — M2 design choices (spec `docs/superpowers/specs/2026-10-15-m2-ble-sync-design.md`)

The user asked for brainstorm → spec → plan → execution while away, deciding routine points alone. Self-approved:
- **Transfer logic in portable C** (`e32_xfer`) with a thin NimBLE layer, so it is host-tested; NimBLE code is only
  build-checked until the board is available.
- **Python device model is the reference**; it generates `protocol/vectors/sync.txt` session transcripts that the C
  engine and the TypeScript mock device replay byte for byte (same pattern as the M0 vectors). Line format, not JSON,
  so the C test needs no parser library.
- **Protocol clarifications** (spec section 2), notably `[0x83][status]` = transfer failed, decoded as
  `TransferFailed` (fixes the ambiguous decode deferred from M1), and `battery_pct = 255` = unknown.
- **Button:** recording starts on press; a press held 1.5 s cancels that note and, on release, opens a 120 s
  advertising window; 10 s clears bonds. Matches parent spec 4.1 without the pre-roll buffer.
- **Advertising:** 60 s after a save and after every disconnect (so a dropped link can resume), 120 s on long press.
- **Credit policy:** window 16, re-grant half the window each time half is consumed; configurable.
- **PWA M2 scope:** sync screen plus play/save WAV as the on-phone acceptance check; no UI framework; TypeScript 5.9
  (7.x is the new native compiler, too fresh).
- **GitHub Pages deploy only by manual dispatch**: publishing is the user's call.
- `bleak` is an optional extra (`tools[ble]`); tests never import it.

## 2026-10-15 — M2 final review fixes

A fresh whole-branch review found no critical issue and seven important ones, all fixed:
- A note that keeps losing chunks is skipped (`transfer keeps losing chunks`) instead of aborting the whole sync.
- A 200 ms grace after an incomplete TRANSFER_DONE is restored in both clients: under BlueZ, bleak's AcquireNotify
  uses one socket per characteristic, so CTRL can overtake DATA. bleak is also forced to StartNotify (`bleak>=2.1`).
- The PWA asks `navigator.storage.persist()` (with delete-after-sync the phone holds the only copy) and warns if refused.
- The service worker is network-first; the old cache-first one would have frozen the app at its first version.
- The device starts the MTU exchange itself (`ble_gattc_exchange_mtu`), which needs `CONFIG_BT_NIMBLE_ROLE_CENTRAL=y`
  because NimBLE ties the GATT client to the central role. The device never scans.
- Task stacks: id buffers moved off the stacks, host and transfer tasks at 6 KB; free stack is logged at each disconnect.
- A full event queue now fails the ATT write instead of dropping the request; the queue is reset on disconnect.
Open question for the user: Just Works pairing is accepted in every advertising window (parent spec 4.6). Limiting new
bonds to the 120 s long-press window would stop a nearby phone pairing during the 60 s after-note window.

## 2026-10-18 — Status LED is the board's RGB LED by default

The user wired no external LED. The DevKitC-style board has a WS2812 addressable LED (GPIO48; GPIO38 on DevKitC-1
v1.1), driven through `espressif/led_strip ~3.1.0` (RMT). Colours: red recording, blue blink advertising, orange
blink error, white flashes bonds cleared. A plain GPIO LED stays available in menuconfig.

## 2026-10-18 — Latching toggle switch support (user's choice)

The breadboard uses a latching toggle switch, which the push-button logic would misread (a press that never ends:
note cancelled at 1.5 s, bonds cleared at 10 s). The user chose a switch mode, now the default in
`sdkconfig.defaults`: on = record, off = save, on for under 1.5 s = discard and advertise 120 s. Forgetting bonds
moved to the `unpair` console command. Push-button mode stays in menuconfig. Host-tested in `test_button.c`.

## 2026-10-18 — First hardware run (M1) and the dump watchdog fix

- First power-up left the chip in download mode (`boot:0x0`) even across USB chip resets; a USB unplug/replug fixed
  it. Flashing over JTAG (OpenOCD) then booted normally.
- Recording works end to end. Voice at close range peaks at 26002 (-2 dBFS) with gain shift 2: keep the gain.
- Bug found on hardware: `dump` of a long note starved the idle task on CPU 1; task-watchdog logs landed inside
  base64 lines and the PC rejected the dump (correctly). Fix: the console mutes logs during `dump` and yields every
  16 lines. Verified on the board: four notes (up to 765 KB) dumped intact at 47 KiB/s, no watchdog message.
