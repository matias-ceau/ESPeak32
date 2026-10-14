#ifndef E32_DSP_H
#define E32_DSP_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
  int32_t prev_in, prev_out;
  int gain_shift;
} e32_dsp_t;

void e32_dsp_init(e32_dsp_t *st, int gain_shift); /* gain_shift 0..6 */
/* slots are raw 32-bit I2S words (24-bit sample, MSB-aligned). */
void e32_dsp_process(e32_dsp_t *st, const int32_t *slots, int16_t *out, size_t n);
/* max |sample| saturated to 32767; 0 for n == 0 */
int16_t e32_peak_abs(const int16_t *pcm, size_t n);

#endif
