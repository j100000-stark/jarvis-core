"""SecurityInvestigator: correlate events, build timeline, assign risk level.

Clearly distinguishes evidence (observed data) from assumptions (inferred).
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..agent.models import (
    AgentReport,
    AlertSeverity,
    SecurityAlert,
    SecurityEvent,
    SecurityFinding,
)


class SecurityInvestigator:
    """Analyze collected security events and produce structured findings.

    All findings explicitly state whether each claim is evidence or assumption.
    The investigator never fabricates data: if no events are available it
    reports that clearly instead of inventing a threat picture.
    """

    def __init__(self) -> None:
        self._investigations: list[AgentReport] = []
        self._counter = 0

    def investigate(
        self,
        task_id: str,
        events: list[SecurityEvent],
        alerts: list[SecurityAlert],
        *,
        goal: str = "Analyze local security events",
    ) -> AgentReport:
        """Correlate events and alerts into a structured investigation report."""
        findings: list[SecurityFinding] = []
        self._counter += 1

        if not events and not alerts:
            findings.append(
                SecurityFinding(
                    identifier=f"INV-{self._counter:04d}-NA",
                    category="data_availability",
                    title="No events available for analysis",
                    description=(
                        "No security events or alerts were provided to the investigator. "
                        "A meaningful investigation cannot be conducted without data."
                    ),
                    is_assumption=False,
                    severity=AlertSeverity.INFO,
                )
            )
            report = AgentReport(
                task_id=task_id,
                agent_name="SecurityInvestigator",
                success=True,
                summary="No events available. Investigation returned empty.",
                findings=tuple(findings),
            )
            self._investigations.append(report)
            return report

        # Build timeline
        timeline = self._build_timeline(events, alerts)

        # Assess risk
        risk = self._assess_risk(alerts)

        # Produce findings — one per alert, with clear evidence/assumption labelling
        for idx, alert in enumerate(alerts, start=1):
            findings.append(
                SecurityFinding(
                    identifier=f"INV-{self._counter:04d}-{idx:02d}",
                    category=alert.severity.value,
                    title=alert.title,
                    description=alert.description,
                    evidence="; ".join(e.description for e in alert.events),
                    is_assumption=False,  # Derived from observed sentinel events
                    severity=alert.severity,
                    remediation=self._suggest_remediation(alert),
                )
            )

        summary = (
            f"Investigated {len(events)} events and {len(alerts)} alerts. "
            f"Overall risk: {risk.value}. "
            f"Timeline spans {len(timeline)} entries."
        )

        report = AgentReport(
            task_id=task_id,
            agent_name="SecurityInvestigator",
            success=True,
            summary=summary,
            findings=tuple(findings),
            alerts=tuple(alerts),
            raw_data={"timeline": "\n".join(timeline), "risk_level": risk.value},
        )
        self._investigations.append(report)
        return report

    def _build_timeline(
        self, events: list[SecurityEvent], alerts: list[SecurityAlert]
    ) -> list[str]:
        entries: list[tuple[str, str]] = []
        for e in events:
            entries.append((e.timestamp, f"[EVENT] {e.event_type}: {e.description}"))
        for a in alerts:
            entries.append((a.timestamp, f"[ALERT/{a.severity.upper()}] {a.title}: {a.description}"))
        entries.sort(key=lambda x: x[0])
        return [f"{ts} — {desc}" for ts, desc in entries]

    def _assess_risk(self, alerts: list[SecurityAlert]) -> AlertSeverity:
        if not alerts:
            return AlertSeverity.INFO
        levels = {
            AlertSeverity.INFO: 0,
            AlertSeverity.LOW: 1,
            AlertSeverity.MEDIUM: 2,
            AlertSeverity.HIGH: 3,
            AlertSeverity.CRITICAL: 4,
        }
        max_level = max(levels.get(a.severity, 0) for a in alerts)
        for sev, lvl in levels.items():
            if lvl == max_level:
                return sev
        return AlertSeverity.INFO

    def _suggest_remediation(self, alert: SecurityAlert) -> str:
        mapping = {
            AlertSeverity.CRITICAL: "Immediately isolate affected component and investigate manually.",
            AlertSeverity.HIGH: "Review and address within the current session.",
            AlertSeverity.MEDIUM: "Schedule review; monitor for escalation.",
            AlertSeverity.LOW: "Log and monitor; no immediate action required.",
            AlertSeverity.INFO: "No action required.",
        }
        return mapping.get(alert.severity, "Review findings manually.")

    def all_reports(self) -> list[AgentReport]:
        return list(self._investigations)
