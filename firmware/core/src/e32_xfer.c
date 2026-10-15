#include "e32_xfer.h"

#include <string.h>

#include "e32_container.h"
#include "e32_crc32.h"

enum { OP_LIST = 1, OP_GET, OP_CREDIT, OP_DELETE, OP_SET_TIME, OP_ABORT };
enum { ST_OK = 0, ST_UNKNOWN_OPCODE, ST_BAD_ARGS, ST_NOT_FOUND, ST_BUSY, ST_MTU, ST_IO };
#define EV_TRANSFER_DONE 0x83

static const int8_t ARG_BYTES[] = {-1, 0, 10, 2, 4, 8, 0}; /* indexed by opcode */

static void put16(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v;
  p[1] = (uint8_t)(v >> 8);
}
static void put32(uint8_t *p, uint32_t v) {
  for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static void put64(uint8_t *p, uint64_t v) {
  for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static uint32_t get32(const uint8_t *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }

static void send(e32_xfer_t *x, int channel, const uint8_t *msg, size_t len) {
  if (x->io->send(x->io->ctx, channel, msg, len) != 0) x->active = false; /* link lost */
}

static void send_status(e32_xfer_t *x, uint8_t op, uint8_t status) {
  uint8_t m[2] = {(uint8_t)(op | 0x80), status};
  send(x, E32_XFER_CTRL, m, 2);
}

void e32_xfer_init(e32_xfer_t *x, const e32_xfer_io_t *io, const e32_xfer_config_t *cfg) {
  memset(x, 0, sizeof *x);
  x->io = io;
  x->cfg = *cfg;
  x->mtu = 23;
}

void e32_xfer_connect(e32_xfer_t *x, uint16_t mtu) {
  x->connected = true;
  x->mtu = mtu;
  x->active = false;
}

void e32_xfer_set_mtu(e32_xfer_t *x, uint16_t mtu) { x->mtu = mtu; }

void e32_xfer_disconnect(e32_xfer_t *x) {
  x->connected = false;
  x->active = false;
}

static void handle_list(e32_xfer_t *x) {
  uint32_t *ids = x->list_ids;
  size_t n = x->io->list(x->io->ctx, ids, E32_XFER_MAX_LIST);
  uint8_t m[2 + 25] = {0x80 | OP_LIST, ST_OK}; /* index u16, total u16, id u32, size u32, codec u8, boot u32, start u64 */
  if (n == 0) {
    memset(m + 2, 0, 4);
    send(x, E32_XFER_CTRL, m, 6);
    return;
  }
  for (size_t i = 0; i < n; i++) {
    uint32_t size = 0;
    uint8_t hdr[E32_HEADER_BYTES];
    e32_header_t h = {0};
    uint8_t codec = 255;
    if (x->io->stat(x->io->ctx, ids[i], &size) == E32_XFER_OK && size >= E32_HEADER_BYTES &&
        x->io->read(x->io->ctx, ids[i], 0, hdr, sizeof hdr) == E32_XFER_OK && e32_header_unpack(hdr, &h) == 0) {
      codec = h.codec;
    } else {
      h.boot_id = 0;
      h.start_us = 0;
    }
    put16(m + 2, (uint16_t)i);
    put16(m + 4, (uint16_t)n);
    put32(m + 6, ids[i]);
    put32(m + 10, size);
    m[14] = codec;
    put32(m + 15, h.boot_id);
    put64(m + 19, h.start_us);
    send(x, E32_XFER_CTRL, m, sizeof m);
  }
}

static void handle_get(e32_xfer_t *x, uint32_t id, uint32_t offset, uint16_t credits) {
  uint32_t size;
  int st = x->io->stat(x->io->ctx, id, &size);
  if (st == E32_XFER_EBUSY) {
    send_status(x, OP_GET, ST_BUSY);
    return;
  }
  if (st != E32_XFER_OK) {
    send_status(x, OP_GET, ST_NOT_FOUND);
    return;
  }
  if (offset > size) {
    send_status(x, OP_GET, ST_BAD_ARGS);
    return;
  }
  x->active = false;
  uint32_t crc = 0;
  for (uint32_t pos = 0; pos < offset;) { /* seed the whole-file CRC on a resumed GET */
    size_t n = offset - pos < sizeof x->chunk ? offset - pos : sizeof x->chunk;
    if (x->io->read(x->io->ctx, id, pos, x->chunk, n) != E32_XFER_OK) {
    send_status(x, OP_GET, ST_IO);
    return;
  }
    crc = e32_crc32_update(crc, x->chunk, n);
    pos += (uint32_t)n;
  }
  x->active = true;
  x->file_id = id;
  x->size = size;
  x->offset = offset;
  x->crc = crc;
  x->seq = 0;
  x->credits = credits;
  uint8_t m[10] = {0x80 | OP_GET, ST_OK};
  put32(m + 2, id);
  put32(m + 6, size);
  send(x, E32_XFER_CTRL, m, sizeof m);
}

static void handle_delete(e32_xfer_t *x, uint32_t id) {
  if (x->active && x->file_id == id) {
    send_status(x, OP_DELETE, ST_BUSY);
    return;
  }
  int st = x->io->remove(x->io->ctx, id);
  if (st == E32_XFER_ENOENT) {
    send_status(x, OP_DELETE, ST_NOT_FOUND);
    return;
  }
  if (st == E32_XFER_EBUSY) {
    send_status(x, OP_DELETE, ST_BUSY);
    return;
  }
  if (st != E32_XFER_OK) {
    send_status(x, OP_DELETE, ST_IO);
    return;
  }
  uint8_t m[6] = {0x80 | OP_DELETE, ST_OK};
  put32(m + 2, id);
  send(x, E32_XFER_CTRL, m, sizeof m);
}

void e32_xfer_request(e32_xfer_t *x, const uint8_t *req, size_t len) {
  if (!x->connected || len == 0) return;
  uint8_t op = req[0];
  const uint8_t *a = req + 1;
  size_t nargs = len - 1;
  if (op == OP_CREDIT) {
    if (nargs == 2 && x->active) {
      uint32_t c = (uint32_t)x->credits + get16(a);
      x->credits = c > 0xFFFF ? 0xFFFF : (uint16_t)c;
    }
    return;
  }
  if (op < OP_LIST || op > OP_ABORT) {
    send_status(x, op, ST_UNKNOWN_OPCODE);
    return;
  }
  if (x->mtu < E32_XFER_MIN_MTU) {
    send_status(x, op, ST_MTU);
    return;
  }
  if (nargs != (size_t)ARG_BYTES[op]) {
    send_status(x, op, ST_BAD_ARGS);
    return;
  }
  switch (op) {
    case OP_LIST:
      handle_list(x);
      break;
    case OP_GET:
      handle_get(x, get32(a), get32(a + 4), get16(a + 8));
      break;
    case OP_DELETE:
      handle_delete(x, get32(a));
      break;
    case OP_SET_TIME: {
      uint8_t m[10] = {0x80 | OP_SET_TIME, ST_OK};
      put64(m + 2, x->io->now_us(x->io->ctx));
      send(x, E32_XFER_CTRL, m, sizeof m);
      break;
    }
    case OP_ABORT: {
      x->active = false;
      uint8_t m[2] = {0x80 | OP_ABORT, ST_OK};
      send(x, E32_XFER_CTRL, m, sizeof m);
      break;
    }
  }
}

bool e32_xfer_pump(e32_xfer_t *x) {
  if (!x->connected || !x->active) return false;
  if (x->offset == x->size) {
    x->active = false;
    uint8_t m[10] = {EV_TRANSFER_DONE, ST_OK};
    put32(m + 2, x->file_id);
    put32(m + 6, x->crc);
    send(x, E32_XFER_CTRL, m, sizeof m);
    return true;
  }
  if (x->credits == 0) return false;
  size_t payload = (size_t)x->mtu - 5;
  if (payload > E32_XFER_MAX_PAYLOAD) payload = E32_XFER_MAX_PAYLOAD;
  size_t n = x->size - x->offset < payload ? x->size - x->offset : payload;
  if (x->io->read(x->io->ctx, x->file_id, x->offset, x->chunk + 2, n) != E32_XFER_OK) {
    x->active = false;
    uint8_t m[2] = {EV_TRANSFER_DONE, ST_IO};
    send(x, E32_XFER_CTRL, m, sizeof m);
    return true;
  }
  put16(x->chunk, x->seq);
  x->crc = e32_crc32_update(x->crc, x->chunk + 2, n);
  x->offset += (uint32_t)n;
  x->seq++;
  x->credits--;
  send(x, E32_XFER_DATA, x->chunk, n + 2);
  return true;
}

void e32_xfer_info(e32_xfer_t *x, uint8_t out[E32_XFER_INFO_BYTES]) {
  out[0] = 1;
  out[1] = x->io->battery_pct(x->io->ctx);
  memcpy(out + 2, x->cfg.fw, 3);
  out[5] = x->cfg.codecs_mask;
  put32(out + 6, x->io->free_bytes(x->io->ctx));
  put32(out + 10, x->cfg.boot_id);
  put64(out + 14, x->io->now_us(x->io->ctx));
  put32(out + 22, (uint32_t)x->io->list(x->io->ctx, x->info_ids, E32_XFER_MAX_LIST));
}
