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
