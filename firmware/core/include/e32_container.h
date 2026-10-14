#ifndef E32_CONTAINER_H
#define E32_CONTAINER_H
#include <stddef.h>
#include <stdint.h>

#define E32_HEADER_BYTES 32
#define E32_UNFINALIZED 0xFFFFFFFFu

enum { E32_CODEC_PCM16 = 0, E32_CODEC_ADPCM = 1, E32_CODEC_OPUS = 2 };

typedef struct {
  uint8_t version, codec;
  uint16_t sample_rate;
  uint32_t file_id, boot_id;
  uint64_t start_us;
  uint32_t sample_count, payload_crc32;
} e32_header_t;

void e32_header_pack(const e32_header_t *h, uint8_t out[E32_HEADER_BYTES]);
/* 0 ok, -1 bad magic, -2 bad version */
int e32_header_unpack(const uint8_t in[E32_HEADER_BYTES], e32_header_t *h);
/* Writes u16 len + payload; returns len + 2. */
size_t e32_frame_pack(const uint8_t *payload, uint16_t len, uint8_t *out);

#endif
