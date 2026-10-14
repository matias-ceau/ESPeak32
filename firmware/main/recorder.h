#pragma once
#include <stdbool.h>

bool recorder_is_recording(void);
/* Button toggles recording; never returns. */
void recorder_run(void);
