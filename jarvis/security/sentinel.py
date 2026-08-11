"""SecuritySentinel: monitor authorized local system events and detect anomalies.

Monitoring is strictly read-only and covers only the local authorized system.
No external network scanning or unauthorized process interaction is performed.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..agent.models import AlertSeverity, SecurityAlert, SecurityEvent


_SENTINEL_VERSION = "0.1"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SecuritySentinel:
    """Read-only monitor for the authorized local system.

    Collects:
    - Process/service state (via /proc or platform APIs where available)
    - Local network interface state (via socket/platform APIs)
    - Anomaly detection based on simple heuristics on collected data

    Does NOT: scan external hosts, exploit vulnerabilities, intercept
    traffic, or access credentials.
    """

    def __init__(self, authorized_pids: frozenset[int] | None = None) -> None:
        self._authorized_pids = authorized_pids or frozenset()
        self._events: list[SecurityEvent] = []
        self._alerts: list[SecurityAlert] = []
        self._alert_counter = 0

    # ------------------------------------------------------------------
    # Event collection
    # ------------------------------------------------------------------

    def collect_process_snapshot(self) -> list[SecurityEvent]:
        """Collect a snapshot of running process IDs from the local system.

        Returns a list of SecurityEvent records describing the process state.
        Only reads from /proc (Linux) or uses os.getpid()/ppid (all platforms).
        """
        events: list[SecurityEvent] = []
        try:
            pids = self._read_pids()
            events.append(
                SecurityEvent(
                    event_type="process_snapshot",
                    source="sentinel.process",
                    description=f"Observed {len(pids)} running processes on local system.",
                    raw_data=f"pids_count={len(pids)};platform={platform.system()}",
                )
            )
        except Exception as exc:
            events.append(
                SecurityEvent(
                    event_type="process_snapshot_error",
                    source="sentinel.process",
                    description=f"Could not read process list: {exc}",
                )
            )
        self._events.extend(events)
        return events

    def collect_network_interfaces(self) -> list[SecurityEvent]:
        """Read local network interface names (read-only, no packets sent)."""
        events: list[SecurityEvent] = []
        try:
            import socket

            hostname = socket.gethostname()
            try:
                addrs = socket.getaddrinfo(hostname, None)
                unique = {a[4][0] for a in addrs}
            except Exception:
                unique = set()

            events.append(
                SecurityEvent(
                    event_type="network_interface_snapshot",
                    source="sentinel.network",
                    description=f"Local hostname: {hostname}; addresses observed: {len(unique)}",
                    raw_data=f"hostname={hostname};addr_count={len(unique)}",
                )
            )
        except Exception as exc:
            events.append(
                SecurityEvent(
                    event_type="network_interface_error",
                    source="sentinel.network",
                    description=f"Could not read network interfaces: {exc}",
                )
            )
        self._events.extend(events)
        return events

    def detect_anomalies(self) -> list[SecurityAlert]:
        """Apply simple heuristics to collected events to detect anomalies.

        Currently detects:
        - Unusually high process count (> 500 on a local system)
        - Any collection errors

        Returns newly created SecurityAlert records.
        """
        new_alerts: list[SecurityAlert] = []
        for event in self._events:
            alert = self._evaluate_event(event)
            if alert:
                new_alerts.append(alert)
                self._alerts.append(alert)
        return new_alerts

    def _evaluate_event(self, event: SecurityEvent) -> SecurityAlert | None:
        if "error" in event.event_type:
            self._alert_counter += 1
            return SecurityAlert(
                identifier=f"SENT-{self._alert_counter:04d}",
                severity=AlertSeverity.LOW,
                title="Monitoring collection error",
                description=event.description,
                events=(event,),
            )
        if event.event_type == "process_snapshot":
            try:
                raw = dict(kv.split("=", 1) for kv in event.raw_data.split(";") if "=" in kv)
                count = int(raw.get("pids_count", "0"))
                if count > 500:
                    self._alert_counter += 1
                    return SecurityAlert(
                        identifier=f"SENT-{self._alert_counter:04d}",
                        severity=AlertSeverity.MEDIUM,
                        title="Unusually high process count",
                        description=f"Observed {count} processes (threshold: 500).",
                        events=(event,),
                    )
            except Exception:
                pass
        return None

    def _read_pids(self) -> list[int]:
        """Read running PIDs from /proc (Linux) or return [current_pid]."""
        proc = "/proc"
        if os.path.isdir(proc):
            return [
                int(entry)
                for entry in os.listdir(proc)
                if entry.isdigit()
            ]
        return [os.getpid()]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_events(self) -> list[SecurityEvent]:
        return list(self._events)

    def all_alerts(self) -> list[SecurityAlert]:
        return list(self._alerts)

    def clear_events(self) -> None:
        """Clear collected events (alerts are retained)."""
        self._events.clear()
