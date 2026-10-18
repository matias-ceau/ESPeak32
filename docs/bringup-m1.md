# M1 bring-up checklist (run on real hardware)

Goal: an intelligible voice note on your PC, produced end to end.

1. **Wire** the board per `hardware/wiring-v0-s3.md` (INMP441 L/R must go to GND).
2. **Flash**: `cd firmware && idf.py set-target esp32s3 && idf.py -p <port> flash monitor`.
   The console is on the S3's native USB port (USB-Serial-JTAG). If your board only exposes a USB-UART bridge, switch
   the console channel in `idf.py menuconfig` and raise the baud to 921600.
3. **Boot log** should show `mounted /audio, boot_id=N` (N increments on every boot).
4. **Record**: switch on (LED red), speak for about 10 s at 20 cm, switch off. The log shows `saved note id=1 ...`.
5. **List**: `espeak32 ls --port <port>` shows id 1 and its size.
6. **Dump + decode**: `espeak32 dump --port <port> --id 1 -o note.e32 --decode note.wav`, then listen to `note.wav`.
7. **Measure** and fill in `docs/measurements.md`: RMS in silence, peak while speaking, and whether the level is right
   (adjust `ESPEAK32_MIC_GAIN_SHIFT` in menuconfig); time the dump.

## Troubleshooting

| Symptom | Check |
|---|---|
| Log warns "mic appears silent" | SD/WS/BCLK wiring and pins in menuconfig; L/R tied to GND; 3V3 present |
| Clipped / harsh audio | Lower `ESPEAK32_MIC_GAIN_SHIFT` |
| Very quiet audio | Raise `ESPEAK32_MIC_GAIN_SHIFT` (max 6) |
| Garbled audio | Rebuild with the PCM16 codec option, dump again; if PCM16 is clean, report the ADPCM issue |
| `espeak32 dump` exits 3 | Dump was corrupted or interrupted; run it again (nothing is written on failure) |
| Dump very slow | UART bridge at 115200 baud; use 921600 or the native USB port |
| Note not listed after a long recording | Storage nearly full stops a note at 64 KiB free; delete with `espeak32 rm` |

## Extra checks for the storage layer (not covered by host tests)

- **Power cut:** start a note, speak for ~20 s, pull the USB cable mid-note, reconnect. `espeak32 ls` should list the
  note; `espeak32 dump ... --decode` should decode most of it with the warning "file not finalized".
- **Long notes:** LittleFS finalizes by copying the file, so a note can only be finalized while free space is at least
  its own size plus 64 KiB. Otherwise the log says "note left unfinalized"; the audio is still decodable.
