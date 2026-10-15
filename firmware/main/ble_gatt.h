#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/* NimBLE host, ESPeak32 GATT service (protocol/PROTOCOL.md), LE Secure Connections bonding and the transfer task.
 * Does not advertise until ble_advertise_for() is called. */
esp_err_t ble_start(void);
/* Starts or extends the connectable window. While connected the window is held open; every disconnect opens a
 * fresh 60 s window so a dropped transfer can resume. */
void ble_advertise_for(uint32_t ms);
void ble_clear_bonds(void);
bool ble_is_advertising(void);
