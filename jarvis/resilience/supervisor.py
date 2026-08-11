"""Service supervisor: bounded restarts with exponential back-off.

The supervisor does NOT fork processes.  It calls registered factory
callables that re-initialize the service object, which keeps the
implementation testable without touching the real OS process table.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..agent.models import RecoveryIncident, ServiceState
from .crash_recovery import CrashRecoveryManager


@dataclass
class _SupervisedEntry:
    name: str
    factory: Callable[[], Any]
    instance: Any
    max_restarts: int
    base_backoff_seconds: float
    restart_count: int = 0
    state: ServiceState = ServiceState.RUNNING


class ServiceSupervisor:
    """Supervise named service objects with bounded restarts and backoff.

    The upper bound on restarts prevents runaway loops.
    Backoff is computed as: base * 2^(attempt-1), capped at 60 s.
    """

    MAX_BACKOFF_SECONDS = 60.0

    def __init__(self, crash_recovery: CrashRecoveryManager | None = None) -> None:
        self._services: dict[str, _SupervisedEntry] = {}
        self._incidents: list[RecoveryIncident] = []
        self._counter = 0
        self._crash_recovery = crash_recovery or CrashRecoveryManager()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def supervise(
        self,
        name: str,
        factory: Callable[[], Any],
        *,
        max_restarts: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        """Register a service factory and create the initial instance."""
        instance = factory()
        self._services[name] = _SupervisedEntry(
            name=name,
            factory=factory,
            instance=instance,
            max_restarts=max_restarts,
            base_backoff_seconds=base_backoff_seconds,
        )
        self._crash_recovery.register_service(name, max_restarts=max_restarts)

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------

    def restart(self, name: str, reason: str = "supervisor restart") -> RecoveryIncident:
        """Attempt to restart a named service.

        Records an incident regardless of outcome.  Raises RuntimeError
        if the service has exhausted its restart budget (crash loop).

        Budget is enforced by the supervisor's own per-entry restart_count so
        that successful restarts do not inadvertently reset the loop detector.
        """
        entry = self._services.get(name)
        if entry is None:
            raise KeyError(f"No supervised service named '{name}'.")

        # Enforce the budget using the supervisor's own counter (not the CRM
        # counter, which is reset on each successful recovery).
        if entry.restart_count >= entry.max_restarts:
            entry.state = ServiceState.CRASH_LOOP
            incident = self._crash_recovery.record_failure(
                name, "Crash loop: restart budget exhausted."
            )
            self._incidents.append(incident)
            raise RuntimeError(
                f"Service '{name}' is in a crash loop and will not be restarted."
            )

        incident = self._crash_recovery.record_failure(name, reason)
        entry.restart_count += 1

        backoff = min(
            entry.base_backoff_seconds * math.pow(2, entry.restart_count - 1),
            self.MAX_BACKOFF_SECONDS,
        )
        entry.state = ServiceState.RESTARTING
        self._sleep(backoff)

        try:
            entry.instance = entry.factory()
            entry.state = ServiceState.RUNNING
        except Exception as exc:
            entry.state = ServiceState.FAILED
            incident = self._crash_recovery.record_failure(
                name, f"Factory raised: {exc}"
            )

        self._incidents.append(incident)
        return incident

    # Seam for tests to override without touching real clock
    def _sleep(self, seconds: float) -> None:  # pragma: no cover
        time.sleep(seconds)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, name: str) -> Any | None:
        entry = self._services.get(name)
        return entry.instance if entry else None

    def state_of(self, name: str) -> ServiceState | None:
        entry = self._services.get(name)
        return entry.state if entry else None

    def all_incidents(self) -> list[RecoveryIncident]:
        return list(self._incidents)

    def service_names(self) -> list[str]:
        return list(self._services.keys())
