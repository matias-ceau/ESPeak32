#include "e32_dsp.h"
#include "test_util.h"

static void constant_input_decays_to_zero(void) {
  e32_dsp_t st;
  int32_t in[4000];
  int16_t out[4000];
  for (int i = 0; i < 4000; i++) in[i] = 1000 << 16;
  e32_dsp_init(&st, 0);
  e32_dsp_process(&st, in, out, 4000);
  CHECK(out[0] == 1000);
  CHECK(out[3999] >= -1 && out[3999] <= 1);
}

static void gain_shift_saturates_not_wraps(void) {
  e32_dsp_t st;
  int32_t hi = 0x7FFF0000, lo = (int32_t)0x80000000u;
  int16_t out;
  e32_dsp_init(&st, 3);
  e32_dsp_process(&st, &hi, &out, 1);
  CHECK(out == 32767);
  e32_dsp_init(&st, 3);
  e32_dsp_process(&st, &lo, &out, 1);
  CHECK(out == -32768);
}

static void peak_of_silence_is_zero(void) {
  e32_dsp_t st;
  int32_t in[1000] = {0};
  int16_t out[1000];
  e32_dsp_init(&st, 2);
  e32_dsp_process(&st, in, out, 1000);
  for (int i = 0; i < 1000; i++) CHECK(out[i] == 0);
  CHECK(e32_peak_abs(out, 1000) == 0);
}

static void peak_abs_basic_and_saturates(void) {
  int16_t a[3] = {-5, 3, 4};
  CHECK(e32_peak_abs(a, 3) == 5);
  CHECK(e32_peak_abs(a, 0) == 0);
  int16_t b[2] = {1, -32768};
  CHECK(e32_peak_abs(b, 2) == 32767);
}

int main(void) {
  constant_input_decays_to_zero();
  gain_shift_saturates_not_wraps();
  peak_of_silence_is_zero();
  peak_abs_basic_and_saturates();
  return 0;
}
