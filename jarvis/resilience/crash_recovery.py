"""Crash recovery: records incidents, manages restart budgets, detects loops."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..agent.models import RecoveryIncident, ServiceState


@dataclass
class _ServiceBudget:
    name: str
    max_restarts: int
    restart_count: int = 0
    last_failure_time: float = field(default_factory=time.monotonic)
    # Consecutive failures within this many seconds count toward loop detection
    loop_window_seconds: float = 60.0
    state: ServiceState = ServiceState.RUNNING


class CrashRecoveryManager:
    """Track crash history, enforce restart budgets, and detect crash loops.

    Restart budgets prevent JARVIS from spawning processes indefinitely.
    Crash loops are detected when a service fails more than
    max_restarts times within the configured time window.
    """

    def __init__(self, default_max_restarts: int = 3) -> None:
        self._default_max_restarts = default_max_restarts
        self._budgets: dict[str, _ServiceBudget] = {}
        self._incidents: list[RecoveryIncident] = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_service(
        self,
        name: str,
        max_restarts: int | None = None,
        loop_window_seconds: float = 60.0,
    ) -> None:
        """Register a service with a restart budget."""
        self._budgets[name] = _ServiceBudget(
            name=name,
            max_restarts=max_restarts if max_restarts is not None else self._default_max_restarts,
            loop_window_seconds=loop_window_seconds,
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_failure(self, service_name: str, reason: str) -> RecoveryIncident:
        """Record a failure for the named service and return an incident.

        If the service is not registered it is auto-registered with defaults.
        """
        if service_name not in self._budgets:
            self.register_service(service_name)

        budget = self._budgets[service_name]
        now = time.monotonic()

        # Reset count if outside the loop window
        if now - budget.last_failure_time > budget.loop_window_seconds:
            budget.restart_count = 0

        budget.restart_count += 1
        budget.last_failure_time = now

        if budget.restart_count > budget.max_restarts:
            budget.state = ServiceState.CRASH_LOOP
        else:
            budget.state = ServiceState.FAILED

        self._counter += 1
        incident = RecoveryIncident(
            identifier=f"CR-{self._counter:04d}",
            service_name=service_name,
            reason=reason,
            restart_count=budget.restart_count,
        )
        self._incidents.append(incident)
        return incident

    def record_recovery(self, service_name: str) -> None:
        """Mark a service as recovered (resets crash-loop state)."""
        if service_name in self._budgets:
            budget = self._budgets[service_name]
            budget.state = ServiceState.RUNNING
            budget.restart_count = 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def can_restart(self, service_name: str) -> bool:
        """Return True if the service is within its restart budget."""
        budget = self._budgets.get(service_name)
        if budget is None:
            return True  # Unknown services get one attempt
        return budget.restart_count <= budget.max_restarts

    def in_crash_loop(self, service_name: str) -> bool:
        """Return True if the service has exhausted its restart budget."""
        budget = self._budgets.get(service_name)
        return budget is not None and budget.state is ServiceState.CRASH_LOOP

    def state_of(self, service_name: str) -> ServiceState | None:
        budget = self._budgets.get(service_name)
        return budget.state if budget else None

    def all_incidents(self) -> list[RecoveryIncident]:
        return list(self._incidents)

    def incidents_for(self, service_name: str) -> list[RecoveryIncident]:
        return [i for i in self._incidents if i.service_name == service_name]

    def restart_count(self, service_name: str) -> int:
        budget = self._budgets.get(service_name)
        return budget.restart_count if budget else 0
