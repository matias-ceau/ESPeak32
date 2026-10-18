# Measurements

| Date | Board | Codec | Gain shift | Silence RMS | Speech peak | Note length (s) | Dump time (s) | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-10-18 | ESP32-S3 DevKitC clone + INMP441 | ADPCM | 2 | ambient only (notes 1-3): RMS 208-391 | 26002 (-2 dBFS), RMS 1301 (-28 dBFS), voice close | 5.6 | 1.0 (47 KiB/s over USB-Serial-JTAG; 765 KB in 16 s) | Gain 2 is right: voice peaks near full scale. Fetched via a libusb bridge (no cdc_acm), CRC ok on all 4 notes. |

## BLE sync (M2)

| Date | Phone / PC | MTU | Window | Note bytes | Sync time (s) | KB/s | Resume after drop OK | Notes |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
