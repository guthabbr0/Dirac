from __future__ import annotations

from dirac.memory.base import BaseMemory
from dirac.types import MemoryQuery, Scope

from .runtime_notes import TOOL_TURN_STATE_PLACEHOLDER, current_time_note


class ContextAssembler:
    def __init__(self, memory: BaseMemory) -> None:
        self.memory = memory

    async def assemble(
        self, *, scope: Scope, trigger_text: str, system_prompt: str
    ) -> list[dict[str, str]]:
        memories = await self.memory.search(MemoryQuery(text=trigger_text, scope=scope, limit=5))
        messages = [
            {
                "role": "system",
                "content": TOOL_TURN_STATE_PLACEHOLDER
                + "\n\n"
                + system_prompt
                + "\n\n"
                + current_time_note(),
            },
        ]
        if memories:
            memory_lines = [f"discord {item.discord_id}: {item.annotations}" for item in memories]
            messages.append(
                {"role": "user", "content": "Durable memory context:\n" + "\n".join(memory_lines)}
            )
        messages.append({"role": "user", "content": trigger_text})
        return messages
