from __future__ import annotations

import json
from datetime import datetime, timezone

from dirac.types import LogEvent

from .base import BaseLog
from .redaction import redact


class ConsoleLog(BaseLog):
    async def event(self, event: LogEvent) -> None:
        timestamp = event.timestamp_utc or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        detail = json.dumps(redact(event.detail), ensure_ascii=False, default=str)
        scope = f" scope={event.scope.label()}" if event.scope else ""
        print(
            f"[{timestamp}] {event.level.upper()} {event.component}{scope} {event.message} {detail}",
            flush=True,
        )
