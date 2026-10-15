#pragma once
#include <stdbool.h>
#include <stdint.h>

bool recorder_is_recording(void);
/* Id of the note being recorded, 0 when idle. */
uint32_t recorder_active_id(void);
/* Button toggles recording; never returns. */
void recorder_run(void);
