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
        """Persist a memory and return it — upsert on exact content match.

        If a record with identical normalised content already exists in the
        same tier, its timestamp is refreshed and it is returned without
        creating a duplicate entry.  This prevents the memory file from
        accumulating hundreds of identical facts across sessions.
        """
        cleaned = " ".join(content.split())
        if not cleaned:
            raise ValueError("Memory content cannot be empty.")

        # Upsert: refresh timestamp of an existing identical record in this tier.
        normalized = cleaned.casefold()
        for idx, existing in enumerate(self._records):
            if existing.tier == tier and existing.content.casefold() == normalized:
                updated = MemoryRecord(
                    identifier=existing.identifier,
                    content=cleaned,
                    created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    tier=tier,
                )
                self._records[idx] = updated
                self._save()
                return updated

        next_id = max((record.identifier for record in self._records), default=0) + 1
        record = MemoryRecord(
            identifier=next_id,
            content=cleaned,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            tier=tier,
        )
        self._records.append(record)
        if self.max_items > 0:
            self._records = self._records[-self.max_items :]
        self._save()
        return record

    def search(self, query: str = "", tier: str | None = None) -> list[MemoryRecord]:
        """Return newest matching records, optionally filtered by tier.

        Matching is tolerant: a record matches when the full query is a
        substring OR any query token (≥3 chars) appears in the content.
        This lets natural-language questions ("Come mi chiamo?") hit records
        stored as statements ("User's name is Sandeep") when they share words,
        instead of requiring an exact phrase match.
        """
        normalized = query.casefold().strip()
        tokens = [t for t in normalized.split() if len(t) >= 3]

        def matches(content: str) -> bool:
            if not normalized:
                return True
            folded = content.casefold()
            if normalized in folded:
                return True
            return any(token in folded for token in tokens)

        matching = (
            record
            for record in reversed(self._records)
            if (tier is None or record.tier == tier) and matches(record.content)
        )
        return list(matching)

    def recent(self, limit: int = 8, tier: str | None = None) -> list[MemoryRecord]:
        """Return the newest records regardless of query match."""
        records = [
            r for r in reversed(self._records) if tier is None or r.tier == tier
        ]
        return records[:limit]

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
