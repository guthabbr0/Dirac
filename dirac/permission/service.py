from __future__ import annotations

from dataclasses import dataclass

from dirac.types import Scope


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str = "ok"


class PermissionService:
    """Deterministic gate that runs before any provider call."""

    def __init__(
        self, root_operator_ids: set[str] | None = None, blocked_user_ids: set[str] | None = None
    ) -> None:
        self.root_operator_ids = set(root_operator_ids or set())
        self.blocked_user_ids = set(blocked_user_ids or set())

    async def can_run_command(self, user_id: str, command: str, scope: Scope) -> PermissionDecision:
        _ = scope
        if user_id in self.blocked_user_ids:
            return PermissionDecision(False, "blocked")
        if command in {"kill", "stop", "pause", "resume"} and user_id not in self.root_operator_ids:
            return PermissionDecision(False, "ultimate_only")
        if (
            command
            in {"tool", "tools", "task", "tasks", "provider", "providers", "scope", "scopes"}
            and user_id not in self.root_operator_ids
        ):
            return PermissionDecision(False, "root_only")
        return PermissionDecision(True)

    async def can_enter_context(self, user_id: str, scope: Scope) -> PermissionDecision:
        _ = scope
        return PermissionDecision(
            user_id not in self.blocked_user_ids,
            "blocked" if user_id in self.blocked_user_ids else "ok",
        )
