#include "status_led.h"

#include "esp_log.h"
#include "sdkconfig.h"

static const char *TAG = "led";
static led_state_t s_state = -1;

#ifdef CONFIG_ESPEAK32_LED_WS2812
#include "led_strip.h"

static led_strip_handle_t s_strip;
/* r, g, b kept dim: the board LED is very bright and draws ~1 mA per step at full scale */
static const uint8_t COLORS[][3] = {
    [LED_OFF] = {0, 0, 0}, [LED_RECORD] = {40, 0, 0}, [LED_ADVERTISE] = {0, 0, 40},
    [LED_ERROR] = {40, 12, 0}, [LED_INFO] = {25, 25, 25},
};

void status_led_init(void) {
  led_strip_config_t strip = {
      .strip_gpio_num = CONFIG_ESPEAK32_PIN_LED,
      .max_leds = 1,
      .led_model = LED_MODEL_WS2812,
      .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
  };
  led_strip_rmt_config_t rmt = {.clk_src = RMT_CLK_SRC_DEFAULT, .resolution_hz = 10 * 1000 * 1000};
  if (led_strip_new_rmt_device(&strip, &rmt, &s_strip) != ESP_OK) {
    ESP_LOGE(TAG, "RGB LED on GPIO%d not available", CONFIG_ESPEAK32_PIN_LED);
    s_strip = NULL;
  }
  status_led_set(LED_OFF);
}

void status_led_set(led_state_t s) {
  if (s == s_state || !s_strip) return;
  s_state = s;
  led_strip_set_pixel(s_strip, 0, COLORS[s][0], COLORS[s][1], COLORS[s][2]);
  led_strip_refresh(s_strip);
}

#else
#include "driver/gpio.h"

void status_led_init(void) {
  gpio_config_t out = {.pin_bit_mask = 1ULL << CONFIG_ESPEAK32_PIN_LED, .mode = GPIO_MODE_OUTPUT};
  gpio_config(&out);
  status_led_set(LED_OFF);
}

void status_led_set(led_state_t s) {
  if (s == s_state) return;
  s_state = s;
  gpio_set_level(CONFIG_ESPEAK32_PIN_LED, s != LED_OFF);
}
#endif
