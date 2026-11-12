# Bill of materials

## v0 breadboard build (M1, M2)

| Part | Qty | Notes |
|---|---|---|
| ESP32-S3 dev board (8 MB flash) | 1 | Programming and serial over USB; on-board WS2812 RGB LED used for status |
| INMP441 I2S MEMS microphone module | 1 | 3.3 V, omnidirectional |
| Latching toggle switch (or a tact switch) | 1 | Record control; see `wiring-v0-s3.md` |
| Breadboard + jumper wires, USB cable | | |

Wiring: `wiring-v0-s3.md`.

## Cassette build (C3)

| Part | Qty | Notes |
|---|---|---|
| ESP32-C3 Super Mini (4 MB flash) | 1 | USB-C is the chip's own USB-Serial-JTAG; blue LED on GPIO8 used for status |
| INMP441 I2S MEMS microphone module | 1 | |
| Momentary push button (tact switch) | 1 | Record control; on GPIO3 so it can wake the chip from deep sleep (M4) |
| Empty compact-cassette shell | 1 | Enclosure (M4) |

Wiring: `wiring-c3-supermini.md`. Power parts for M4 (LiPo, TP4056-type charger, 3.3 V buck, slide switch,
battery-sense divider on GPIO4) are not wired yet; the 5 V boost converter is not needed at all.
