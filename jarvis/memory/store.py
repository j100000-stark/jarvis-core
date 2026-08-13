"""Small JSON-backed memory store for JARVIS V1.

Memory is tiered:
  long_term  — explicit facts the user asked JARVIS to remember
  episodic   — important events, task results, sessions
  system     — JARVIS configuration facts
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A single piece of user-provided memory."""

    identifier: int
    content: str
    created_at: str
    tier: str = "long_term"   # "long_term" | "episodic" | "system"


class MemoryStore:
    """Store memories locally without a database or external service."""

    def __init__(self, path: Path, max_items: int = 500) -> None:
        self.path = path
        self.max_items = max_items
        self._records: list[MemoryRecord] = []
        self._load()

    def remember(self, content: str, tier: str = "long_term") -> MemoryRecord:
        """Persist a new memory and return it."""
        cleaned = " ".join(content.split())
        if not cleaned:
            raise ValueError("Memory content cannot be empty.")

        next_id = max((record.identifier for record in self._records), default=0) + 1
        record = MemoryRecord(
            identifier=next_id,
            content=cleaned,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            tier=tier,
        )
        self._records.append(record)
        self._records = self._records[-self.max_items :]
        self._save()
        return record

    def search(self, query: str = "", tier: str | None = None) -> list[MemoryRecord]:
        """Return newest matching records, optionally filtered by tier."""
        normalized = query.casefold().strip()
        matching = (
            record
            for record in reversed(self._records)
            if (tier is None or record.tier == tier)
            and (not normalized or normalized in record.content.casefold())
        )
        return list(matching)

    def count(self, tier: str | None = None) -> int:
        if tier is None:
            return len(self._records)
        return sum(1 for r in self._records if r.tier == tier)

    def forget(self, identifier: int) -> bool:
        """Remove a specific memory by id. Returns True if found and removed."""
        before = len(self._records)
        self._records = [r for r in self._records if r.identifier != identifier]
        if len(self._records) < before:
            self._save()
            return True
        return False

    def clear(self, tier: str | None = None) -> int:
        """Remove all memories (or all of a given tier). Returns count removed."""
        if tier is None:
            count = len(self._records)
            self._records = []
        else:
            before = len(self._records)
            self._records = [r for r in self._records if r.tier != tier]
            count = before - len(self._records)
        if count > 0:
            self._save()
        return count

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = [
                MemoryRecord(
                    identifier=int(item["identifier"]),
                    content=str(item["content"]),
                    created_at=str(item["created_at"]),
                    tier=str(item.get("tier", "long_term")),
                )
                for item in payload
                if isinstance(item, dict)
            ][-self.max_items :]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self._records = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps([asdict(record) for record in self._records], indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)
