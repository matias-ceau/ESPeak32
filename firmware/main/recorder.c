#include "recorder.h"

#include <stdio.h>
#include <sys/stat.h>

#include "audio_capture.h"
#include "ble_gatt.h"
#include "driver/gpio.h"
#include "e32_button.h"
#include "e32_dsp.h"
#include "e32_writer.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "status_led.h"
#include "store.h"

#define SLOTS_PER_READ 320
#define LOOPS_PER_SECOND 50 /* 320 samples at 16 kHz = 20 ms */
#define SAMPLE_RATE 16000
#define FREE_HEADROOM_BYTES (64 * 1024)
#define SILENCE_CHECK_SAMPLES (2 * SAMPLE_RATE)
#define SILENCE_PEAK 2

#ifdef CONFIG_ESPEAK32_CODEC_PCM16
#define CODEC E32_CODEC_PCM16
#else
#define CODEC E32_CODEC_ADPCM
#endif

static const char *TAG = "rec";
#define ADVERTISE_AFTER_NOTE_MS 60000
#define ADVERTISE_LONG_PRESS_MS 120000

static volatile bool s_recording;
static volatile uint32_t s_active_id;
static e32_button_t s_button;

bool recorder_is_recording(void) { return s_recording; }
uint32_t recorder_active_id(void) { return s_active_id; }
static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

static bool button_down(void) { return gpio_get_level(CONFIG_ESPEAK32_PIN_BUTTON) == 0; }
static void flash(int times) {
  for (int i = 0; i < times; i++) {
    status_led_set(LED_INFO);
    vTaskDelay(pdMS_TO_TICKS(80));
    status_led_set(LED_OFF);
    vTaskDelay(pdMS_TO_TICKS(80));
  }
}

static void blink_error(void) {
  for (int i = 0; i < 15; i++) {
    status_led_set(i & 1 ? LED_ERROR : LED_OFF);
    vTaskDelay(pdMS_TO_TICKS(100));
  }
  status_led_set(LED_OFF);
}

static void record_one_note(void) {
  static e32_writer_t writer;
  static e32_dsp_t dsp;
  static int32_t slots[SLOTS_PER_READ];
  static int16_t pcm[SLOTS_PER_READ];

  uint32_t id = store_next_file_id();
  e32_sink_t sink;
  void *handle = NULL;
  if (id == 0 || !store_sink_open(id, &sink, &handle)) {
    ESP_LOGE(TAG, "cannot create note file");
    blink_error();
    return;
  }
  if (e32_writer_open(&writer, CODEC, SAMPLE_RATE, id, store_boot_id(), (uint64_t)esp_timer_get_time(),
                      sink) != 0) {
    ESP_LOGE(TAG, "writer open failed");
    store_sink_close(handle);
    blink_error();
    return;
  }
  e32_dsp_init(&dsp, CONFIG_ESPEAK32_MIC_GAIN_SHIFT);

  uint64_t total = 0;
  int16_t early_peak = 0;
  bool silence_checked = false, failed = false, cancelled = false;
  unsigned loops = 0;
  s_active_id = id;
  s_recording = true;
  status_led_set(LED_RECORD);
  ESP_LOGI(TAG, "recording note id=%u", (unsigned)id);

  while (true) {
    int n = audio_capture_read(slots, SLOTS_PER_READ, 100);
    if (n < 0) {
      ESP_LOGE(TAG, "audio read failed");
      failed = true;
      break;
    }
    if (n > 0) {
      e32_dsp_process(&dsp, slots, pcm, (size_t)n);
      if (!silence_checked) {
        int16_t p = e32_peak_abs(pcm, (size_t)n);
        if (p > early_peak) early_peak = p;
      }
      if (e32_writer_push(&writer, pcm, (size_t)n) != 0) {
        ESP_LOGE(TAG, "storage write failed (full?)");
        failed = true;
        break;
      }
      total += (uint64_t)n;
      if (!silence_checked && total >= SILENCE_CHECK_SAMPLES) {
        silence_checked = true;
        if (early_peak <= SILENCE_PEAK)
          ESP_LOGW(TAG, "mic appears silent - check wiring (SD, WS, BCLK, and L/R tied to GND)");
      }
    }
    if (total >= (uint64_t)CONFIG_ESPEAK32_MAX_NOTE_SECONDS * SAMPLE_RATE) {
      ESP_LOGW(TAG, "maximum note length reached");
      break;
    }
    if (++loops % LOOPS_PER_SECOND == 0) { /* free-space query and flash commit are slow: once a second */
      if (!store_sink_sync(handle)) {
        ESP_LOGE(TAG, "flash sync failed");
        failed = true;
        break;
      }
      if (store_free_bytes() < FREE_HEADROOM_BYTES) {
        ESP_LOGW(TAG, "storage nearly full, stopping");
        failed = true;
        break;
      }
    }
    e32_btn_action_t a = e32_button_update(&s_button, button_down(), true, now_ms());
    if (a == E32_BTN_STOP) break;
    if (a == E32_BTN_CANCEL) { /* the press that started this note turned into a long press */
      cancelled = true;
      break;
    }
  }

  int rc = e32_writer_close(&writer);
  store_sink_close(handle);
  s_recording = false;
  s_active_id = 0;
  status_led_set(LED_OFF);
  if (cancelled) {
    store_delete(id);
    ESP_LOGI(TAG, "long press: note id=%u discarded", (unsigned)id);
    return;
  }
  char path[48];
  struct stat st = {0};
  if (store_path(id, path, sizeof path)) stat(path, &st);
  ESP_LOGI(TAG, "saved note id=%u samples=%llu bytes=%u%s", (unsigned)id, (unsigned long long)total,
           (unsigned)st.st_size, rc ? " (finalize error)" : "");
  if (failed || rc) blink_error();
  ble_advertise_for(ADVERTISE_AFTER_NOTE_MS);
}

void recorder_run(void) {
  gpio_config_t btn = {
      .pin_bit_mask = 1ULL << CONFIG_ESPEAK32_PIN_BUTTON,
      .mode = GPIO_MODE_INPUT,
      .pull_up_en = GPIO_PULLUP_ENABLE,
  };
  gpio_config(&btn);
  status_led_init();

  static int32_t drain[SLOTS_PER_READ];
  e32_button_init(&s_button);
  while (true) {
    audio_capture_read(drain, SLOTS_PER_READ, 10); /* keep the DMA ring drained while idle */
    switch (e32_button_update(&s_button, button_down(), false, now_ms())) {
      case E32_BTN_START:
        record_one_note();
        break;
      case E32_BTN_ADVERTISE:
        ESP_LOGI(TAG, "long press: advertising for %d s", ADVERTISE_LONG_PRESS_MS / 1000);
        ble_advertise_for(ADVERTISE_LONG_PRESS_MS);
        break;
      case E32_BTN_CLEAR_BONDS:
        ESP_LOGW(TAG, "very long press: clearing BLE bonds");
        ble_clear_bonds();
        flash(3);
        break;
      default:
        break;
    }
    status_led_set(ble_is_advertising() && (now_ms() / 500) % 2 ? LED_ADVERTISE : LED_OFF); /* slow blink */
  }
}
