"""Persistent guard against accidental high-frequency brightness writes."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import StateError, read_state, write_state

BRIGHTNESS_WRITE_MIN_INTERVAL_SECONDS = 10.0
BRIGHTNESS_WRITE_STATE_NAME = "brightness-write-rate.json"


@dataclass(frozen=True)
class WriteRateDecision:
    allowed: bool
    elapsed_seconds: float | None
    wait_seconds: float


def check_brightness_write_rate(
    path: Path,
    *,
    allow_fast_control: bool,
    now: float | None = None,
) -> WriteRateDecision:
    if allow_fast_control:
        return WriteRateDecision(True, None, 0.0)

    state = read_state(path)
    if state is None:
        return WriteRateDecision(True, None, 0.0)

    raw = state.get("acceptedAtUnix")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise StateError("Brightness write-rate state contains no valid timestamp")

    current = time.time() if now is None else now
    elapsed = current - float(raw)
    if elapsed < 0:
        # A corrected system clock must not permanently lock out control. The next
        # accepted write replaces the stale future timestamp.
        return WriteRateDecision(True, elapsed, 0.0)
    wait = max(0.0, BRIGHTNESS_WRITE_MIN_INTERVAL_SECONDS - elapsed)
    return WriteRateDecision(wait <= 0.0, elapsed, wait)


def record_brightness_write(
    path: Path,
    *,
    command: str,
    destination: str,
    now: float | None = None,
) -> None:
    timestamp = time.time() if now is None else now
    write_state(
        path,
        {
            "schema": 1,
            "role": "sanlight-brightness-write-rate",
            "acceptedAtUnix": timestamp,
            "command": command,
            "destination": destination,
        },
    )
