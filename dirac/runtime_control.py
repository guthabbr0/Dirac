from __future__ import annotations

import time
from dataclasses import dataclass


DEFAULT_STOP_SECONDS = 60
MAX_HOLD_SECONDS = 86_400


def clamp_hold_seconds(value: object, default: int = DEFAULT_STOP_SECONDS) -> int:
    try:
        seconds = int(float(str(value)))
    except Exception:
        seconds = default
    return max(1, min(seconds, MAX_HOLD_SECONDS))


@dataclass
class RuntimeHold:
    mode: str = "running"
    until_monotonic: float | None = None
    reason: str = ""
    started_by: str = ""
    generation: int = 0

    def remaining_seconds(self, now: float | None = None) -> int | None:
        if self.until_monotonic is None:
            return None
        remaining = int(round(self.until_monotonic - (time.monotonic() if now is None else now)))
        return max(0, remaining)


class RuntimeControl:
    """Process-local emergency hold state for Discord replies and background work."""

    def __init__(self) -> None:
        self._hold = RuntimeHold()

    def _expire_if_needed(self) -> None:
        if self._hold.until_monotonic is None:
            return
        if time.monotonic() >= self._hold.until_monotonic:
            self._hold = RuntimeHold(generation=self._hold.generation + 1)

    def status(self) -> RuntimeHold:
        self._expire_if_needed()
        return RuntimeHold(
            mode=self._hold.mode,
            until_monotonic=self._hold.until_monotonic,
            reason=self._hold.reason,
            started_by=self._hold.started_by,
            generation=self._hold.generation,
        )

    def stop(self, seconds: object = DEFAULT_STOP_SECONDS, *, started_by: str = "") -> RuntimeHold:
        duration = clamp_hold_seconds(seconds, DEFAULT_STOP_SECONDS)
        self._hold = RuntimeHold(
            mode="stopped",
            until_monotonic=time.monotonic() + duration,
            reason=f"cooldown:{duration}s",
            started_by=str(started_by),
            generation=self._hold.generation + 1,
        )
        return self.status()

    def pause(self, seconds: object | None = None, *, started_by: str = "") -> RuntimeHold:
        until = None if seconds is None else time.monotonic() + clamp_hold_seconds(seconds, DEFAULT_STOP_SECONDS)
        reason = "manual" if seconds is None else f"pause:{clamp_hold_seconds(seconds, DEFAULT_STOP_SECONDS)}s"
        self._hold = RuntimeHold(
            mode="paused",
            until_monotonic=until,
            reason=reason,
            started_by=str(started_by),
            generation=self._hold.generation + 1,
        )
        return self.status()

    def resume(self) -> RuntimeHold:
        self._hold = RuntimeHold(generation=self._hold.generation + 1)
        return self.status()

    def is_stopped(self) -> bool:
        return self.status().mode == "stopped"

    def is_paused(self) -> bool:
        return self.status().mode == "paused"

    def is_held(self) -> bool:
        return self.status().mode in {"stopped", "paused"}

    def should_accept_message(self, is_ultimate_operator: bool) -> bool:
        state = self.status()
        return is_ultimate_operator or state.mode != "stopped"

    def should_answer(self, is_ultimate_operator: bool) -> bool:
        state = self.status()
        return is_ultimate_operator or state.mode == "running"

    def background_suspended(self) -> bool:
        return self.is_held()


runtime_control = RuntimeControl()
