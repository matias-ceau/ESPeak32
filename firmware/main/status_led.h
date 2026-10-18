#pragma once

/* One status LED: the board's addressable RGB LED (WS2812, default) or a plain LED on a GPIO (menuconfig).
 * A plain LED shows every state except OFF as "on". */
typedef enum { LED_OFF, LED_RECORD, LED_ADVERTISE, LED_ERROR, LED_INFO } led_state_t;

void status_led_init(void);
/* Cheap to call often: the LED is only rewritten when the state changes. */
void status_led_set(led_state_t s);
