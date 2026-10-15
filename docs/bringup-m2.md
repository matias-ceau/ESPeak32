# M2 bring-up checklist (BLE sync, run on real hardware)

Goal: a note recorded on the device reaches the phone app and the PC over BLE, survives a dropped link, and is deleted
from the device only after it is stored. Do M1 (`docs/bringup-m1.md`) first.

1. **Flash** firmware 0.2.0: `cd firmware && idf.py -p <port> flash monitor`. The boot log has no BLE errors.
2. **Record** a note of about 30 s (short press, speak, short press). The log shows `saved note id=N` then
   `advertising for 60 s`; the LED blinks slowly.
3. **PC first** (easier to debug): `espeak32 ble scan` lists the device. `espeak32 ble info` pairs (Just Works; accept
   any OS prompt) and prints `firmware: 0.2.0`. Then `espeak32 ble sync --out notes/ --wav` and listen to the WAV.
   Note the time it took and the size, and fill in `docs/measurements.md` (KB/s).
4. **Resume:** record a long note (2 min), start `espeak32 ble sync --out notes/`, and halfway through switch the PC's
   Bluetooth off for 5 s and on again (or walk away). The device advertises again for 60 s after the drop; rerun the
   same command if it gave up. The note must arrive complete (CRC verified), and the `.part` file must be gone.
5. **Phone:** open the app (README, "Phone app"), tap *Connect & sync*, pick ESPeak32, accept pairing. The notes appear;
   *Play* works; *Save WAV* gives a file. With *Delete from device after sync* on, `espeak32 ble list` afterwards
   shows the device empty.
6. **Resume on the phone:** as in 4, but toggle the phone's Bluetooth mid-transfer, then tap *Connect & sync* again.
7. **Two-phase delete:** with a note on the device, start a phone sync and force-close Chrome mid-transfer. Reopen and
   sync again: the note must still be on the device until the app shows it.
8. **Long press:** hold the button 1.5 s while idle: no note is created, and the device advertises for 120 s.
9. **Bond reset:** forget the device on the phone, hold the button 10 s (three quick flashes), pair again.

Write down the phone model, the MTU (`I (…) ble: mtu N` in the monitor log) and the window you used.

## Troubleshooting

| Symptom | Check |
|---|---|
| No pairing prompt, reads fail | Remove the old bond on the phone/PC, hold the device button 10 s, pair again. |
| Status "MTU below 64 bytes" | Note the phone model; the device needs MTU >= 64. Report it with the monitor log. |
| Transfer stalls, many resumes | Lower the window (`espeak32 ble sync --window 8`); report the KB/s at each window. |
| `no ESPeak32 advertising nearby` | The window is 60 s after a save; hold the button 1.5 s to open a 120 s window. |
| Phone app says Web Bluetooth unavailable | Use Chrome (not Firefox/Samsung Internet) over HTTPS or `adb reverse` localhost. |
