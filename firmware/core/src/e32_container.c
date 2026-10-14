#include "e32_container.h"

#include <string.h>

static void put16(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
}
static void put32(uint8_t *p, uint32_t v) {
  for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static void put64(uint8_t *p, uint64_t v) {
  for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t get64(const uint8_t *p) { return (uint64_t)get32(p) | ((uint64_t)get32(p + 4) << 32); }

void e32_header_pack(const e32_header_t *h, uint8_t out[E32_HEADER_BYTES]) {
  memcpy(out, "E32A", 4);
  out[4] = h->version;
  out[5] = h->codec;
  put16(out + 6, h->sample_rate);
  put32(out + 8, h->file_id);
  put32(out + 12, h->boot_id);
  put64(out + 16, h->start_us);
  put32(out + 24, h->sample_count);
  put32(out + 28, h->payload_crc32);
}

int e32_header_unpack(const uint8_t in[E32_HEADER_BYTES], e32_header_t *h) {
  if (memcmp(in, "E32A", 4) != 0) return -1;
  if (in[4] != 1) return -2;
  h->version = in[4];
  h->codec = in[5];
  h->sample_rate = get16(in + 6);
  h->file_id = get32(in + 8);
  h->boot_id = get32(in + 12);
  h->start_us = get64(in + 16);
  h->sample_count = get32(in + 24);
  h->payload_crc32 = get32(in + 28);
  return 0;
}

size_t e32_frame_pack(const uint8_t *payload, uint16_t len, uint8_t *out) {
  put16(out, len);
  memcpy(out + 2, payload, len);
  return (size_t)len + 2;
}
