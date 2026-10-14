#include <string.h>
#include "e32_adpcm.h"
#include "e32_container.h"
#include "test_util.h"

static void golden_first_bytes(void) {
  int16_t pcm[E32_ADPCM_BLOCK_SAMPLES] = {0, 7};
  uint8_t out[E32_ADPCM_BLOCK_BYTES];
  e32_adpcm_enc_t st;
  e32_adpcm_enc_init(&st);
  e32_adpcm_encode_block(&st, pcm, out);
  CHECK(out[0] == 0 && out[1] == 0 && out[2] == 0 && out[3] == 0);
  CHECK(out[4] == 0xB4);
}

static void silence_block_is_zero(void) {
  int16_t pcm[E32_ADPCM_BLOCK_SAMPLES] = {0};
  uint8_t out[E32_ADPCM_BLOCK_BYTES], zero[E32_ADPCM_BLOCK_BYTES] = {0};
  e32_adpcm_enc_t st;
  e32_adpcm_enc_init(&st);
  e32_adpcm_encode_block(&st, pcm, out);
  CHECK(memcmp(out, zero, sizeof out) == 0);
}

static void matches_vector(void) {
  size_t pcm_len, file_len;
  uint8_t *raw = read_file(VEC("tone_16k.pcm"), &pcm_len);
  uint8_t *file = read_file(VEC("tone_16k.adpcm.e32"), &file_len);
  size_t n = pcm_len / 2, pos = E32_HEADER_BYTES, done = 0, blocks = 0;
  e32_adpcm_enc_t st;
  e32_adpcm_enc_init(&st);
  while (done < n) {
    int16_t pcm[E32_ADPCM_BLOCK_SAMPLES] = {0};
    size_t take = n - done < E32_ADPCM_BLOCK_SAMPLES ? n - done : E32_ADPCM_BLOCK_SAMPLES;
    for (size_t i = 0; i < take; i++)
      pcm[i] = (int16_t)(raw[2 * (done + i)] | (raw[2 * (done + i) + 1] << 8));
    uint8_t out[E32_ADPCM_BLOCK_BYTES];
    e32_adpcm_encode_block(&st, pcm, out);
    CHECK(pos + 2 + E32_ADPCM_BLOCK_BYTES <= file_len);
    CHECK_EQ_U64(file[pos] | (file[pos + 1] << 8), E32_ADPCM_BLOCK_BYTES);
    CHECK(memcmp(out, file + pos + 2, E32_ADPCM_BLOCK_BYTES) == 0);
    pos += 2 + E32_ADPCM_BLOCK_BYTES;
    done += take;
    blocks++;
  }
  CHECK_EQ_U64(pos, file_len);
  CHECK(blocks > 1);
  free(raw);
  free(file);
}

int main(void) {
  golden_first_bytes();
  silence_block_is_zero();
  matches_vector();
  return 0;
}
