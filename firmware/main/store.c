#include "store.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_littlefs.h"
#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

#define BASE "/audio"
static const char *TAG = "store";
static uint32_t s_boot_id;

static int sink_append(void *ctx, const uint8_t *data, size_t len) {
  return fwrite(data, 1, len, (FILE *)ctx) == len ? 0 : 1;
}

static int sink_rewrite_header(void *ctx, const uint8_t header[E32_HEADER_BYTES]) {
  FILE *f = ctx;
  if (fflush(f) != 0 || fseek(f, 0, SEEK_SET) != 0) return 1;
  if (fwrite(header, 1, E32_HEADER_BYTES, f) != E32_HEADER_BYTES) return 1;
  if (fflush(f) != 0) return 1;
  fseek(f, 0, SEEK_END);
  return 0;
}

esp_err_t store_init(void) {
  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    err = nvs_flash_init();
  }
  if (err != ESP_OK) return err;

  nvs_handle_t h;
  err = nvs_open("e32", NVS_READWRITE, &h);
  if (err != ESP_OK) return err;
  uint32_t boot = 0;
  nvs_get_u32(h, "boot_id", &boot);
  s_boot_id = boot + 1;
  nvs_set_u32(h, "boot_id", s_boot_id);
  nvs_commit(h);
  nvs_close(h);

  esp_vfs_littlefs_conf_t conf = {
      .base_path = BASE,
      .partition_label = "audio",
      .format_if_mount_failed = true,
      .dont_mount = false,
  };
  err = esp_vfs_littlefs_register(&conf);
  if (err != ESP_OK) return err;
  ESP_LOGI(TAG, "mounted %s, boot_id=%u, free=%u bytes", BASE, (unsigned)s_boot_id,
           (unsigned)store_free_bytes());
  return ESP_OK;
}

uint32_t store_boot_id(void) { return s_boot_id; }

uint32_t store_next_file_id(void) {
  nvs_handle_t h;
  uint32_t id = 1;
  if (nvs_open("e32", NVS_READWRITE, &h) != ESP_OK) return 0;
  nvs_get_u32(h, "next_id", &id);
  nvs_set_u32(h, "next_id", id + 1);
  nvs_commit(h);
  nvs_close(h);
  return id;
}

bool store_path(uint32_t id, char *out, size_t out_len) {
  return snprintf(out, out_len, BASE "/%08lu.e32", (unsigned long)id) < (int)out_len;
}

bool store_sink_open(uint32_t file_id, e32_sink_t *sink, void **handle) {
  char path[48];
  if (!store_path(file_id, path, sizeof path)) return false;
  FILE *f = fopen(path, "w+b");
  if (!f) return false;
  sink->append = sink_append;
  sink->rewrite_header = sink_rewrite_header;
  sink->ctx = f;
  *handle = f;
  return true;
}

void store_sink_close(void *handle) {
  if (handle) fclose((FILE *)handle);
}

size_t store_free_bytes(void) {
  size_t total = 0, used = 0;
  if (esp_littlefs_info("audio", &total, &used) != ESP_OK || used > total) return 0;
  return total - used;
}

static int cmp_u32(const void *a, const void *b) {
  uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
  return x < y ? -1 : x > y;
}

size_t store_list(uint32_t *ids, size_t max) {
  DIR *d = opendir(BASE);
  if (!d) return 0;
  size_t n = 0;
  struct dirent *e;
  while ((e = readdir(d)) != NULL && n < max) {
    unsigned long id;
    char tail[8];
    if (sscanf(e->d_name, "%8lu.%7s", &id, tail) == 2 && strcmp(tail, "e32") == 0) ids[n++] = (uint32_t)id;
  }
  closedir(d);
  qsort(ids, n, sizeof ids[0], cmp_u32);
  return n;
}

esp_err_t store_delete(uint32_t id) {
  char path[48];
  if (!store_path(id, path, sizeof path)) return ESP_ERR_INVALID_ARG;
  return remove(path) == 0 ? ESP_OK : ESP_ERR_NOT_FOUND;
}
