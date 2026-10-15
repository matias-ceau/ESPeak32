#ifndef E32_XFER_H
#define E32_XFER_H
/* BLE transfer engine: CTRL request handling and credit-windowed DATA streaming (protocol/PROTOCOL.md).
 * Transport-agnostic; verified byte for byte against protocol/vectors/sync.txt. All calls from one task. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E32_XFER_INFO_BYTES 26
#define E32_XFER_MIN_MTU 64
#define E32_XFER_MAX_PAYLOAD 507
#define E32_XFER_MAX_LIST 256

enum { E32_XFER_OK = 0, E32_XFER_ENOENT = -1, E32_XFER_EBUSY = -2, E32_XFER_EIO = -3 };
enum { E32_XFER_CTRL = 0, E32_XFER_DATA = 1 };

typedef struct {
  void *ctx;
  size_t (*list)(void *ctx, uint32_t *ids, size_t max);                         /* complete notes, ascending */
  int (*stat)(void *ctx, uint32_t id, uint32_t *size);                           /* OK, ENOENT, EBUSY (recording) */
  int (*read)(void *ctx, uint32_t id, uint32_t off, uint8_t *buf, size_t len);   /* OK or EIO */
  int (*remove)(void *ctx, uint32_t id);                                         /* OK, ENOENT, EBUSY, EIO */
  int (*send)(void *ctx, int channel, const uint8_t *msg, size_t len);           /* blocks; nonzero = link lost */
  uint64_t (*now_us)(void *ctx);
  uint32_t (*free_bytes)(void *ctx);
  uint8_t (*battery_pct)(void *ctx); /* 255 = unknown */
} e32_xfer_io_t;

typedef struct {
  uint32_t boot_id;
  uint8_t fw[3];
  uint8_t codecs_mask;
} e32_xfer_config_t;

typedef struct {
  const e32_xfer_io_t *io;
  e32_xfer_config_t cfg;
  bool connected;
  uint16_t mtu;
  bool active; /* a GET is in progress */
  uint32_t file_id, size, offset, crc;
  uint16_t seq, credits;
  uint8_t chunk[E32_XFER_MAX_PAYLOAD + 2];
  /* id buffers live here, not on small task stacks; e32_xfer_info may run on another task, so it has its own */
  uint32_t list_ids[E32_XFER_MAX_LIST];
  uint32_t info_ids[E32_XFER_MAX_LIST];
} e32_xfer_t;

void e32_xfer_init(e32_xfer_t *x, const e32_xfer_io_t *io, const e32_xfer_config_t *cfg);
void e32_xfer_connect(e32_xfer_t *x, uint16_t mtu);
void e32_xfer_set_mtu(e32_xfer_t *x, uint16_t mtu);
void e32_xfer_disconnect(e32_xfer_t *x);
/* Handles one CTRL write; any response is sent synchronously through io->send. */
void e32_xfer_request(e32_xfer_t *x, const uint8_t *req, size_t len);
/* Sends at most one DATA chunk or the final TRANSFER_DONE; returns true if it sent something. */
bool e32_xfer_pump(e32_xfer_t *x);
void e32_xfer_info(e32_xfer_t *x, uint8_t out[E32_XFER_INFO_BYTES]);

#endif
