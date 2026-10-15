#include "e32_adpcm.h"

static const int16_t STEP[89] = {
    7,     8,     9,     10,    11,    12,    13,    14,    16,    17,    19,    21,    23,    25,    28,
    31,    34,    37,    41,    45,    50,    55,    60,    66,    73,    80,    88,    97,    107,   118,
    130,   143,   157,   173,   190,   209,   230,   253,   279,   307,   337,   371,   408,   449,   494,
    544,   598,   658,   724,   796,   876,   963,   1060,  1166,  1282,  1411,  1552,  1707,  1878,  2066,
    2272,  2499,  2749,  3024,  3327,  3660,  4026,  4428,  4871,  5358,  5894,  6484,  7132,  7845,  8630,
    9493,  10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767};
static const int8_t INDEX_ADJ[8] = {-1, -1, -1, -1, 2, 4, 6, 8};

void e32_adpcm_enc_init(e32_adpcm_enc_t *st) { st->index = 0; }

/* Shared reconstruction (reference IMA shift arithmetic), so the encoder tracks exactly what a decoder will produce. */
static void reconstruct(int32_t *pred, int *index, int code) {
  int32_t step = STEP[*index];
  int32_t d = step >> 3;
  if (code & 4) d += step;
  if (code & 2) d += step >> 1;
  if (code & 1) d += step >> 2;
  int32_t p = (code & 8) ? *pred - d : *pred + d;
  *pred = p > 32767 ? 32767 : p < -32768 ? -32768 : p;
  int i = *index + INDEX_ADJ[code & 7];
  *index = i < 0 ? 0 : i > 88 ? 88 : i;
}

/* Reference IMA successive approximation against step, step/2, step/4. */
static int quantise(int32_t diff, int32_t step) {
  int code = 0;
  if (diff < 0) {
    code = 8;
    diff = -diff;
  }
  if (diff >= step) { code |= 4; diff -= step; }
  if (diff >= (step >> 1)) { code |= 2; diff -= step >> 1; }
  if (diff >= (step >> 2)) code |= 1;
  return code;
}

void e32_adpcm_encode_block(e32_adpcm_enc_t *st, const int16_t pcm[E32_ADPCM_BLOCK_SAMPLES],
                            uint8_t out[E32_ADPCM_BLOCK_BYTES]) {
  int32_t pred = pcm[0];
  int index = st->index;
  out[0] = (uint8_t)(pred & 0xFF);
  out[1] = (uint8_t)((pred >> 8) & 0xFF);
  out[2] = (uint8_t)index;
  out[3] = 0;
  for (int i = 1; i < E32_ADPCM_BLOCK_SAMPLES; i++) {
    int code = quantise(pcm[i] - pred, STEP[index]);
    reconstruct(&pred, &index, code);
    uint8_t *byte = &out[4 + (i - 1) / 2];
    if ((i - 1) % 2 == 0)
      *byte = (uint8_t)code;
    else
      *byte |= (uint8_t)(code << 4);
  }
  st->index = (uint8_t)index;
}
