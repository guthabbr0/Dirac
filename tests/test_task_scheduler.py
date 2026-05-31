from datetime import datetime, timezone

from dirac.task.scheduler import LooseTaskScheduler
from dirac.types import TaskDefinition


def test_scheduler_picks_one_due_task_and_advances_before_launch() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tasks = [
        TaskDefinition(
            task_id="a",
            name="a",
            prompt="a",
            schedule_minutes=1,
            next_run_utc="2025-12-31T23:59:00.000Z",
        ),
        TaskDefinition(
            task_id="b",
            name="b",
            prompt="b",
            schedule_minutes=1,
            next_run_utc="2025-12-31T23:59:00.000Z",
        ),
    ]
    scheduler = LooseTaskScheduler(choice=lambda due: due[0])
    selected = scheduler.pick_one_and_advance(tasks, now=now)
    assert selected is tasks[0]
    assert selected.next_run_utc == "2026-01-01T00:01:00.000Z"
    assert tasks[1].next_run_utc == "2025-12-31T23:59:00.000Z"
