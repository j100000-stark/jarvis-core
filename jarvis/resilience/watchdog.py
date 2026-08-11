"""Watchdog: detects unexpected service failures and triggers recovery."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..agent.models import RecoveryIncident, ServiceState


@dataclass
class _WatchedService:
    name: str
    check: Callable[[], bool]
    state: ServiceState = ServiceState.RUNNING
    failure_count: int = 0
    last_checked: float = field(default_factory=time.monotonic)


class WatchdogManager:
    """Monitor registered services and detect unexpected failures.

    The watchdog does NOT spawn processes — it calls cooperative check
    callables and records failures.  Restarts are delegated to
    ServiceSupervisor to avoid recursive process spawning.
    """

    # A service with this many consecutive failures in one poll cycle
    # is marked as CRASH_LOOP.
    CRASH_LOOP_THRESHOLD = 5

    def __init__(self) -> None:
        self._services: dict[str, _WatchedService] = {}
        self._incidents: list[RecoveryIncident] = []
        self._incident_counter = 0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, check: Callable[[], bool]) -> None:
        """Register a service with a liveness check callable."""
        self._services[name] = _WatchedService(name=name, check=check)

    def deregister(self, name: str) -> None:
        """Remove a service from watchdog monitoring."""
        self._services.pop(name, None)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def poll(self) -> list[RecoveryIncident]:
        """Run all liveness checks and return newly created incidents."""
        new_incidents: list[RecoveryIncident] = []
        for service in self._services.values():
            try:
                alive = service.check()
            except Exception as exc:
                alive = False
                self._record_incident(
                    service, f"Check raised exception: {exc}", new_incidents
                )
                continue

            if alive:
                service.state = ServiceState.RUNNING
                service.failure_count = 0
            else:
                self._record_incident(
                    service, "Liveness check returned False.", new_incidents
                )

        return new_incidents

    def _record_incident(
        self,
        service: _WatchedService,
        reason: str,
        collector: list[RecoveryIncident],
    ) -> None:
        service.failure_count += 1
        if service.failure_count >= self.CRASH_LOOP_THRESHOLD:
            service.state = ServiceState.CRASH_LOOP
        else:
            service.state = ServiceState.FAILED

        self._incident_counter += 1
        incident = RecoveryIncident(
            identifier=f"WD-{self._incident_counter:04d}",
            service_name=service.name,
            reason=reason,
            restart_count=service.failure_count,
        )
        self._incidents.append(incident)
        collector.append(incident)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def state_of(self, name: str) -> ServiceState | None:
        """Return the current state of a registered service, or None."""
        service = self._services.get(name)
        return service.state if service else None

    def all_incidents(self) -> list[RecoveryIncident]:
        """Return all recorded incidents (defensive copy)."""
        return list(self._incidents)

    def in_crash_loop(self, name: str) -> bool:
        """Return True if the named service is in a detected crash loop."""
        state = self.state_of(name)
        return state is ServiceState.CRASH_LOOP

    def service_names(self) -> list[str]:
        """Return the names of all registered services."""
        return list(self._services.keys())

    def healthy_services(self) -> list[str]:
        """Return names of services currently in RUNNING state."""
        return [
            name
            for name, svc in self._services.items()
            if svc.state is ServiceState.RUNNING
        ]
