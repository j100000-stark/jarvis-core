"""Local recovery state for graceful failure handling."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Incident:
    """A recoverable error captured during assistant operation."""

    identifier: int
    operation: str
    error_type: str
    message: str
    created_at: str
    trace: str


class RecoveryManager:
    """Keep an in-memory incident log and provide a stable incident ID."""

    def __init__(self) -> None:
        self._incidents: list[Incident] = []

    def record(self, error: Exception, operation: str) -> Incident:
        incident = Incident(
            identifier=len(self._incidents) + 1,
            operation=operation,
            error_type=type(error).__name__,
            message=str(error),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            trace="".join(traceback.format_exception(error)),
        )
        self._incidents.append(incident)
        return incident

    def count(self) -> int:
        return len(self._incidents)

    def latest(self) -> Incident | None:
        return self._incidents[-1] if self._incidents else None
