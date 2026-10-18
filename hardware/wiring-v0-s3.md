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
| LED | None needed: the board's RGB LED (WS2812, GPIO48) is used. For a plain LED: menuconfig -> ESPeak32 -> Status LED -> GPIO, then GPIO8 -> 330 ohm -> LED -> GND. If the RGB LED stays dark, your board may be a DevKitC-1 v1.1: set the LED GPIO to 38. |

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

LED (RGB): red = recording; blue slow blink (1 Hz) = advertising, connectable; orange fast blink for 3 s = error
(storage full, write failure); three white flashes = bonds cleared. A plain LED shows the same patterns without colour. After a disconnect the device advertises for another 60 s so an interrupted sync can resume.
