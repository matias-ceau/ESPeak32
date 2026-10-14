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
