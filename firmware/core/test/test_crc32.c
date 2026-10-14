#include <string.h>
#include "e32_crc32.h"
#include "test_util.h"

int main(void) {
  const uint8_t *s = (const uint8_t *)"123456789";
  CHECK_EQ_U64(e32_crc32_update(0, s, 9), 0xCBF43926u);
  uint32_t c = e32_crc32_update(0, s, 4);
  c = e32_crc32_update(c, s + 4, 5);
  CHECK_EQ_U64(c, 0xCBF43926u);
  CHECK_EQ_U64(e32_crc32_update(0, NULL, 0), 0);
  return 0;
}
