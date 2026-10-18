#include "e32_button.h"

#include <string.h>

enum { PH_NONE, PH_FROM_IDLE, PH_LONG, PH_CLEARED, PH_STOP_PRESS };

void e32_button_init(e32_button_t *b) { memset(b, 0, sizeof *b); }

void e32_button_init_switch(e32_button_t *b) {
  memset(b, 0, sizeof *b);
  b->is_switch = true;
}

static e32_btn_action_t switch_update(e32_button_t *b, bool edge, bool recording, uint32_t now_ms) {
  if (b->advertise_pending) { /* second half of a quick flick: CANCEL was returned on the previous call */
    b->advertise_pending = false;
    return E32_BTN_ADVERTISE;
  }
  if (!edge) return E32_BTN_NONE;
  if (b->pressed) {
    b->press_at = now_ms;
    return recording ? E32_BTN_NONE : E32_BTN_START;
  }
  if (!recording) return E32_BTN_NONE; /* the firmware already ended the note (length cap, storage full) */
  if ((uint32_t)(now_ms - b->press_at) < E32_BTN_LONG_MS) {
    b->advertise_pending = true;
    return E32_BTN_CANCEL;
  }
  return E32_BTN_STOP;
}

e32_btn_action_t e32_button_update(e32_button_t *b, bool raw_pressed, bool recording, uint32_t now_ms) {
  if (raw_pressed != b->raw) {
    b->raw = raw_pressed;
    b->raw_since = now_ms;
  }
  bool edge = b->raw != b->pressed && (uint32_t)(now_ms - b->raw_since) >= E32_BTN_DEBOUNCE_MS;
  if (edge) b->pressed = b->raw;
  if (b->is_switch) return switch_update(b, edge, recording, now_ms);
  if (edge) {
    if (b->pressed) {
      b->press_at = now_ms;
      b->phase = recording ? PH_STOP_PRESS : PH_FROM_IDLE;
      return recording ? E32_BTN_STOP : E32_BTN_START;
    }
    uint8_t phase = b->phase;
    b->phase = PH_NONE;
    return phase == PH_LONG ? E32_BTN_ADVERTISE : E32_BTN_NONE;
  }
  if (b->pressed) {
    uint32_t held = now_ms - b->press_at;
    if (b->phase == PH_FROM_IDLE && held >= E32_BTN_LONG_MS) {
      b->phase = PH_LONG;
      return E32_BTN_CANCEL;
    }
    if (b->phase == PH_LONG && held >= E32_BTN_CLEAR_MS) {
      b->phase = PH_CLEARED;
      return E32_BTN_CLEAR_BONDS;
    }
  }
  return E32_BTN_NONE;
}
