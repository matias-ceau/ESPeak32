#include "e32_button.h"

#include <string.h>

enum { PH_NONE, PH_FROM_IDLE, PH_LONG, PH_CLEARED, PH_STOP_PRESS };

void e32_button_init(e32_button_t *b) { memset(b, 0, sizeof *b); }

e32_btn_action_t e32_button_update(e32_button_t *b, bool raw_pressed, bool recording, uint32_t now_ms) {
  if (raw_pressed != b->raw) {
    b->raw = raw_pressed;
    b->raw_since = now_ms;
  }
  if (b->raw != b->pressed && (uint32_t)(now_ms - b->raw_since) >= E32_BTN_DEBOUNCE_MS) {
    b->pressed = b->raw;
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
