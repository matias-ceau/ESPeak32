# Wiring: ESP32-C3 Super Mini (cassette build)

Pins are the C3 defaults in `firmware/sdkconfig.defaults.esp32c3` (change them with `idf.py menuconfig` ->
ESPeak32). Build and flash: `cd firmware && idf.py set-target esp32c3 && idf.py -p /dev/ttyACM0 flash monitor`.
The Super Mini has no USB-UART chip: its USB-C port is the C3's own USB-Serial-JTAG, used for flashing and the console.

## Super Mini header

The two rows of pins, each listed from the USB-C end:

| Row A | Row B |
|---|---|
| 5V | GPIO5 |
| GND | GPIO6 |
| 3V3 | GPIO7 |
| GPIO4 | GPIO8 (blue LED) |
| GPIO3 | GPIO9 (BOOT button) |
| GPIO2 | GPIO10 |
| GPIO1 | GPIO20 |
| GPIO0 | GPIO21 |

Which row is on the left depends on which face you look at: go by the silkscreen labels, and check them before
soldering because clones differ.

## INMP441 microphone

| INMP441 pin | Super Mini | Why this pin |
|---|---|---|
| VDD | 3V3 | |
| GND | GND | |
| SCK | GPIO5 (I2S BCLK) | GPIO5, 6 and 7 are adjacent: one short three-wire run |
| WS | GPIO6 (I2S WS) | |
| SD | GPIO7 (I2S data in) | |
| **L/R** | **GND** | left channel; the firmware reads the left slot |

## Button and LED

| Part | Connect to | Why this pin |
|---|---|---|
| Momentary push button | GPIO3 to GND (internal pull-up) | only GPIO0-5 can wake the C3 from deep sleep (M4) |
| Status LED | nothing: the board's blue LED on GPIO8 is used | lit when GPIO8 is low |

Kept free on purpose: GPIO4 (ADC1, battery-voltage divider in M4), GPIO0 and GPIO1 (spare, deep-sleep capable).
Avoid GPIO2, GPIO8 and GPIO9 for anything else: they are strapping pins (GPIO9 is the BOOT button). GPIO20/21 are
the C3's UART0, unused.

## Button and LED behaviour (push-button mode, firmware 0.3.0)

| Action | Effect |
|---|---|
| Press while idle | Start recording (LED on). |
| Press while recording | Stop and save; the device then advertises for 60 s so the phone can sync (LED slow blink). |
| Hold 1.5 s while idle | The note just started is discarded; on release the device advertises for 120 s. |
| Hold 10 s | Clears all BLE bonds (three flashes). `unpair` on the serial console does the same. |

At power-up the LED blinks three times (self-test). If instead it stays lit while idle and goes dark while recording,
the LED polarity is inverted on your board: menuconfig -> ESPeak32 -> "Plain LED lights when the pin is low".

## Storage

4 MB flash: 1 MB app, 2.9 MB of notes (`firmware/partitions_4mb.csv`), about 6 minutes of IMA-ADPCM. A note is
finalized by appending a few bytes (file format v2), so even a note that fills the storage is finalized.

## Bring-up on the C3

Do `docs/bringup-m1.md` and `docs/bringup-m2.md` with these differences: the target is `esp32c3`; the record control
is the push button; the LED is the blue one (no colours: on = recording, slow blink = advertising, fast blink = error).
Also note the app size printed by `idf.py size` and the free heap after BLE starts.
