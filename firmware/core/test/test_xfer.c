/* Replays protocol/vectors/sync.txt against e32_xfer byte for byte. */
#include <string.h>

#include "e32_xfer.h"
#include "test_util.h"

#define MAX_NOTES 8
#define MAX_OUT 512

typedef struct {
  uint32_t id;
  uint8_t *data;
  size_t len;
  bool busy;
} note_t;

typedef struct {
  int channel; /* 0 CTRL, 1 DATA, 2 INFO */
  uint8_t msg[E32_XFER_MAX_PAYLOAD + 8];
  size_t len;
} out_t;

static note_t notes[MAX_NOTES];
static size_t n_notes;
static uint32_t fail_id, fail_off;
static bool fail_set;
static uint64_t cfg_now;
static uint32_t cfg_free;
static uint8_t cfg_battery;
static out_t outs[MAX_OUT];
static size_t n_outs, n_checked;
static const char *scenario = "";
static int line_no;

static note_t *find(uint32_t id) {
  for (size_t i = 0; i < n_notes; i++)
    if (notes[i].id == id) return &notes[i];
  return NULL;
}

static size_t io_list(void *ctx, uint32_t *ids, size_t max) {
  (void)ctx;
  size_t n = 0;
  for (size_t i = 0; i < n_notes && n < max; i++)
    if (!notes[i].busy) ids[n++] = notes[i].id;
  for (size_t i = 1; i < n; i++) /* insertion sort, ascending */
    for (size_t j = i; j > 0 && ids[j - 1] > ids[j]; j--) {
      uint32_t t = ids[j];
      ids[j] = ids[j - 1];
      ids[j - 1] = t;
    }
  return n;
}

static int io_stat(void *ctx, uint32_t id, uint32_t *size) {
  (void)ctx;
  note_t *n = find(id);
  if (!n) return E32_XFER_ENOENT;
  if (n->busy) return E32_XFER_EBUSY;
  *size = (uint32_t)n->len;
  return E32_XFER_OK;
}

static int io_read(void *ctx, uint32_t id, uint32_t off, uint8_t *buf, size_t len) {
  (void)ctx;
  note_t *n = find(id);
  if (!n || off + len > n->len) return E32_XFER_EIO;
  if (fail_set && fail_id == id && fail_off >= off && fail_off < off + len) return E32_XFER_EIO;
  memcpy(buf, n->data + off, len);
  return E32_XFER_OK;
}

static int io_remove(void *ctx, uint32_t id) {
  (void)ctx;
  note_t *n = find(id);
  if (!n) return E32_XFER_ENOENT;
  if (n->busy) return E32_XFER_EBUSY;
  free(n->data);
  *n = notes[--n_notes];
  return E32_XFER_OK;
}

static void record(int channel, const uint8_t *msg, size_t len) {
  CHECK(n_outs < MAX_OUT);
  CHECK(len <= sizeof outs[0].msg);
  outs[n_outs].channel = channel;
  memcpy(outs[n_outs].msg, msg, len);
  outs[n_outs].len = len;
  n_outs++;
}

static int io_send(void *ctx, int channel, const uint8_t *msg, size_t len) {
  (void)ctx;
  record(channel, msg, len);
  return 0;
}

static uint64_t io_now(void *ctx) { (void)ctx; return cfg_now; }
static uint32_t io_free(void *ctx) { (void)ctx; return cfg_free; }
static uint8_t io_battery(void *ctx) { (void)ctx; return cfg_battery; }

static const e32_xfer_io_t IO = {NULL, io_list, io_stat, io_read, io_remove, io_send, io_now, io_free, io_battery};

static size_t unhex(const char *s, uint8_t *out, size_t max) {
  size_t n = 0;
  while (s[0] && s[0] != '\n' && s[1] && s[1] != '\n') {
    CHECK(n < max);
    unsigned v;
    CHECK(sscanf(s, "%2x", &v) == 1);
    out[n++] = (uint8_t)v;
    s += 2;
  }
  return n;
}

static void fail_here(const char *what) {
  fprintf(stderr, "sync.txt:%d scenario %s: %s\n", line_no, scenario, what);
  exit(1);
}

static void expect_consumed(void) {
  if (n_checked != n_outs) fail_here("engine produced more outputs than expected");
  n_outs = n_checked = 0;
}

static void load_note(uint32_t id, const char *name, bool busy) {
  char path[512];
  snprintf(path, sizeof path, "%s/%s", E32_VECTOR_DIR, name);
  CHECK(n_notes < MAX_NOTES);
  note_t *n = &notes[n_notes++];
  n->id = id;
  n->data = read_file(path, &n->len);
  n->busy = busy;
}

static void reset_scenario(void) {
  for (size_t i = 0; i < n_notes; i++) free(notes[i].data);
  n_notes = n_outs = n_checked = 0;
  fail_set = false;
}

int main(void) {
  size_t len;
  uint8_t *text = read_file(VEC("sync.txt"), &len);
  char *buf = malloc(len + 1);
  memcpy(buf, text, len);
  buf[len] = 0;

  static e32_xfer_t x;
  static char name[128];
  int scenarios = 0;
  static uint8_t bytes[4096];
  for (char *line = strtok(buf, "\n"); line; line = strtok(NULL, "\n")) {
    line_no++;
    unsigned a, b, c, d, codecs, battery, freeb;
    unsigned long long now;
    if (sscanf(line, "SCENARIO %127s", name) == 1) {
      scenario = name;
      reset_scenario();
    } else if (sscanf(line, "CONFIG boot_id=%u fw=%u.%u.%u codecs=%u battery=%u free=%u now_us=%llu", &a, &b, &c,
                      &d, &codecs, &battery, &freeb, &now) == 8) {
      cfg_now = now;
      cfg_free = freeb;
      cfg_battery = (uint8_t)battery;
      e32_xfer_config_t cfg = {a, {(uint8_t)b, (uint8_t)c, (uint8_t)d}, (uint8_t)codecs};
      e32_xfer_init(&x, &IO, &cfg);
    } else if (strncmp(line, "FILE ", 5) == 0 || strncmp(line, "BUSY ", 5) == 0) {
      char fname[128];
      CHECK(sscanf(line + 5, "%u %127s", &a, fname) == 2);
      load_note(a, fname, line[0] == 'B');
    } else if (sscanf(line, "FAILREAD %u %u", &a, &b) == 2) {
      fail_set = true;
      fail_id = a;
      fail_off = b;
    } else if (sscanf(line, "CONNECT %u", &a) == 1) {
      expect_consumed();
      e32_xfer_connect(&x, (uint16_t)a);
      while (e32_xfer_pump(&x)) {
      }
    } else if (sscanf(line, "MTU %u", &a) == 1) {
      expect_consumed();
      e32_xfer_set_mtu(&x, (uint16_t)a);
      while (e32_xfer_pump(&x)) {
      }
    } else if (strncmp(line, "SEND ", 5) == 0) {
      expect_consumed();
      size_t n = unhex(line + 5, bytes, sizeof bytes);
      e32_xfer_request(&x, bytes, n);
      while (e32_xfer_pump(&x)) {
      }
    } else if (strcmp(line, "INFO") == 0) {
      expect_consumed();
      uint8_t info[E32_XFER_INFO_BYTES];
      e32_xfer_info(&x, info);
      record(2, info, sizeof info);
    } else if (strcmp(line, "DISCONNECT") == 0) {
      expect_consumed();
      e32_xfer_disconnect(&x);
    } else if (strncmp(line, "EXPECT ", 7) == 0) {
      int channel = strncmp(line + 7, "CTRL ", 5) == 0 ? 0 : strncmp(line + 7, "DATA ", 5) == 0 ? 1 : 2;
      size_t n = unhex(line + 12, bytes, sizeof bytes);
      if (n_checked >= n_outs) fail_here("expected output missing");
      out_t *o = &outs[n_checked++];
      if (o->channel != channel || o->len != n || memcmp(o->msg, bytes, n) != 0) {
        fprintf(stderr, "got channel %d:", o->channel);
        for (size_t i = 0; i < o->len; i++) fprintf(stderr, "%02x", o->msg[i]);
        fprintf(stderr, "\n");
        fail_here("output mismatch");
      }
    } else if (strcmp(line, "END") == 0) {
      expect_consumed();
      scenarios++;
    } else {
      fail_here("unknown directive");
    }
  }
  CHECK(scenarios >= 20);
  printf("%d scenarios replayed\n", scenarios);
  reset_scenario();
  free(buf);
  free(text);
  return 0;
}
