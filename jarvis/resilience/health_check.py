"""Health check manager: aggregate component health into HealthStatus records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..agent.models import HealthStatus


@dataclass
class _HealthCheck:
    name: str
    check: Callable[[], bool]
    detail_fn: Callable[[], str] | None = None


class HealthCheckManager:
    """Run registered health checks and produce HealthStatus snapshots.

    Health checks are callable predicates.  A check that raises is
    treated as unhealthy; the exception message becomes the detail.
    """

    def __init__(self) -> None:
        self._checks: dict[str, _HealthCheck] = {}

    def register(
        self,
        name: str,
        check: Callable[[], bool],
        detail_fn: Callable[[], str] | None = None,
    ) -> None:
        """Register a health check.

        ``check`` — returns True when the component is healthy.
        ``detail_fn`` — optional callable that returns a detail string.
        """
        self._checks[name] = _HealthCheck(name=name, check=check, detail_fn=detail_fn)

    def check(self, name: str) -> HealthStatus:
        """Run a single named health check and return its status."""
        entry = self._checks.get(name)
        if entry is None:
            return HealthStatus(
                component=name,
                healthy=False,
                state="unknown",
                details="No health check registered for this component.",
            )
        return self._run(entry)

    def check_all(self) -> list[HealthStatus]:
        """Run all registered checks and return a list of statuses."""
        return [self._run(entry) for entry in self._checks.values()]

    def all_healthy(self) -> bool:
        """Return True only if every registered check passes."""
        return all(self._run(entry).healthy for entry in self._checks.values())

    def _run(self, entry: _HealthCheck) -> HealthStatus:
        try:
            healthy = entry.check()
            detail = entry.detail_fn() if entry.detail_fn else ""
            state = "healthy" if healthy else "unhealthy"
        except Exception as exc:
            healthy = False
            state = "error"
            detail = str(exc)
        return HealthStatus(
            component=entry.name,
            healthy=healthy,
            state=state,
            details=detail,
        )

    def registered_names(self) -> list[str]:
        return list(self._checks.keys())
