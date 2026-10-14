#ifndef E32_ADPCM_H
#define E32_ADPCM_H
#include <stdint.h>

#define E32_ADPCM_BLOCK_BYTES 256
#define E32_ADPCM_BLOCK_SAMPLES 505

typedef struct {
  uint8_t index;
} e32_adpcm_enc_t;

void e32_adpcm_enc_init(e32_adpcm_enc_t *st);
void e32_adpcm_encode_block(e32_adpcm_enc_t *st, const int16_t pcm[E32_ADPCM_BLOCK_SAMPLES],
                            uint8_t out[E32_ADPCM_BLOCK_BYTES]);

#endif
