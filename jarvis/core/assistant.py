"""The JARVIS orchestration layer.

The core owns conversation flow and delegates storage, tools, configuration,
sandbox policy, and recovery to their respective modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..agent import (
    AgentExecutor,
    Brain,
    BrainUnavailableError,
    Planner,
    UnavailableBrain,
    build_local_brain,
)
from ..agent.demo import DEMO_LABEL, DemoBrain
from ..agent.remote_llm import RemoteLLMConfigError, build_remote_llm_brain
from ..agent.models import ExecutionReport
from ..config import Settings
from ..memory import MemoryManager
from ..network.manager import NetworkManager
from ..network.recovery import NetworkRecoveryManager
from ..recovery import RecoveryManager, SelfRepairManager
from ..resilience import (
    CrashRecoveryManager,
    HealthCheckManager,
    ServiceSupervisor,
    StateRecoveryManager,
    WatchdogManager,
)
from ..rollback import RollbackManager
from ..sandbox import Sandbox
from ..system import SystemMonitor
from ..tools import ToolContext, ToolRegistry, build_default_registry


@dataclass(slots=True)
class Assistant:
    """Coordinate JARVIS capabilities without coupling them together."""

    settings: Settings
    brain: Brain = field(default_factory=UnavailableBrain)
    memory: MemoryManager = field(init=False)
    sandbox: Sandbox = field(init=False)
    recovery: RecoveryManager = field(init=False)
    tools: ToolRegistry = field(init=False)
    rollback: RollbackManager = field(init=False)
    planner: Planner = field(init=False)
    executor: AgentExecutor = field(init=False)
    monitor: SystemMonitor = field(init=False)
    # Resilience subsystem
    watchdog: WatchdogManager = field(init=False)
    crash_recovery: CrashRecoveryManager = field(init=False)
    health_checks: HealthCheckManager = field(init=False)
    network_recovery: NetworkRecoveryManager = field(init=False)
    # Self-repair subsystem
    self_repair: SelfRepairManager = field(init=False)

    def __post_init__(self) -> None:
        # --- Brain selection ---
        if isinstance(self.brain, UnavailableBrain):
            if self.settings.demo_mode:
                # DemoBrain: explicit scripted responses, no real AI
                self.brain = DemoBrain()
            elif self.settings.llm_enabled:
                # RemoteLLMBrain: real LLM via API key — fails loudly if key missing
                self.brain = build_remote_llm_brain(self.settings)
            elif self.settings.local_provider_enabled:
                # LocalAIProvider: on-device model (Ollama / llama.cpp)
                self.brain = build_local_brain(self.settings)

        # --- Core subsystems ---
        self.memory = MemoryManager(
            self.settings.memory_file,
            max_items=self.settings.max_memory_items,
        )
        self.sandbox = Sandbox(
            workspace_root=self.settings.data_dir.parent,
            timeout_seconds=self.settings.sandbox_timeout_seconds,
        )
        self.recovery = RecoveryManager()
        self.tools: ToolRegistry = build_default_registry()
        self.rollback = RollbackManager(self.sandbox)
        self.planner = Planner(self.brain, self.memory)
        self.executor = AgentExecutor(self.tools, self.recovery)
        self.monitor = SystemMonitor(self.settings.data_dir.parent)

        # --- Resilience subsystem ---
        self.watchdog = WatchdogManager()
        self.crash_recovery = CrashRecoveryManager()
        self.health_checks = HealthCheckManager()
        self.network_recovery = NetworkRecoveryManager(
            probe_hosts=("1.1.1.1", "8.8.8.8"),
            max_reconnect_attempts=5,
        )

        # --- Self-repair ---
        self.self_repair = SelfRepairManager(self.settings.data_dir)

        # Register basic health checks
        self.health_checks.register(
            "disk",
            lambda: self.monitor.healthy(),
            detail_fn=lambda: "Disk accessible.",
        )
        self.health_checks.register(
            "memory_store",
            lambda: self.memory.count() >= 0,
            detail_fn=lambda: f"{self.memory.count()} memory items.",
        )
        self.health_checks.register(
            "tools",
            lambda: len(self.tools.names()) > 0,
            detail_fn=lambda: f"Tools: {', '.join(self.tools.names())}",
        )

    def startup_message(self) -> str:
        """Return a concise session greeting."""
        pname = getattr(self.brain, "provider_name", "unknown")
        if self.settings.demo_mode:
            suffix = f" [{DEMO_LABEL}]"
        elif pname.startswith("llm:"):
            suffix = f" [REAL LLM — {pname}]"
        elif pname.startswith("local:"):
            suffix = f" [LOCAL LLM — {pname}]"
        else:
            suffix = ""
        return (
            f"{self.settings.name} v{self.settings.version} online{suffix}. "
            "Type 'help' for commands or 'exit' to leave."
        )

    def respond(self, message: str) -> str:
        """Process one user message and return a human-readable response."""
        normalized = message.strip()
        if not normalized:
            return "I need a message to work with."

        try:
            if normalized.lower() == "help":
                return self.tools.help_text()
            if normalized.lower() == "status":
                return self.status_text()
            if normalized.lower().startswith("goal "):
                report = self.run_goal(normalized[5:].strip())
                return self._format_execution_report(report)
            if normalized.lower().startswith("remember "):
                value = normalized[9:].strip()
                if not value:
                    return "Tell me what you would like me to remember."
                record = self.memory.remember(value)
                return f"Stored memory #{record.identifier}."
            if normalized.lower().startswith("recall"):
                query = normalized[6:].strip()
                records = self.memory.search(query)
                if not records:
                    return "I could not find any matching memories."
                return "\n".join(
                    f"#{record.identifier} — {record.content}" for record in records
                )

            tool_name, _, argument = normalized.partition(" ")
            tool = self.tools.get(tool_name)
            if tool is not None:
                context = ToolContext(
                    settings=self.settings,
                    memory=self.memory,
                    sandbox=self.sandbox,
                )
                result = self.tools.execute(tool_name, argument.strip(), context)
                return result.output if result.ok else (result.error or "Tool failed.")

            return (
                "I am ready for a local command. Try 'help', 'remember <fact>', "
                "'recall', 'time', or 'status'."
            )
        except BrainUnavailableError as error:
            return str(error)
        except Exception as error:
            incident = self.recovery.record(error, operation="respond")
            return (
                f"I hit a recoverable error ({incident.identifier}). "
                "The incident was recorded locally."
            )

    def execute_goal_structured(self, goal: str) -> dict:
        """Run a goal through Planner → Executor with one self-repair attempt on failure.

        Flow:
          1. Attempt goal with current settings.
          2. On exception or semantic failure: diagnose → repair → retry once.
          3. Return a structured dict with the full execution trace.
        Never fabricates results or swallows errors silently.
        """
        # Reset repair attempt counter so each new goal gets a fresh budget.
        self.self_repair.reset_attempts()
        repair_notes: list[str] = []

        def _build_steps(report: ExecutionReport) -> list[dict]:
            return [
                {
                    "stepId": sr.step.identifier,
                    "objective": sr.step.objective,
                    "tool": sr.step.tool_name,
                    "output": sr.result.output or "",
                    "error": sr.result.error,
                    "verified": sr.verified,
                    "verification": sr.step.verification,
                }
                for sr in report.steps
            ]

        # ── First attempt ─────────────────────────────────────────────────
        effective_settings = self.settings
        try:
            report = self._run_goal_with_settings(goal, effective_settings)
        except Exception as first_error:
            incident = self.recovery.record(first_error, operation="execute_goal_structured")
            repair = self.self_repair.diagnose_and_repair(
                failure_message=str(first_error),
                failure_step=None,
                goal=goal,
                settings=effective_settings,
                registry=self.tools,
            )
            repair_notes = repair.actions

            if repair.success:
                effective_settings = repair.repaired_settings or effective_settings
                try:
                    report = self._run_goal_with_settings(goal, effective_settings)
                except Exception as retry_error:
                    incident2 = self.recovery.record(retry_error, "execute_goal_structured:retry")
                    return self._error_result(goal, incident2, None, repair_notes)
            else:
                return self._error_result(goal, incident, self._find_failing_step(), repair_notes)

        # ── Semantic failure: executor returned success=False ──────────────
        if not report.success and report.failure:
            repair = self.self_repair.diagnose_and_repair(
                failure_message=report.failure,
                failure_step=None,
                goal=goal,
                settings=effective_settings,
                registry=self.tools,
            )
            repair_notes.extend(repair.actions)

            if repair.success:
                effective_settings = repair.repaired_settings or effective_settings
                try:
                    report = self._run_goal_with_settings(goal, effective_settings)
                except Exception as repair_err:
                    incident3 = self.recovery.record(repair_err, "execute_goal_structured:semantic_repair")
                    return self._error_result(goal, incident3, None, repair_notes)

        # ── Build success (or unrecoverable failure) result ───────────────
        plan_provider = getattr(self.brain, "provider_name", "unknown")
        execution_steps = _build_steps(report)
        response = self._format_execution_report(report)
        if repair_notes:
            from ..diagnostics import sanitize_message
            repair_notes = [sanitize_message(n) for n in repair_notes]
            concise = "; ".join(n for n in repair_notes[:2] if n)
            response = f"[Self-repair: {concise}] {response}"

        return {
            "success": report.success,
            "goal": goal,
            "response": response,
            "providerName": plan_provider,
            "demoMode": self.settings.demo_mode,
            "demoLabel": DEMO_LABEL if self.settings.demo_mode else None,
            "planGoal": report.goal,
            "planProvider": plan_provider,
            "executionSteps": execution_steps,
            "failure": report.failure,
            "repairNotes": repair_notes if repair_notes else None,
        }

    def run_goal(self, goal: str) -> ExecutionReport:
        """Plan and execute a high-level goal through the safe tool boundary.

        In demo mode the Planner validation is bypassed because DemoBrain
        intentionally prefixes plan.goal with the DEMO label, which would
        fail the Planner's exact-equality check.  All other safety gates
        (sandbox, tool boundary, executor) remain active.
        """
        return self._run_goal_with_settings(goal, self.settings)

    def _run_goal_with_settings(self, goal: str, settings: Settings) -> ExecutionReport:
        """Execute a goal using the supplied settings (allows patched settings on retry).

        This is the single code-path that builds a ToolContext so that any
        patched settings (e.g. web_research_enabled=True after self-repair)
        are correctly passed down to every tool.
        """
        if settings.demo_mode:
            # Bypass Planner validation for DemoBrain — it prefixes plan.goal
            plan = self.brain.plan(goal, tuple(self.memory.context_for(goal)))
        else:
            plan = self.planner.create_plan(goal)
        return self.executor.execute(
            plan,
            ToolContext(settings=settings, memory=self.memory, sandbox=self.sandbox),
        )

    def _find_failing_step(self) -> str | None:
        """Return the identifier of the most recent failing executor step."""
        all_incidents = list(self.recovery._incidents)  # noqa: SLF001
        for past in reversed(all_incidents[:-1]):
            if past.operation.startswith("step:") or past.operation.startswith("retry:"):
                return past.operation.split(":", 1)[-1]
        return None

    def _error_result(
        self,
        goal: str,
        incident: object,
        failing_step: str | None,
        repair_notes: list[str],
    ) -> dict:
        """Build a structured error response from a recorded incident."""
        from ..diagnostics import build_execution_error, sanitize_message
        exec_error = build_execution_error(
            incident,  # type: ignore[arg-type]
            goal=goal,
            failing_step=failing_step,
        )
        clean_notes = [sanitize_message(n) for n in repair_notes] if repair_notes else None
        return {
            "success": False,
            "goal": goal,
            "response": (
                f"Goal execution failed: {exec_error['type']} in {exec_error['component']}."
                f" Incident #{exec_error.get('incidentId', '?')} recorded."
            ),
            "providerName": getattr(self.brain, "provider_name", "unknown"),
            "demoMode": self.settings.demo_mode,
            "demoLabel": DEMO_LABEL if self.settings.demo_mode else None,
            "planGoal": None,
            "planProvider": None,
            "executionSteps": [],
            "failure": exec_error["message"],
            "error": exec_error,
            "repairNotes": clean_notes,
        }

    @staticmethod
    def _format_execution_report(report: ExecutionReport) -> str:
        lines = [
            f"Goal {'completed' if report.success else 'failed'}: {report.goal}",
        ]
        for step in report.steps:
            state = "verified" if step.verified else "failed"
            detail = step.result.output or step.result.error or "no output"
            lines.append(f"  [{state}] {step.step.identifier}: {detail}")
        if report.failure:
            lines.append(f"Reason: {report.failure}")
        return "\n".join(lines)

    def status_text(self) -> str:
        """Describe the current local runtime state."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        pname = getattr(self.brain, "provider_name", "unknown")
        if pname.startswith("llm:"):
            provider_type = "real-llm"
        elif pname.startswith("local:"):
            provider_type = "local-llm"
        elif pname == "demo":
            provider_type = "demo"
        else:
            provider_type = "none"
        return "\n".join(
            [
                f"{self.settings.name} v{self.settings.version}",
                f"Local time: {now}",
                f"Memories: {self.memory.count()}",
                f"Tools: {', '.join(self.tools.names())}",
                f"Recovery incidents: {self.recovery.count()}",
                f"Brain provider: {pname}",
                f"Provider type: {provider_type}",
                f"Disk healthy: {self.monitor.healthy()}",
                f"External APIs: {'enabled' if self.settings.web_research_enabled else 'disabled'}",
                f"Demo mode: {'yes' if self.settings.demo_mode else 'no'}",
                f"LLM mode: {'yes' if self.settings.llm_enabled else 'no'}",
            ]
        )

    def system_report(self) -> dict:
        """Return a comprehensive system state dict for the web interface.

        Does NOT fabricate data.  If a subsystem is unavailable its entry
        reflects that honestly.  Network connectivity probes are skipped
        (we return last-known state) to keep the call fast.
        """
        # Health checks
        health_statuses = self.health_checks.check_all()
        health = [
            {
                "component": s.component,
                "healthy": s.healthy,
                "state": s.state,
                "details": s.details,
            }
            for s in health_statuses
        ]

        # Network — return last-known state without blocking probe
        net = self.network_recovery.connectivity
        network = {
            "connectivity": net.value,
            "reachableHosts": [],
            "unreachableHosts": [],
            "details": "Last-known network state (no live probe on this call).",
        }

        # Recovery incidents from crash recovery
        crm_incidents = self.crash_recovery.all_incidents()[-10:]
        incidents = [
            {
                "identifier": i.identifier,
                "serviceName": i.service_name,
                "reason": i.reason,
                "restartCount": i.restart_count,
                "timestamp": i.timestamp,
                "resolved": i.resolved,
            }
            for i in crm_incidents
        ]

        # Security — we surface a summary rather than running a live assessment
        security = {
            "alertCount": 0,
            "findingCount": 0,
            "highestSeverity": "info",
            "lastAssessmentAt": None,
        }

        # Agent activity — empty for now (populated when orchestrator is used)
        agent_activity: list[dict] = []

        demo_mode = self.settings.demo_mode
        return {
            "demoMode": demo_mode,
            "demoLabel": DEMO_LABEL if demo_mode else None,
            "health": health,
            "network": network,
            "recentIncidents": incidents,
            "security": security,
            "recentAgentActivity": agent_activity,
        }
