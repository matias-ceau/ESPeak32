# v0 wiring: ESP32-S3 dev board

Pins below are the Kconfig defaults (`idf.py menuconfig` -> ESPeak32); change them there for other boards.

| INMP441 pin | Connect to |
|---|---|
| VDD | 3V3 |
| GND | GND |
| SCK | GPIO4 (I2S BCLK) |
| WS | GPIO5 (I2S WS) |
| SD | GPIO6 (I2S data in) |
| **L/R** | **GND** (left channel; the firmware reads the left slot) |

| Part | Connect to |
|---|---|
| Record button | GPIO7 to GND (internal pull-up, active low) |
| LED | GPIO8 -> 330 ohm -> LED -> GND |

Avoid strapping pins (0, 3, 45, 46), USB pins (19, 20) and the flash/PSRAM pins. Boards such as the S3 camera board use
different free pins; set them through menuconfig. The firmware expects the partition table in `firmware/partitions.csv`
(8 MB flash).

## Button and LED behaviour (firmware 0.2.0)

| Action | Effect |
|---|---|
| Short press while idle | Start recording (LED on). Recording starts at the press, so the first word is kept. |
| Press while recording | Stop and save; the device then advertises for 60 s so the phone can sync. |
| Hold 1.5 s while idle | The note just started is discarded; on release the device advertises for 120 s. |
| Hold 10 s | Clears all BLE bonds (three quick LED flashes). Use it when the phone was "forgotten". |

LED: on = recording; slow blink (1 Hz) = advertising, connectable; fast blink for 3 s = error (storage full, write
failure). After a disconnect the device advertises for another 60 s so an interrupted sync can resume.
