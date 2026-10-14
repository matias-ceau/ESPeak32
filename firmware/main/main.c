#include "audio_capture.h"
#include "esp_log.h"
#include "recorder.h"
#include "store.h"

void app_main(void) {
  ESP_ERROR_CHECK(store_init());
  ESP_ERROR_CHECK(audio_capture_start());
  recorder_run();
}
