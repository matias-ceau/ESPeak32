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
  e32_sink_t s = {mem_append, m};
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

static uint32_t get32(const uint8_t *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

/* The header is written once (version 2, unfinalized fields); the end record carries the count and CRC. */
static void one_sample_note(void) {
  static mem_sink_t m;
  e32_writer_t w;
  int16_t s = 1234;
  CHECK(e32_writer_open(&w, E32_CODEC_ADPCM, 16000, 1, 2, START_US, sink_for(&m)) == 0);
  CHECK(e32_writer_push(&w, &s, 1) == 0);
  CHECK(e32_writer_close(&w) == 0);
  CHECK_EQ_U64(m.len, 32 + 258 + E32_END_BYTES);
  e32_header_t h;
  CHECK(e32_header_unpack(m.buf, &h) == 0);
  CHECK_EQ_U64(h.version, 2);
  CHECK_EQ_U64(h.sample_count, E32_UNFINALIZED);
  CHECK_EQ_U64(h.payload_crc32, 0);
  const uint8_t *end = m.buf + m.len - E32_END_BYTES;
  CHECK(end[0] == 0xFF && end[1] == 0xFF && memcmp(end + 2, "E32E", 4) == 0);
  CHECK_EQ_U64(get32(end + 6), 1);
  CHECK_EQ_U64(get32(end + 10), e32_crc32_update(0, m.buf + 32, 258));
}

static void rejects_opus(void) {
  static mem_sink_t m;
  e32_writer_t w;
  CHECK(e32_writer_open(&w, E32_CODEC_OPUS, 16000, 1, 2, START_US, sink_for(&m)) == -1);
}

/* A failed append may leave a partial frame on a real filesystem, so the writer adds no end record after it: the note
 * stays unfinalized and decodes up to its last complete frame. */
static void sink_full_midway_stays_unfinalized(void) {
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
  CHECK_EQ_U64(m.len, 32 + 7 * 258); /* seven whole frames, nothing after them */
  e32_header_t h;
  CHECK(e32_header_unpack(m.buf, &h) == 0);
  CHECK_EQ_U64(h.sample_count, E32_UNFINALIZED);
  free(pcm);
}

/* The end record itself does not fit: the note stays unfinalized with every frame intact. */
static void end_record_does_not_fit(void) {
  static mem_sink_t m;
  e32_writer_t w;
  int16_t s = 1;
  e32_sink_t sk = sink_for(&m);
  m.limit = 32 + 258 + E32_END_BYTES - 1;
  CHECK(e32_writer_open(&w, E32_CODEC_ADPCM, 16000, 1, 2, START_US, sk) == 0);
  CHECK(e32_writer_push(&w, &s, 1) == 0);
  CHECK(e32_writer_close(&w) == -2);
  CHECK_EQ_U64(m.len, 32 + 258);
}

int main(void) {
  byte_exact(E32_CODEC_ADPCM, VEC("tone_16k.adpcm.e32"));
  byte_exact(E32_CODEC_PCM16, VEC("tone_16k.pcm16.e32"));
  empty_note();
  one_sample_note();
  rejects_opus();
  sink_full_midway_stays_unfinalized();
  end_record_does_not_fit();
  return 0;
}
