#include "e32_dsp.h"

void e32_dsp_init(e32_dsp_t *st, int gain_shift) {
  st->prev_in = 0;
  st->prev_out = 0;
  st->gain_shift = gain_shift;
}

void e32_dsp_process(e32_dsp_t *st, const int32_t *slots, int16_t *out, size_t n) {
  for (size_t i = 0; i < n; i++) {
    int32_t x = slots[i] >> 16; /* top 16 bits */
    /* DC blocker, R = 32604/32768 ~ 0.995; 64-bit to avoid overflow on large steady signals */
    int64_t y = (int64_t)x - st->prev_in + (((int64_t)st->prev_out * 32604) >> 15);
    st->prev_in = x;
    st->prev_out = (int32_t)y;
    int64_t g = y * ((int64_t)1 << st->gain_shift);
    out[i] = (int16_t)(g > 32767 ? 32767 : g < -32768 ? -32768 : g);
  }
}

int16_t e32_peak_abs(const int16_t *pcm, size_t n) {
  int32_t peak = 0;
  for (size_t i = 0; i < n; i++) {
    int32_t a = pcm[i] < 0 ? -(int32_t)pcm[i] : pcm[i];
    if (a > peak) peak = a;
  }
  return (int16_t)(peak > 32767 ? 32767 : peak);
}
