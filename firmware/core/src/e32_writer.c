#include "e32_writer.h"

#include <string.h>

#include "e32_crc32.h"

int e32_writer_open(e32_writer_t *w, uint8_t codec, uint16_t sample_rate, uint32_t file_id,
                    uint32_t boot_id, uint64_t start_us, e32_sink_t sink) {
  if (codec != E32_CODEC_PCM16 && codec != E32_CODEC_ADPCM) return -1;
  memset(w, 0, sizeof *w);
  w->sink = sink;
  w->block_samples = codec == E32_CODEC_ADPCM ? E32_ADPCM_BLOCK_SAMPLES : 256;
  w->hdr = (e32_header_t){1, codec, sample_rate, file_id, boot_id, start_us, E32_UNFINALIZED, 0};
  e32_adpcm_enc_init(&w->enc);
  uint8_t h[E32_HEADER_BYTES];
  e32_header_pack(&w->hdr, h);
  if (w->sink.append(w->sink.ctx, h, sizeof h) != 0) {
    w->err = -2;
    return -2;
  }
  return 0;
}

/* Encodes the staged samples as one frame and appends it. */
static void flush_block(e32_writer_t *w) {
  uint8_t frame[2 + 512];
  size_t real = w->staged, payload_len;
  if (w->hdr.codec == E32_CODEC_ADPCM) {
    memset(w->staging + real, 0, (E32_ADPCM_BLOCK_SAMPLES - real) * sizeof(int16_t));
    e32_adpcm_encode_block(&w->enc, w->staging, frame + 2);
    payload_len = E32_ADPCM_BLOCK_BYTES;
  } else {
    for (size_t i = 0; i < real; i++) {
      frame[2 + 2 * i] = (uint8_t)(w->staging[i] & 0xFF);
      frame[2 + 2 * i + 1] = (uint8_t)((w->staging[i] >> 8) & 0xFF);
    }
    payload_len = real * 2;
  }
  frame[0] = (uint8_t)payload_len;
  frame[1] = (uint8_t)(payload_len >> 8);
  w->staged = 0;
  if (w->sink.append(w->sink.ctx, frame, 2 + payload_len) != 0) {
    w->err = -2;
    return;
  }
  w->crc = e32_crc32_update(w->crc, frame, 2 + payload_len);
  w->appended_samples += (uint32_t)real;
}

int e32_writer_push(e32_writer_t *w, const int16_t *pcm, size_t n) {
  size_t i = 0;
  while (i < n && !w->err) {
    size_t take = w->block_samples - w->staged;
    if (take > n - i) take = n - i;
    memcpy(w->staging + w->staged, pcm + i, take * sizeof(int16_t));
    w->staged += take;
    i += take;
    if (w->staged == w->block_samples) flush_block(w);
  }
  return w->err;
}

int e32_writer_close(e32_writer_t *w) {
  if (w->staged > 0 && !w->err) flush_block(w);
  w->hdr.sample_count = w->appended_samples;
  w->hdr.payload_crc32 = w->crc;
  uint8_t h[E32_HEADER_BYTES];
  e32_header_pack(&w->hdr, h);
  int rc = w->sink.rewrite_header(w->sink.ctx, h);
  if (w->err) return w->err;
  return rc != 0 ? -2 : 0;
}
