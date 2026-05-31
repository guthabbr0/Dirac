from __future__ import annotations

from typing import Protocol

from dirac.memory.base import BaseMemory
from dirac.provider.base import BaseProviderClient
from dirac.types import MemoryQuery, ProviderRequest, Scope

from .audit import ConsolidationAudit


class VisibleEventSource(Protocol):
    async def recent_visible_events(self, *, minutes: int, limit: int) -> list[dict[str, str]]: ...


class ConsolidationService:
    """Quiet-phase memory assimilation. This is separate from ordinary periodic tasks."""

    def __init__(
        self, *, memory: BaseMemory, provider: BaseProviderClient, events: VisibleEventSource
    ) -> None:
        self.memory = memory
        self.provider = provider
        self.events = events

    async def consolidate(
        self, *, scope: Scope, model: str, minutes: int = 10
    ) -> ConsolidationAudit:
        visible_events = await self.events.recent_visible_events(minutes=minutes, limit=250)
        if not visible_events:
            return ConsolidationAudit(True, "No visible events to consolidate.")
        _existing = await self.memory.search(MemoryQuery(scope=scope, limit=10))
        request = ProviderRequest(
            messages=[
                {
                    "role": "user",
                    "content": "Consolidate these visible events into durable memory candidates.",
                }
            ],
            model=model,
            scope=scope,
            source="consolidation",
            metadata={"event_count": len(visible_events)},
        )
        response = await self.provider.chat(request)
        return ConsolidationAudit(
            True, response.content, detail={"event_count": len(visible_events)}
        )
