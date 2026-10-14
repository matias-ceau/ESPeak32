"""Minimal 16-bit mono WAV writer."""

from __future__ import annotations

import struct
import wave
from typing import Sequence


def write_wav(path_or_file, samples: Sequence[int], sample_rate: int) -> None:
    with wave.open(path_or_file, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
