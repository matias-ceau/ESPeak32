#ifndef E32_BUTTON_H
#define E32_BUTTON_H
/* One-button classifier: record / stop, long press = cancel then advertise, very long press = clear bonds. */
#include <stdbool.h>
#include <stdint.h>

typedef enum {
  E32_BTN_NONE,
  E32_BTN_START,
  E32_BTN_STOP,
  E32_BTN_CANCEL,
  E32_BTN_ADVERTISE,
  E32_BTN_CLEAR_BONDS
} e32_btn_action_t;

#define E32_BTN_DEBOUNCE_MS 30
#define E32_BTN_LONG_MS 1500
#define E32_BTN_CLEAR_MS 10000

typedef struct {
  bool raw, pressed;
  uint32_t raw_since, press_at;
  uint8_t phase;
} e32_button_t;

void e32_button_init(e32_button_t *b);
/* Call every ~10 ms with the raw (undebounced) level; returns at most one action. */
e32_btn_action_t e32_button_update(e32_button_t *b, bool raw_pressed, bool recording, uint32_t now_ms);

#endif
