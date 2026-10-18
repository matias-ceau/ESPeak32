#include "e32_button.h"
#include "test_util.h"

typedef struct {
  e32_button_t b;
  uint32_t now;
  bool recording;
  e32_btn_action_t got[16];
  int n;
} sim_t;

/* Holds the raw level for `ms` in 10 ms ticks, simulating the recorder's reaction to each action. */
static void hold(sim_t *s, bool raw, uint32_t ms) {
  for (uint32_t t = 0; t < ms; t += 10) {
    e32_btn_action_t a = e32_button_update(&s->b, raw, s->recording, s->now);
    if (a != E32_BTN_NONE) {
      CHECK(s->n < 16);
      s->got[s->n++] = a;
      if (a == E32_BTN_START) s->recording = true;
      if (a == E32_BTN_STOP || a == E32_BTN_CANCEL) s->recording = false;
    }
    s->now += 10;
  }
}

static void sim_start(sim_t *s, uint32_t now) {
  s->now = now;
  s->recording = false;
  s->n = 0;
  hold(s, false, 100);
}

static void sim_init(sim_t *s, uint32_t now) {
  e32_button_init(&s->b);
  sim_start(s, now);
}

static void sim_init_switch(sim_t *s, uint32_t now) {
  e32_button_init_switch(&s->b);
  sim_start(s, now);
}

#define EXPECT_ACTIONS(s, ...)                                         \
  do {                                                                 \
    e32_btn_action_t want[] = {__VA_ARGS__};                           \
    CHECK_EQ_U64((s).n, sizeof want / sizeof want[0]);                 \
    for (int i = 0; i < (s).n; i++) CHECK_EQ_U64((s).got[i], want[i]); \
  } while (0)

static void short_press_starts_and_keeps_recording(void) {
  sim_t s;
  sim_init(&s, 0);
  hold(&s, true, 200);
  hold(&s, false, 500);
  EXPECT_ACTIONS(s, E32_BTN_START);
  CHECK(s.recording);
}

static void second_press_stops(void) {
  sim_t s;
  sim_init(&s, 0);
  hold(&s, true, 200);
  hold(&s, false, 2000);
  hold(&s, true, 200);
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_STOP);
}

static void long_press_cancels_then_advertises(void) {
  sim_t s;
  sim_init(&s, 0);
  hold(&s, true, 1520); /* debounced edge at 30 ms: 1500 ms later is t = 1530 */
  EXPECT_ACTIONS(s, E32_BTN_START);
  hold(&s, true, 1500);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_CANCEL);
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_CANCEL, E32_BTN_ADVERTISE);
}

static void very_long_press_clears_bonds(void) {
  sim_t s;
  sim_init(&s, 0);
  hold(&s, true, 11000);
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_CANCEL, E32_BTN_CLEAR_BONDS);
}

static void bounce_is_ignored(void) {
  sim_t s;
  sim_init(&s, 0);
  hold(&s, true, 10);
  hold(&s, false, 10);
  hold(&s, true, 10);
  hold(&s, false, 500);
  CHECK_EQ_U64(s.n, 0);
}

static void release_of_stop_press_does_nothing(void) {
  sim_t s;
  sim_init(&s, 0);
  hold(&s, true, 200);
  hold(&s, false, 1000);
  hold(&s, true, 3000);
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_STOP);
}

static void now_ms_wraparound(void) {
  sim_t s;
  sim_init(&s, UINT32_MAX - 500);
  hold(&s, true, 1520);
  EXPECT_ACTIONS(s, E32_BTN_START);
  hold(&s, true, 100);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_CANCEL);
}

/* ---- latching switch mode ---- */

static void switch_on_records_off_saves(void) {
  sim_t s;
  sim_init_switch(&s, 0);
  hold(&s, true, 3000);
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_STOP);
}

static void switch_quick_flick_discards_and_advertises(void) {
  sim_t s;
  sim_init_switch(&s, 0);
  hold(&s, true, 500);
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START, E32_BTN_CANCEL, E32_BTN_ADVERTISE);
  CHECK(!s.recording);
}

static void switch_left_on_never_cancels_or_clears_bonds(void) {
  sim_t s;
  sim_init_switch(&s, 0);
  hold(&s, true, 15000);
  EXPECT_ACTIONS(s, E32_BTN_START);
  CHECK(s.recording);
}

static void switch_off_after_firmware_stopped_does_nothing(void) {
  sim_t s;
  sim_init_switch(&s, 0);
  hold(&s, true, 3000);
  s.recording = false; /* max length or storage full ended the note while the lever is still on */
  hold(&s, false, 200);
  EXPECT_ACTIONS(s, E32_BTN_START);
}

static void switch_bounce_is_ignored(void) {
  sim_t s;
  sim_init_switch(&s, 0);
  hold(&s, true, 10);
  hold(&s, false, 10);
  hold(&s, true, 10);
  hold(&s, false, 500);
  CHECK_EQ_U64(s.n, 0);
}

static void switch_on_at_boot_records(void) {
  sim_t s;
  e32_button_init_switch(&s.b);
  s.now = 0;
  s.recording = false;
  s.n = 0;
  hold(&s, true, 200);
  EXPECT_ACTIONS(s, E32_BTN_START);
}

int main(void) {
  short_press_starts_and_keeps_recording();
  second_press_stops();
  long_press_cancels_then_advertises();
  very_long_press_clears_bonds();
  bounce_is_ignored();
  release_of_stop_press_does_nothing();
  now_ms_wraparound();
  switch_on_records_off_saves();
  switch_quick_flick_discards_and_advertises();
  switch_left_on_never_cancels_or_clears_bonds();
  switch_off_after_firmware_stopped_does_nothing();
  switch_bounce_is_ignored();
  switch_on_at_boot_records();
  return 0;
}
