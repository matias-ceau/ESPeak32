#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "e32_writer.h"
#include "esp_err.h"

/* NVS + LittleFS mounted at "/audio"; increments and persists boot_id. */
esp_err_t store_init(void);
uint32_t store_boot_id(void);
/* Monotonic, persisted in NVS key "next_id"; first value 1. */
uint32_t store_next_file_id(void);
/* Creates /audio/%08u.e32 ("w+b"). `handle` is the FILE* behind the sink. */
bool store_sink_open(uint32_t file_id, e32_sink_t *sink, void **handle);
void store_sink_close(void *handle);
size_t store_free_bytes(void);
/* Ascending ids; returns the count. */
size_t store_list(uint32_t *ids, size_t max);
bool store_path(uint32_t id, char *out, size_t out_len);
esp_err_t store_delete(uint32_t id);
