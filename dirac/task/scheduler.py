from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone

from dirac.types import TaskDefinition


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def utc_after_minutes(minutes: int, *, base: datetime | None = None) -> str:
    origin = base or datetime.now(timezone.utc)
    return (
        (origin + timedelta(minutes=max(1, int(minutes))))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class LooseTaskScheduler:
    """Cron-like selector: every tick, run at most one random due task."""

    def __init__(
        self, *, choice: Callable[[Sequence[TaskDefinition]], TaskDefinition] | None = None
    ) -> None:
        self.choice = choice or random.choice

    def due_tasks(
        self, tasks: Sequence[TaskDefinition], *, now: datetime | None = None
    ) -> list[TaskDefinition]:
        current = now or datetime.now(timezone.utc)
        due: list[TaskDefinition] = []
        for task in tasks:
            if not task.enabled or task.schedule_minutes is None:
                continue
            if task.max_runs is not None and task.run_count >= task.max_runs:
                continue
            next_run = parse_utc(task.next_run_utc)
            if next_run is None or next_run <= current:
                due.append(task)
        return due

    def pick_one_and_advance(
        self, tasks: Sequence[TaskDefinition], *, now: datetime | None = None
    ) -> TaskDefinition | None:
        current = now or datetime.now(timezone.utc)
        due = self.due_tasks(tasks, now=current)
        if not due:
            return None
        selected = self.choice(due)
        selected.next_run_utc = utc_after_minutes(selected.schedule_minutes or 1, base=current)
        return selected
