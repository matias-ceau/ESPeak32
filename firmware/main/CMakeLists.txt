idf_component_register(
  SRCS "main.c" "audio_capture.c" "store.c" "recorder.c"
  INCLUDE_DIRS "."
  REQUIRES core esp_driver_i2s esp_driver_gpio esp_timer nvs_flash joltwallet__littlefs)
