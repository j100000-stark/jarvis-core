"""SecurityCommander: coordinate defensive security agents toward a goal.

The commander receives a high-level defensive goal, selects appropriate
agents, orchestrates their execution, and produces a unified report.

No offensive capabilities, no external network access, no credential
handling.  All actions pass through individual agent safety gates.
"""

from __future__ import annotations

from ..agent.models import AgentReport, AgentTask, AlertSeverity, SecurityFinding
from .defender import SecurityDefender
from .investigator import SecurityInvestigator
from .sentinel import SecuritySentinel
from .test_agent import SecurityTestAgent


class SecurityCommander:
    """Coordinate SecuritySentinel → SecurityInvestigator → SecurityDefender.

    Orchestration flow:
      1. Sentinel collects current system events.
      2. Investigator correlates events into findings.
      3. (Optional) TestAgent runs a posture check on an authorized target.
      4. Defender logs or preserves evidence based on severity.
      5. Commander produces a unified report.
    """

    def __init__(
        self,
        sentinel: SecuritySentinel | None = None,
        investigator: SecurityInvestigator | None = None,
        defender: SecurityDefender | None = None,
        test_agent: SecurityTestAgent | None = None,
    ) -> None:
        self.sentinel = sentinel or SecuritySentinel()
        self.investigator = investigator or SecurityInvestigator()
        self.defender = defender or SecurityDefender()
        self.test_agent = test_agent or SecurityTestAgent()
        self._reports: list[AgentReport] = []
        self._counter = 0

    def run(
        self,
        goal: str,
        *,
        include_posture_check: bool = False,
        authorized_target: str | None = None,
    ) -> AgentReport:
        """Execute a full defensive security assessment for the given goal.

        Parameters
        ----------
        goal:
            High-level defensive goal (e.g. "Check whether my computer is
            behaving normally.").
        include_posture_check:
            Whether to run SecurityTestAgent against an authorized target.
        authorized_target:
            Required when include_posture_check=True.

        Returns a unified AgentReport with all findings and alerts.
        """
        self._counter += 1
        cmd_id = f"CMD-{self._counter:04d}"

        all_findings: list[SecurityFinding] = []
        sub_reports: list[AgentReport] = []

        # --- Step 1: Sentinel collection ---
        events = self.sentinel.collect_process_snapshot()
        events += self.sentinel.collect_network_interfaces()
        sentinel_alerts = self.sentinel.detect_anomalies()

        # --- Step 2: Investigation ---
        inv_report = self.investigator.investigate(
            task_id=f"{cmd_id}-INV",
            events=events,
            alerts=sentinel_alerts,
            goal=goal,
        )
        sub_reports.append(inv_report)
        all_findings.extend(inv_report.findings)

        # --- Step 3: Optional posture check ---
        if include_posture_check:
            if authorized_target:
                self.test_agent.authorize_target(authorized_target)
            if self.test_agent.is_authorized():
                test_report = self.test_agent.run_posture_check(
                    task_id=f"{cmd_id}-TEST"
                )
                sub_reports.append(test_report)
                all_findings.extend(test_report.findings)

        # --- Step 4: Defender evidence preservation ---
        from .defender import ActionType, DefenderAction

        preserve_action = DefenderAction(
            action_type=ActionType.PRESERVE_EVIDENCE,
            target="security_assessment_log",
            rationale=f"Commander assessment for goal: {goal}",
            requires_approval=False,
        )
        try:
            def_report = self.defender.execute(preserve_action, task_id=f"{cmd_id}-DEF")
            sub_reports.append(def_report)
        except Exception as exc:
            all_findings.append(
                SecurityFinding(
                    identifier=f"{cmd_id}-DEF-ERR",
                    category="defender",
                    title="Evidence preservation failed",
                    description=str(exc),
                    is_assumption=False,
                    severity=AlertSeverity.LOW,
                )
            )

        # --- Step 5: Unified summary ---
        critical = [f for f in all_findings if f.severity == AlertSeverity.CRITICAL]
        high = [f for f in all_findings if f.severity == AlertSeverity.HIGH]
        summary = (
            f"Security assessment for goal: '{goal}'. "
            f"{len(all_findings)} finding(s) total; "
            f"{len(critical)} critical, {len(high)} high. "
            f"Agents used: sentinel, investigator"
            + (", test_agent" if include_posture_check and self.test_agent.is_authorized() else "")
            + ", defender."
        )

        report = AgentReport(
            task_id=cmd_id,
            agent_name="SecurityCommander",
            success=True,
            summary=summary,
            findings=tuple(all_findings),
            alerts=tuple(sentinel_alerts),
            raw_data={
                "goal": goal,
                "sub_report_ids": ",".join(r.task_id for r in sub_reports),
            },
        )
        self._reports.append(report)
        return report

    def all_reports(self) -> list[AgentReport]:
        return list(self._reports)
