#ifndef TEST_UTIL_H
#define TEST_UTIL_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define CHECK(cond)                                                      \
  do {                                                                   \
    if (!(cond)) {                                                       \
      fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
      exit(1);                                                           \
    }                                                                    \
  } while (0)

#define CHECK_EQ_U64(a, b)                                                       \
  do {                                                                           \
    unsigned long long _a = (a), _b = (b);                                       \
    if (_a != _b) {                                                              \
      fprintf(stderr, "%s:%d: %s == %s failed: %llu vs %llu\n", __FILE__, __LINE__, #a, #b, _a, _b); \
      exit(1);                                                                   \
    }                                                                            \
  } while (0)

/* Reads a whole file; fails the test if the file is missing or empty. Caller frees. */
static inline uint8_t *read_file(const char *path, size_t *len) {
  FILE *f = fopen(path, "rb");
  if (!f) {
    fprintf(stderr, "cannot open %s\n", path);
    exit(1);
  }
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  if (n <= 0) {
    fprintf(stderr, "empty file %s\n", path);
    exit(1);
  }
  uint8_t *buf = malloc((size_t)n);
  if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
    fprintf(stderr, "read error %s\n", path);
    exit(1);
  }
  fclose(f);
  *len = (size_t)n;
  return buf;
}

#define VEC(name) (E32_VECTOR_DIR "/" name)

#endif
