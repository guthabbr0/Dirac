from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from dirac.types import Scope, ToolResult


class BaseToolExecutor(ABC):
    @abstractmethod
    async def run(self, name: str, args: dict[str, Any], scope: Scope) -> ToolResult:
        raise NotImplementedError


class ToolExecutionService:
    def __init__(self, executor: BaseToolExecutor) -> None:
        self.executor = executor

    async def run_enabled_tool(
        self, name: str, args: dict[str, Any], scope: Scope, enabled_names: set[str]
    ) -> ToolResult:
        if name not in enabled_names:
            return ToolResult(
                name, False, {"error": "tool_not_enabled_or_unknown"}, needs_model_followup=True
            )
        return await self.executor.run(name, args, scope)
