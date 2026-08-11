"""Memory manager interface layered over the durable local store."""

from __future__ import annotations

from pathlib import Path

from .store import MemoryRecord, MemoryStore


class MemoryManager(MemoryStore):
    """Named manager facade kept separate for future memory backends."""

    def __init__(self, path: Path, max_items: int = 100) -> None:
        super().__init__(path, max_items=max_items)

    def context_for(self, query: str, limit: int = 8) -> tuple[str, ...]:
        """Return compact memory context for a planner or brain."""
        return tuple(record.content for record in self.search(query)[:limit])

    def remember_text(self, content: str) -> MemoryRecord:
        """Explicitly named manager operation for callers outside the core."""
        return self.remember(content)