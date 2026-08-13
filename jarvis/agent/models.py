"""Shared domain models for autonomous execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class StepStatus(StrEnum):
    """Lifecycle state for one planned step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One tool invocation and its expected verification condition."""

    identifier: str
    objective: str
    tool_name: str
    argument: str = ""
    verification: str = ""
    max_retries: int = 0


@dataclass(frozen=True, slots=True)
class Plan:
    """A brain-produced plan for a high-level goal."""

    goal: str
    steps: tuple[PlanStep, ...]
    provider: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A truthful tool outcome; success is never inferred from text."""

    ok: bool
    output: str = ""
    error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepReport:
    """Execution and verification details for one plan step."""

    step: PlanStep
    status: StepStatus
    attempts: int
    result: ToolResult
    verified: bool


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """Complete outcome of executing a plan."""

    goal: str
    success: bool
    steps: tuple[StepReport, ...]
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class CodeGenerationRequest:
    """Context passed to a brain when code changes are needed."""

    goal: str
    allowed_files: tuple[str, ...]
    existing_files: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CodeChange:
    """A complete replacement for one restricted Python file."""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    """A proposed improvement that requires explicit approval to apply."""

    title: str
    rationale: str
    changes: tuple[CodeChange, ...]
    provider: str


# ---------------------------------------------------------------------------
# Resilience models
# ---------------------------------------------------------------------------


class ServiceState(StrEnum):
    """Lifecycle states for a supervised service."""

    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"
    CRASH_LOOP = "crash_loop"


@dataclass(frozen=True, slots=True)
class RecoveryIncident:
    """Record of a crash or recovery event."""

    identifier: str
    service_name: str
    reason: str
    restart_count: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    resolved: bool = False


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Point-in-time health snapshot for JARVIS or one of its components."""

    component: str
    healthy: bool
    state: str
    details: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


# ---------------------------------------------------------------------------
# Network models
# ---------------------------------------------------------------------------


class NetworkConnectivity(StrEnum):
    """Observable network connectivity states."""

    # UNKNOWN means no live probe has run yet — never report OFFLINE
    # merely because connectivity was not measured (spec: truthful status).
    UNKNOWN = "unknown"
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    LOCAL_ONLY = "local_only"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class NetworkState:
    """Current network connectivity state with diagnostics."""

    connectivity: NetworkConnectivity
    reachable_hosts: tuple[str, ...] = ()
    unreachable_hosts: tuple[str, ...] = ()
    details: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


# ---------------------------------------------------------------------------
# Security models
# ---------------------------------------------------------------------------


class AlertSeverity(StrEnum):
    """Severity levels for security alerts (defensive only)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    """A raw observable event on the local authorized system."""

    event_type: str
    source: str
    description: str
    raw_data: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


@dataclass(frozen=True, slots=True)
class SecurityAlert:
    """A structured defensive alert produced by SecuritySentinel."""

    identifier: str
    severity: AlertSeverity
    title: str
    description: str
    events: tuple[SecurityEvent, ...] = ()
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """Result of a security test or investigation (no exploitation)."""

    identifier: str
    category: str
    title: str
    description: str
    evidence: str = ""
    is_assumption: bool = False
    remediation: str = ""
    severity: AlertSeverity = AlertSeverity.INFO


# ---------------------------------------------------------------------------
# Multi-agent orchestration models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentTask:
    """A unit of work dispatched to a specialized agent."""

    task_id: str
    agent_name: str
    goal: str
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentReport:
    """The outcome produced by a specialized agent."""

    task_id: str
    agent_name: str
    success: bool
    summary: str
    findings: tuple[SecurityFinding, ...] = ()
    alerts: tuple[SecurityAlert, ...] = ()
    raw_data: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


# ---------------------------------------------------------------------------
# Self-improvement safety
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    """Explicit request for a new privilege or capability; requires approval."""

    request_id: str
    title: str
    rationale: str
    requested_capability: str
    risk_level: AlertSeverity = AlertSeverity.MEDIUM
    approved: bool = False
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
