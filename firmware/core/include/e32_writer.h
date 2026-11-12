#ifndef E32_WRITER_H
#define E32_WRITER_H
#include <stddef.h>
#include <stdint.h>

#include "e32_adpcm.h"
#include "e32_container.h"

/* Append-only: the writer never seeks back, so a flash filesystem never has to copy the note to finalize it. */
typedef struct {
  int (*append)(void *ctx, const uint8_t *data, size_t len); /* 0 ok, nonzero error */
  void *ctx;
} e32_sink_t;

typedef struct e32_writer {
  e32_sink_t sink;
  e32_header_t hdr;
  e32_adpcm_enc_t enc;
  int16_t staging[E32_ADPCM_BLOCK_SAMPLES];
  size_t staged, block_samples;
  uint32_t appended_samples, crc;
  int err;
} e32_writer_t;

/* 0 ok, -1 unsupported codec, -2 sink error */
int e32_writer_open(e32_writer_t *w, uint8_t codec, uint16_t sample_rate, uint32_t file_id,
                    uint32_t boot_id, uint64_t start_us, e32_sink_t sink);
/* 0 ok; -2 sticky sink error */
int e32_writer_push(e32_writer_t *w, const int16_t *pcm, size_t n);
/* Flushes the last block and appends the end record; returns 0 or the first sticky error. After a sink error the end
 * record is not written (the failed append may have left a partial frame), so the note stays unfinalized but
 * decodable up to its last complete frame. */
int e32_writer_close(e32_writer_t *w);

#endif
