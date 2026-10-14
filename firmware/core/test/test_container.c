#include <string.h>
#include "e32_container.h"
#include "test_util.h"

static const uint8_t GOLDEN[32] = {
    0x45, 0x33, 0x32, 0x41, 0x01, 0x01, 0x80, 0x3e, 0x01, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00,
    0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0xf9, 0x01, 0x00, 0x00, 0xef, 0xbe, 0xad, 0xde};

int main(void) {
  e32_header_t h = {1, 1, 16000, 1, 2, 0x0102030405060708ULL, 505, 0xDEADBEEFu};
  uint8_t out[32];
  e32_header_pack(&h, out);
  CHECK(memcmp(out, GOLDEN, 32) == 0);

  e32_header_t g;
  CHECK(e32_header_unpack(GOLDEN, &g) == 0);
  CHECK(g.codec == 1 && g.sample_rate == 16000 && g.file_id == 1 && g.boot_id == 2);
  CHECK(g.start_us == 0x0102030405060708ULL && g.sample_count == 505 && g.payload_crc32 == 0xDEADBEEFu);

  uint8_t bad[32];
  memcpy(bad, GOLDEN, 32);
  bad[0] = 'X';
  CHECK(e32_header_unpack(bad, &g) == -1);
  memcpy(bad, GOLDEN, 32);
  bad[4] = 2;
  CHECK(e32_header_unpack(bad, &g) == -2);

  const uint8_t payload[3] = {1, 2, 3};
  uint8_t fr[8];
  CHECK(e32_frame_pack(payload, 3, fr) == 5);
  const uint8_t want[5] = {3, 0, 1, 2, 3};
  CHECK(memcmp(fr, want, 5) == 0);
  return 0;
}
