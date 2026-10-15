idf_component_register(
  SRCS "main.c" "audio_capture.c" "store.c" "recorder.c" "console.c" "ble_gatt.c"
  INCLUDE_DIRS "."
  REQUIRES core bt console mbedtls esp_driver_uart esp_driver_usb_serial_jtag esp_driver_i2s esp_driver_gpio esp_timer nvs_flash joltwallet__littlefs)
