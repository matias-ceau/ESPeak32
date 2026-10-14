#include "audio_capture.h"

#include "driver/i2s_std.h"
#include "sdkconfig.h"

static i2s_chan_handle_t s_rx;

esp_err_t audio_capture_start(void) {
  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
  cc.dma_desc_num = 6;
  cc.dma_frame_num = 320;
  esp_err_t err = i2s_new_channel(&cc, NULL, &s_rx);
  if (err != ESP_OK) return err;

  i2s_std_config_t sc = {
      .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),
      .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO),
      .gpio_cfg =
          {
              .mclk = I2S_GPIO_UNUSED,
              .bclk = CONFIG_ESPEAK32_PIN_I2S_BCLK,
              .ws = CONFIG_ESPEAK32_PIN_I2S_WS,
              .dout = I2S_GPIO_UNUSED,
              .din = CONFIG_ESPEAK32_PIN_I2S_SD,
          },
  };
  sc.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT; /* INMP441 L/R pin tied to GND */
  err = i2s_channel_init_std_mode(s_rx, &sc);
  if (err != ESP_OK) return err;
  return i2s_channel_enable(s_rx);
}

int audio_capture_read(int32_t *slots, size_t max_slots, uint32_t timeout_ms) {
  size_t got = 0;
  esp_err_t err = i2s_channel_read(s_rx, slots, max_slots * sizeof(int32_t), &got, timeout_ms);
  if (err != ESP_OK && err != ESP_ERR_TIMEOUT) return -1;
  return (int)(got / sizeof(int32_t));
}

void audio_capture_stop(void) {
  if (!s_rx) return;
  i2s_channel_disable(s_rx);
  i2s_del_channel(s_rx);
  s_rx = NULL;
}
