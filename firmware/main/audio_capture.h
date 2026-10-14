#pragma once
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

/* I2S standard-mode RX, 16 kHz, 32-bit slot, left channel, DMA. Pins from Kconfig. */
esp_err_t audio_capture_start(void);
/* Returns slots read (>= 0) or -1 on error. A timeout returns 0. */
int audio_capture_read(int32_t *slots, size_t max_slots, uint32_t timeout_ms);
void audio_capture_stop(void);
