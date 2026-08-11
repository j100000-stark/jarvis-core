"""Small JSON-backed memory store for V0.1."""

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


class MemoryStore:
    """Store memories locally without a database or external service."""

    def __init__(self, path: Path, max_items: int = 100) -> None:
        self.path = path
        self.max_items = max_items
        self._records: list[MemoryRecord] = []
        self._load()

    def remember(self, content: str) -> MemoryRecord:
        """Persist a new memory and return it."""
        cleaned = " ".join(content.split())
        if not cleaned:
            raise ValueError("Memory content cannot be empty.")

        next_id = max((record.identifier for record in self._records), default=0) + 1
        record = MemoryRecord(
            identifier=next_id,
            content=cleaned,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._records.append(record)
        self._records = self._records[-self.max_items :]
        self._save()
        return record

    def search(self, query: str = "") -> list[MemoryRecord]:
        """Return newest matching records, or all records for an empty query."""
        normalized = query.casefold().strip()
        matching = (
            record
            for record in reversed(self._records)
            if not normalized or normalized in record.content.casefold()
        )
        return list(matching)

    def count(self) -> int:
        return len(self._records)

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
