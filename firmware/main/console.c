#include "console.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ble_gatt.h"
#include "e32_crc32.h"
#include "esp_console.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "recorder.h"
#include "sdkconfig.h"
#include "store.h"

#define DUMP_CHUNK 90

static bool parse_id(int argc, char **argv, uint32_t *id) {
  if (argc < 2) return false;
  char *end;
  unsigned long v = strtoul(argv[1], &end, 10);
  if (*end != '\0' || v == 0) return false;
  *id = (uint32_t)v;
  return true;
}

static int cmd_ls(int argc, char **argv) {
  (void)argc;
  (void)argv;
  uint32_t ids[128];
  size_t n = store_list(ids, 128);
  for (size_t i = 0; i < n; i++) {
    char path[48];
    long size = 0;
    if (store_path(ids[i], path, sizeof path)) {
      FILE *f = fopen(path, "rb");
      if (f) {
        fseek(f, 0, SEEK_END);
        size = ftell(f);
        fclose(f);
      }
    }
    printf("E32LS %u %ld\n", (unsigned)ids[i], size);
  }
  printf("E32LS END\n");
  return 0;
}

static int cmd_dump(int argc, char **argv) {
  uint32_t id;
  if (!parse_id(argc, argv, &id)) {
    printf("E32DUMP ERR notfound\n");
    return 0;
  }
  if (recorder_is_recording()) {
    printf("E32DUMP ERR busy\n");
    return 0;
  }
  char path[48];
  FILE *f = store_path(id, path, sizeof path) ? fopen(path, "rb") : NULL;
  if (!f) {
    printf("E32DUMP ERR notfound\n");
    return 0;
  }
  fseek(f, 0, SEEK_END);
  long size = ftell(f);
  fseek(f, 0, SEEK_SET);
  /* Logs from other tasks would land inside base64 lines: mute them for the dump, and yield regularly so the idle
   * task (task watchdog) runs during long dumps. */
  esp_log_level_set("*", ESP_LOG_NONE);
  printf("E32DUMP BEGIN %u %ld\n", (unsigned)id, size);
  unsigned lines = 0;
  uint8_t raw[DUMP_CHUNK];
  unsigned char b64[4 * ((DUMP_CHUNK + 2) / 3) + 1];
  uint32_t crc = 0;
  size_t n;
  while ((n = fread(raw, 1, sizeof raw, f)) > 0) {
    size_t olen = 0;
    mbedtls_base64_encode(b64, sizeof b64, &olen, raw, n);
    b64[olen] = '\0';
    crc = e32_crc32_update(crc, raw, n);
    printf("E32DUMP D %s\n", b64);
    if (++lines % 16 == 0) vTaskDelay(1);
  }
  int io_error = ferror(f);
  fclose(f);
  if (io_error)
    printf("E32DUMP ERR io\n");
  else
    printf("E32DUMP END %08x\n", (unsigned)crc);
  fflush(stdout);
  esp_log_level_set("*", CONFIG_LOG_DEFAULT_LEVEL);
  return 0;
}

static int cmd_rm(int argc, char **argv) {
  uint32_t id;
  if (!parse_id(argc, argv, &id)) {
    printf("E32RM ERR notfound\n");
    return 0;
  }
  if (recorder_is_recording()) {
    printf("E32RM ERR busy\n");
    return 0;
  }
  if (store_delete(id) == ESP_OK)
    printf("E32RM OK %u\n", (unsigned)id);
  else
    printf("E32RM ERR notfound\n");
  return 0;
}

static int cmd_adv(int argc, char **argv) {
  unsigned long seconds = 120;
  if (argc >= 2) {
    char *end;
    seconds = strtoul(argv[1], &end, 10);
    if (*end != '\0' || seconds == 0 || seconds > 3600) {
      printf("E32ADV ERR args\n");
      return 0;
    }
  }
  ble_advertise_for((uint32_t)seconds * 1000);
  printf(ble_is_advertising() ? "E32ADV OK %lu\n" : "E32ADV ERR ble\n", seconds);
  return 0;
}

static int cmd_unpair(int argc, char **argv) {
  (void)argc;
  (void)argv;
  ble_clear_bonds();
  printf("E32UNPAIR OK\n");
  return 0;
}

static int cmd_rmall(int argc, char **argv) {
  (void)argc;
  (void)argv;
  if (recorder_is_recording()) {
    printf("E32RM ERR busy\n");
    return 0;
  }
  uint32_t ids[128];
  size_t n = store_list(ids, 128);
  for (size_t i = 0; i < n; i++) store_delete(ids[i]);
  printf("E32RM OK all\n");
  return 0;
}

void console_start(void) {
  esp_console_repl_t *repl = NULL;
  esp_console_repl_config_t cfg = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
  cfg.prompt = "e32> ";
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
  esp_console_dev_usb_serial_jtag_config_t hw = ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_console_new_repl_usb_serial_jtag(&hw, &cfg, &repl));
#else
  esp_console_dev_uart_config_t hw = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_console_new_repl_uart(&hw, &cfg, &repl));
#endif
  const esp_console_cmd_t cmds[] = {
      {.command = "ls", .help = "List notes", .func = &cmd_ls},
      {.command = "dump", .help = "Dump a note: dump <id>", .func = &cmd_dump},
      {.command = "rm", .help = "Delete a note: rm <id>", .func = &cmd_rm},
      {.command = "rmall", .help = "Delete all notes", .func = &cmd_rmall},
      {.command = "adv", .help = "Advertise over BLE for N seconds (default 120)", .func = &cmd_adv},
      {.command = "unpair", .help = "Forget every bonded phone or PC", .func = &cmd_unpair},
  };
  for (size_t i = 0; i < sizeof cmds / sizeof cmds[0]; i++) ESP_ERROR_CHECK(esp_console_cmd_register(&cmds[i]));
  ESP_ERROR_CHECK(esp_console_start_repl(repl));
}
