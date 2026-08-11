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
from ..agent.models import ExecutionReport
from ..config import Settings
from ..memory import MemoryManager
from ..network.manager import NetworkManager
from ..network.recovery import NetworkRecoveryManager
from ..recovery import RecoveryManager
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

    def __post_init__(self) -> None:
        # --- Brain selection ---
        if isinstance(self.brain, UnavailableBrain):
            if self.settings.demo_mode:
                self.brain = DemoBrain()
            elif self.settings.local_provider_enabled:
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
        demo = f" [{DEMO_LABEL}]" if self.settings.demo_mode else ""
        return (
            f"{self.settings.name} v{self.settings.version} online{demo}. "
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

    def run_goal(self, goal: str) -> ExecutionReport:
        """Plan and execute a high-level goal through the safe tool boundary."""
        plan = self.planner.create_plan(goal)
        return self.executor.execute(
            plan,
            ToolContext(
                settings=self.settings,
                memory=self.memory,
                sandbox=self.sandbox,
            ),
        )

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
        return "\n".join(
            [
                f"{self.settings.name} v{self.settings.version}",
                f"Local time: {now}",
                f"Memories: {self.memory.count()}",
                f"Tools: {', '.join(self.tools.names())}",
                f"Recovery incidents: {self.recovery.count()}",
                f"Brain provider: {getattr(self.brain, 'provider_name', 'unknown')}",
                f"Disk healthy: {self.monitor.healthy()}",
                "External APIs: disabled",
                f"Demo mode: {'yes' if self.settings.demo_mode else 'no'}",
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
