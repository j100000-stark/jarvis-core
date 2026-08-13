"""Memory manager — tiered facade over the durable local store.

Tiers:
  long_term  — explicit facts the user asked JARVIS to remember ("remember my name is San")
  episodic   — important events, completed tasks, session highlights
  system     — JARVIS own configuration / self-knowledge facts
"""

from __future__ import annotations

from pathlib import Path

from .store import MemoryRecord, MemoryStore


class MemoryManager(MemoryStore):
    """Named manager facade kept separate for future memory backends."""

    def __init__(self, path: Path, max_items: int = 500) -> None:
        super().__init__(path, max_items=max_items)

    # ------------------------------------------------------------------ #
    # Tiered write helpers
    # ------------------------------------------------------------------ #

    def remember_text(self, content: str) -> MemoryRecord:
        """Explicitly named manager operation for callers outside the core."""
        return self.remember(content, tier="long_term")

    def remember_episodic(self, content: str) -> MemoryRecord:
        """Record an important event or completed task in episodic memory."""
        return self.remember(content, tier="episodic")

    def remember_system(self, content: str) -> MemoryRecord:
        """Store a JARVIS configuration or self-knowledge fact."""
        return self.remember(content, tier="system")

    # ------------------------------------------------------------------ #
    # Tiered read helpers
    # ------------------------------------------------------------------ #

    def context_for(self, query: str, limit: int = 8) -> tuple[str, ...]:
        """Return compact memory context across all tiers for a planner or brain.

        Prioritises long_term memories then episodic ones, up to `limit`.
        """
        long_term = self.search(query, tier="long_term")[:limit]
        remaining = limit - len(long_term)
        episodic = self.search(query, tier="episodic")[:remaining] if remaining > 0 else []
        combined = long_term + episodic
        return tuple(record.content for record in combined[:limit])

    def search_long_term(self, query: str = "") -> list[MemoryRecord]:
        return self.search(query, tier="long_term")

    def search_episodic(self, query: str = "") -> list[MemoryRecord]:
        return self.search(query, tier="episodic")

    def search_system(self, query: str = "") -> list[MemoryRecord]:
        return self.search(query, tier="system")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #

    def summary(self) -> str:
        """Human-readable memory summary across all tiers."""
        lt = self.count(tier="long_term")
        ep = self.count(tier="episodic")
        sy = self.count(tier="system")
        return (
            f"Memory: {lt} long-term, {ep} episodic, {sy} system "
            f"({self.count()} total)"
        )
