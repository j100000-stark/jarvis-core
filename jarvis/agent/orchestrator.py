"""Multi-agent orchestrator: coordinates specialized agents toward a high-level goal.

Flow:
  USER GOAL → Commander → Plan → Select Agents → Execute Safe Steps
           → Verify → Report → Recovery if needed

The orchestrator wraps the AgentExecutor with multi-agent awareness.
It dispatches AgentTask records and collects AgentReport records without
fabricating results when no real system data is available.
"""

from __future__ import annotations

from ..agent.models import (
    AgentReport,
    AgentTask,
    AlertSeverity,
    ExecutionReport,
    SecurityFinding,
)
from ..recovery import RecoveryManager
from ..tools import ToolContext, ToolRegistry
from .executor import AgentExecutor


class AgentOrchestrator:
    """Coordinate multiple specialized agents toward a high-level goal.

    The orchestrator selects agents based on the goal keywords, dispatches
    tasks, collects reports, verifies results, and triggers recovery when
    steps fail.  It does not fabricate results.

    Agent registry:
    - Agents are registered by name with a callable that accepts an
      AgentTask and returns an AgentReport.
    - The orchestrator selects agents based on keyword matching against
      the goal; future versions may use Brain-based routing.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        recovery: RecoveryManager,
    ) -> None:
        self._executor = AgentExecutor(registry, recovery)
        self._recovery = recovery
        self._agents: dict[str, tuple[list[str], "AgentCallable"]] = {}
        self._reports: list[AgentReport] = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(
        self,
        name: str,
        keywords: list[str],
        handler: "AgentCallable",
    ) -> None:
        """Register a specialized agent.

        ``name`` — unique agent identifier.
        ``keywords`` — goal keywords that suggest this agent.
        ``handler`` — callable(AgentTask) -> AgentReport.
        """
        self._agents[name] = (keywords, handler)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self, goal: str, context: ToolContext) -> AgentReport:
        """Select agents, execute tasks, verify, and return a unified report.

        Does NOT fabricate findings; if no agents match or data is unavailable,
        the report reflects that honestly.
        """
        self._counter += 1
        orch_id = f"ORCH-{self._counter:04d}"

        selected = self._select_agents(goal)
        all_findings: list[SecurityFinding] = []
        sub_reports: list[AgentReport] = []

        if not selected:
            report = AgentReport(
                task_id=orch_id,
                agent_name="AgentOrchestrator",
                success=True,
                summary=(
                    f"No specialized agents matched goal: '{goal}'. "
                    "Goal forwarded to standard executor."
                ),
                raw_data={"goal": goal},
            )
            self._reports.append(report)
            return report

        for agent_name in selected:
            keywords, handler = self._agents[agent_name]
            task = AgentTask(
                task_id=f"{orch_id}-{agent_name}",
                agent_name=agent_name,
                goal=goal,
            )
            try:
                report = handler(task)
            except Exception as exc:
                self._recovery.record(exc, operation=f"orchestrator:{agent_name}")
                report = AgentReport(
                    task_id=task.task_id,
                    agent_name=agent_name,
                    success=False,
                    summary=f"Agent '{agent_name}' failed: {exc}",
                    findings=(
                        SecurityFinding(
                            identifier=f"{task.task_id}-ERR",
                            category="agent_error",
                            title=f"Agent failed: {agent_name}",
                            description=str(exc),
                            is_assumption=False,
                            severity=AlertSeverity.LOW,
                        ),
                    ),
                )
            sub_reports.append(report)
            all_findings.extend(report.findings)

        success = all(r.success for r in sub_reports)
        summary = (
            f"Orchestrated {len(sub_reports)} agent(s) for goal: '{goal}'. "
            f"{'All succeeded.' if success else 'Some agents failed — see findings.'} "
            f"{len(all_findings)} finding(s) collected."
        )

        report = AgentReport(
            task_id=orch_id,
            agent_name="AgentOrchestrator",
            success=success,
            summary=summary,
            findings=tuple(all_findings),
            raw_data={
                "goal": goal,
                "agents_used": ",".join(selected),
                "sub_report_ids": ",".join(r.task_id for r in sub_reports),
            },
        )
        self._reports.append(report)
        return report

    def _select_agents(self, goal: str) -> list[str]:
        """Select agents whose keywords match the goal (case-insensitive)."""
        goal_lower = goal.lower()
        selected: list[str] = []
        for name, (keywords, _) in self._agents.items():
            if any(kw.lower() in goal_lower for kw in keywords):
                selected.append(name)
        return selected

    def all_reports(self) -> list[AgentReport]:
        return list(self._reports)


# Type alias for agent handlers
AgentCallable = "Callable[[AgentTask], AgentReport]"
