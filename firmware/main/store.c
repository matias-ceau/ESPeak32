#include "store.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "esp_littlefs.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "nvs_flash.h"

#define BASE "/audio"
static const char *TAG = "store";
static uint32_t s_boot_id;
static SemaphoreHandle_t s_read_lock; /* guards the read cache against a concurrent delete */
static FILE *s_read_file;
static uint32_t s_read_id;

static int sink_append(void *ctx, const uint8_t *data, size_t len) {
  return fwrite(data, 1, len, (FILE *)ctx) == len ? 0 : 1;
}

/* LittleFS cannot overwrite in place: rewriting offset 0 copies the rest of the file into new blocks, which needs
 * about file-size bytes free. Commit what exists first so a failed or skipped finalize leaves a decodable
 * (unfinalized) note, and only attempt the rewrite when the copy fits. */
#define FINALIZE_HEADROOM (64 * 1024)

static int sink_rewrite_header(void *ctx, const uint8_t header[E32_HEADER_BYTES]) {
  FILE *f = ctx;
  if (fflush(f) != 0 || fsync(fileno(f)) != 0) return 1;
  long len = ftell(f);
  if (len < 0 || store_free_bytes() < (size_t)len + FINALIZE_HEADROOM) {
    ESP_LOGW(TAG, "not enough free space to finalize header; note left unfinalized (still decodable)");
    return 1;
  }
  if (fseek(f, 0, SEEK_SET) != 0) return 1;
  if (fwrite(header, 1, E32_HEADER_BYTES, f) != E32_HEADER_BYTES) return 1;
  if (fflush(f) != 0 || fseek(f, 0, SEEK_END) != 0 || fsync(fileno(f)) != 0) return 1;
  return 0;
}

esp_err_t store_init(void) {
  s_read_lock = xSemaphoreCreateMutex();
  if (!s_read_lock) return ESP_ERR_NO_MEM;
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
  /* never reuse an id that already has a file, even if NVS was erased */
  uint32_t ids[128];
  size_t n = store_list(ids, 128);
  if (n > 0) {
    uint32_t want = ids[n - 1] + 1, have = 1;
    if (nvs_open("e32", NVS_READWRITE, &h) == ESP_OK) {
      nvs_get_u32(h, "next_id", &have);
      if (have < want) {
        nvs_set_u32(h, "next_id", want);
        nvs_commit(h);
      }
      nvs_close(h);
    }
  }
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
  FILE *f = fopen(path, "w+bx")  /* exclusive: never truncate an existing note */;
  if (!f) return false;
  sink->append = sink_append;
  sink->rewrite_header = sink_rewrite_header;
  sink->ctx = f;
  *handle = f;
  return true;
}

void store_sink_close(void *handle) {
  if (handle && fclose((FILE *)handle) != 0) ESP_LOGE(TAG, "fclose failed; note may be incomplete");
}

bool store_sink_sync(void *handle) {
  FILE *f = handle;
  return f && fflush(f) == 0 && fsync(fileno(f)) == 0;
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

static void close_read_cache(void) {
  if (s_read_file) fclose(s_read_file);
  s_read_file = NULL;
  s_read_id = 0;
}

esp_err_t store_delete(uint32_t id) {
  char path[48];
  if (!store_path(id, path, sizeof path)) return ESP_ERR_INVALID_ARG;
  xSemaphoreTake(s_read_lock, portMAX_DELAY);
  if (s_read_id == id) close_read_cache();
  esp_err_t err = remove(path) == 0 ? ESP_OK : ESP_ERR_NOT_FOUND;
  xSemaphoreGive(s_read_lock);
  return err;
}

esp_err_t store_size(uint32_t id, uint32_t *size) {
  char path[48];
  struct stat st;
  if (!store_path(id, path, sizeof path) || stat(path, &st) != 0) return ESP_ERR_NOT_FOUND;
  *size = (uint32_t)st.st_size;
  return ESP_OK;
}

esp_err_t store_read(uint32_t id, uint32_t off, uint8_t *buf, size_t len) {
  esp_err_t err = ESP_FAIL;
  xSemaphoreTake(s_read_lock, portMAX_DELAY);
  if (s_read_id != id) {
    char path[48];
    close_read_cache();
    if (store_path(id, path, sizeof path) && (s_read_file = fopen(path, "rb")) != NULL) s_read_id = id;
  }
  if (s_read_file && fseek(s_read_file, (long)off, SEEK_SET) == 0 && fread(buf, 1, len, s_read_file) == len)
    err = ESP_OK;
  xSemaphoreGive(s_read_lock);
  return err;
}
