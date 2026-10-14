#ifndef E32_CRC32_H
#define E32_CRC32_H
#include <stddef.h>
#include <stdint.h>

/* CRC-32 (IEEE, zlib semantics). Start with crc = 0; chained calls equal one call. */
uint32_t e32_crc32_update(uint32_t crc, const uint8_t *data, size_t len);

#endif
