#pragma once
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

/* Frames (samples) per DMA buffer; one overrun drops one buffer. */
#define AUDIO_CAPTURE_BUFFER_FRAMES 320

/* I2S standard-mode RX, 16 kHz, 32-bit slot, left channel, DMA. Pins from Kconfig. */
esp_err_t audio_capture_start(void);
/* Returns slots read (>= 0) or -1 on error. A timeout returns 0. */
int audio_capture_read(int32_t *slots, size_t max_slots, uint32_t timeout_ms);
/* DMA buffers dropped since boot because the reader fell behind; each is 20 ms of audio missing from a note. */
uint32_t audio_capture_overruns(void);
void audio_capture_stop(void);
