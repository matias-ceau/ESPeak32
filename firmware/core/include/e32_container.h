#ifndef E32_CONTAINER_H
#define E32_CONTAINER_H
/* .e32 container (protocol/FILE_FORMAT.md). The writer produces version 2: a header that is never rewritten, frames,
 * then an end record holding the sample count and payload CRC. */
#include <stddef.h>
#include <stdint.h>

#define E32_HEADER_BYTES 32
#define E32_UNFINALIZED 0xFFFFFFFFu
#define E32_FORMAT_VERSION 2
#define E32_END_MARKER 0xFFFFu /* never a frame length */
#define E32_END_BYTES 14       /* u16 0xFFFF, "E32E", u32 sample_count, u32 payload_crc32 */

enum { E32_CODEC_PCM16 = 0, E32_CODEC_ADPCM = 1, E32_CODEC_OPUS = 2 };

typedef struct {
  uint8_t version, codec;
  uint16_t sample_rate;
  uint32_t file_id, boot_id;
  uint64_t start_us;
  uint32_t sample_count, payload_crc32; /* version 2: always E32_UNFINALIZED and 0 */
} e32_header_t;

void e32_header_pack(const e32_header_t *h, uint8_t out[E32_HEADER_BYTES]);
/* 0 ok, -1 bad magic, -2 unsupported version (accepts 1 and 2) */
int e32_header_unpack(const uint8_t in[E32_HEADER_BYTES], e32_header_t *h);
/* Writes u16 len + payload; returns len + 2. */
size_t e32_frame_pack(const uint8_t *payload, uint16_t len, uint8_t *out);
/* Writes the version 2 end record; returns E32_END_BYTES. */
size_t e32_end_pack(uint32_t sample_count, uint32_t payload_crc32, uint8_t out[E32_END_BYTES]);

#endif
