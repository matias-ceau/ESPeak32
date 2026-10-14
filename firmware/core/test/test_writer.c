#include <stdlib.h>
#include <string.h>
#include "e32_crc32.h"
#include "e32_writer.h"
#include "test_util.h"

#define START_US 0x0102030405060708ULL

static int16_t *load_pcm(size_t *n) {
  size_t len;
  uint8_t *raw = read_file(VEC("tone_16k.pcm"), &len);
  *n = len / 2;
  int16_t *pcm = malloc(len);
  for (size_t i = 0; i < *n; i++) pcm[i] = (int16_t)(raw[2 * i] | (raw[2 * i + 1] << 8));
  free(raw);
  return pcm;
}

static e32_sink_t sink_for(mem_sink_t *m) {
  memset(m, 0, sizeof *m);
  m->limit = sizeof m->buf;
  e32_sink_t s = {mem_append, mem_rewrite, m};
  return s;
}

static void byte_exact(uint8_t codec, const char *vec) {
  size_t n, flen;
  int16_t *pcm = load_pcm(&n);
  uint8_t *want = read_file(vec, &flen);
  static mem_sink_t m;
  e32_writer_t w;
  CHECK(e32_writer_open(&w, codec, 16000, 1, 2, START_US, sink_for(&m)) == 0);
  static const size_t sizes[4] = {160, 1, 1000, 333};
  size_t pos = 0, k = 0;
  while (pos < n) {
    size_t take = sizes[k++ % 4];
    if (take > n - pos) take = n - pos;
    CHECK(e32_writer_push(&w, pcm + pos, take) == 0);
    pos += take;
  }
  CHECK(e32_writer_close(&w) == 0);
  CHECK_EQ_U64(m.len, flen);
  CHECK(memcmp(m.buf, want, flen) == 0);
  free(pcm);
  free(want);
}

static void empty_note(void) {
  size_t flen;
  uint8_t *want = read_file(VEC("empty.e32"), &flen);
  static mem_sink_t m;
  e32_writer_t w;
  CHECK(e32_writer_open(&w, E32_CODEC_ADPCM, 16000, 1, 2, START_US, sink_for(&m)) == 0);
  CHECK(e32_writer_close(&w) == 0);
  CHECK_EQ_U64(m.len, flen);
  CHECK(memcmp(m.buf, want, flen) == 0);
  free(want);
}

static void one_sample_note(void) {
  static mem_sink_t m;
  e32_writer_t w;
  int16_t s = 1234;
  CHECK(e32_writer_open(&w, E32_CODEC_ADPCM, 16000, 1, 2, START_US, sink_for(&m)) == 0);
  CHECK(e32_writer_push(&w, &s, 1) == 0);
  CHECK(e32_writer_close(&w) == 0);
  CHECK_EQ_U64(m.len, 32 + 258);
  e32_header_t h;
  CHECK(e32_header_unpack(m.buf, &h) == 0);
  CHECK_EQ_U64(h.sample_count, 1);
}

static void rejects_opus(void) {
  static mem_sink_t m;
  e32_writer_t w;
  CHECK(e32_writer_open(&w, E32_CODEC_OPUS, 16000, 1, 2, START_US, sink_for(&m)) == -1);
}

static void sink_full_midway_still_finalizes(void) {
  size_t n;
  int16_t *pcm = load_pcm(&n);
  static mem_sink_t m;
  e32_writer_t w;
  e32_sink_t s = sink_for(&m);
  m.limit = 2000;
  CHECK(e32_writer_open(&w, E32_CODEC_ADPCM, 16000, 1, 2, START_US, s) == 0);
  int failed = 0;
  for (size_t pos = 0; pos < n; pos += 1000) {
    size_t take = n - pos < 1000 ? n - pos : 1000;
    if (e32_writer_push(&w, pcm + pos, take) == -2) failed = 1;
  }
  CHECK(failed);
  CHECK(e32_writer_close(&w) == -2);
  CHECK(m.rewrites == 1);
  e32_header_t h;
  CHECK(e32_header_unpack(m.buf, &h) == 0);
  size_t frames = (m.len - 32) / 258;
  CHECK_EQ_U64(frames, 7);
  CHECK_EQ_U64(h.sample_count, 505 * frames);
  CHECK_EQ_U64(h.payload_crc32, e32_crc32_update(0, m.buf + 32, frames * 258));
  free(pcm);
}

int main(void) {
  byte_exact(E32_CODEC_ADPCM, VEC("tone_16k.adpcm.e32"));
  byte_exact(E32_CODEC_PCM16, VEC("tone_16k.pcm16.e32"));
  empty_note();
  one_sample_note();
  rejects_opus();
  sink_full_midway_still_finalizes();
  return 0;
}
