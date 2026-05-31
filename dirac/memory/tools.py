from __future__ import annotations

from typing import Any
from dataclasses import asdict

from dirac.types import MemoryPatch, MemoryQuery, MemoryWrite

from .base import BaseMemory
from .contracts import (
    is_discord_id,
    normalize_discord_id,
    parse_confidence,
    parse_tags,
    validation_error,
)


class MemoryToolFacade:
    """Tool-call shaped facade over BaseMemory. Storage stays hidden."""

    def __init__(self, memory: BaseMemory, *, created_by: str = "tool") -> None:
        self.memory = memory
        self.created_by = created_by

    async def search(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("int_limit") or 10)
        query = MemoryQuery(
            text=args.get("str_query"),
            discord_id=normalize_discord_id(args.get("str_discord_id")),
            limit=max(1, min(limit, 50)),
        )
        rows = await self.memory.search(query)
        return {"ok": True, "memories": [asdict(row) for row in rows]}

    async def add(self, args: dict[str, Any]) -> dict[str, Any]:
        issues: list[str] = []
        discord_id = normalize_discord_id(args.get("str_discord_id"))
        if not is_discord_id(discord_id):
            issues.append(
                "str_discord_id invalid or missing: provide one Discord snowflake id or mention."
            )
        annotations = str(args.get("str_annotations") or "").strip()
        if not annotations:
            issues.append("str_annotations missing: provide the durable memory text.")
        tags, tag_error = parse_tags(args.get("array_tags"))
        if tag_error:
            issues.append(tag_error)
        confidence, confidence_error = parse_confidence(args.get("float_confidence"), 0.7)
        if confidence_error:
            issues.append(confidence_error)
        if issues:
            return validation_error("memory_add", issues)
        row = await self.memory.add(
            MemoryWrite(discord_id, annotations, tags, confidence, self.created_by)
        )
        return {"ok": True, "memory": asdict(row)}

    async def update(self, args: dict[str, Any]) -> dict[str, Any]:
        memory_id = str(args.get("int_memory_id") or "").strip().lstrip("#")
        if not memory_id.isdigit():
            return validation_error("memory_update", ["int_memory_id missing or invalid."])
        tags, tag_error = parse_tags(args.get("array_tags"))
        confidence, confidence_error = parse_confidence(args.get("float_confidence"), 0.7)
        issues = [item for item in (tag_error, confidence_error) if item]
        if issues:
            return validation_error("memory_update", issues)
        row = await self.memory.update(
            memory_id,
            MemoryPatch(str(args.get("str_annotations") or ""), tags, confidence, self.created_by),
        )
        return {"ok": True, "memory": asdict(row)}

    async def delete(self, args: dict[str, Any]) -> dict[str, Any]:
        memory_id = str(args.get("int_memory_id") or "").strip().lstrip("#")
        if not memory_id.isdigit():
            return validation_error("memory_delete", ["int_memory_id missing or invalid."])
        await self.memory.delete(memory_id)
        return {"ok": True, "int_memory_id": memory_id}
