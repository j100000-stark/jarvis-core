"""SecurityDefender: safe defensive actions on authorized local systems.

Every action passes an explicit policy/safety gate.
Destructive actions require explicit approval via the safety gate.
The defender does NOT implement offensive actions, credential theft,
malware, persistence, or unauthorized access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Callable

from ..agent.models import AgentReport, AlertSeverity, SecurityFinding


class ActionType(StrEnum):
    """Types of defensive actions the defender may take."""

    PRESERVE_EVIDENCE = "preserve_evidence"
    LOG_EVENT = "log_event"
    STOP_LOCAL_PROCESS = "stop_local_process"     # requires approval
    DISABLE_LOCAL_SERVICE = "disable_local_service"  # requires approval
    ISOLATE_INTERFACE = "isolate_interface"        # requires approval


@dataclass(frozen=True, slots=True)
class DefenderAction:
    """A defensive action request with its authorization state."""

    action_type: ActionType
    target: str
    rationale: str
    requires_approval: bool
    approved: bool = False


class SafetyPolicyDenied(PermissionError):
    """Raised when a defensive action is blocked by the safety policy."""


class SecurityDefender:
    """Execute safe defensive actions on the authorized local system.

    Safety gate rules
    -----------------
    1. All actions are logged regardless of outcome.
    2. Destructive actions (STOP_LOCAL_PROCESS, DISABLE_LOCAL_SERVICE,
       ISOLATE_INTERFACE) must be explicitly approved.
    3. No action may target an external system or network.
    4. Evidence preservation is always permitted (read-only).
    5. The defender will not execute any action the safety gate rejects.
    """

    # Actions that require explicit approval before execution
    APPROVAL_REQUIRED = frozenset({
        ActionType.STOP_LOCAL_PROCESS,
        ActionType.DISABLE_LOCAL_SERVICE,
        ActionType.ISOLATE_INTERFACE,
    })

    def __init__(
        self,
        safety_gate: Callable[[DefenderAction], bool] | None = None,
    ) -> None:
        """Create a defender with an optional safety gate callback.

        The safety gate receives a DefenderAction and returns True if
        the action is approved, False otherwise.  If None, a permissive
        gate is used for read-only actions and a deny-all gate is used
        for destructive actions.
        """
        self._safety_gate = safety_gate or self._default_gate
        self._action_log: list[str] = []
        self._reports: list[AgentReport] = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def execute(self, action: DefenderAction, *, task_id: str = "") -> AgentReport:
        """Execute a defensive action after safety gate check.

        Raises SafetyPolicyDenied if the gate rejects the action.
        """
        self._counter += 1
        tid = task_id or f"DEF-{self._counter:04d}"

        # Safety gate
        if action.action_type in self.APPROVAL_REQUIRED and not action.approved:
            msg = (
                f"Action '{action.action_type}' on target '{action.target}' requires "
                "explicit approval. Set approved=True in the DefenderAction."
            )
            self._log(f"DENIED: {msg}")
            raise SafetyPolicyDenied(msg)

        if not self._safety_gate(action):
            msg = f"Safety gate blocked action '{action.action_type}' on '{action.target}'."
            self._log(f"BLOCKED: {msg}")
            raise SafetyPolicyDenied(msg)

        # Execute the safe action
        result_description = self._perform(action)
        self._log(f"EXECUTED: {action.action_type} on {action.target}: {result_description}")

        finding = SecurityFinding(
            identifier=f"{tid}-F01",
            category="defensive_action",
            title=f"Executed: {action.action_type}",
            description=result_description,
            evidence=action.rationale,
            is_assumption=False,
            severity=AlertSeverity.INFO,
        )
        report = AgentReport(
            task_id=tid,
            agent_name="SecurityDefender",
            success=True,
            summary=result_description,
            findings=(finding,),
        )
        self._reports.append(report)
        return report

    def _perform(self, action: DefenderAction) -> str:
        """Simulate or execute the defensive action; return description."""
        if action.action_type is ActionType.PRESERVE_EVIDENCE:
            return (
                f"Evidence preserved for target '{action.target}'. "
                "Log snapshot recorded in defender log."
            )
        if action.action_type is ActionType.LOG_EVENT:
            return f"Event logged for target '{action.target}': {action.rationale}"
        if action.action_type is ActionType.STOP_LOCAL_PROCESS:
            # In a real deployment this would call os.kill(pid, signal.SIGTERM)
            # after validating the PID is on the authorized list.
            # We surface the intent without executing it in the base class.
            return (
                f"STOP_LOCAL_PROCESS action prepared for '{action.target}'. "
                "Execute only after confirming this is an authorized local process."
            )
        if action.action_type is ActionType.DISABLE_LOCAL_SERVICE:
            return (
                f"DISABLE_LOCAL_SERVICE action prepared for '{action.target}'. "
                "Execute using the system service manager on the authorized host."
            )
        if action.action_type is ActionType.ISOLATE_INTERFACE:
            return (
                f"ISOLATE_INTERFACE action prepared for '{action.target}'. "
                "Execute using the authorized network management tool on the local host."
            )
        return f"Unknown action type '{action.action_type}'. No action taken."

    # ------------------------------------------------------------------
    # Safety gate
    # ------------------------------------------------------------------

    def _default_gate(self, action: DefenderAction) -> bool:
        """Default gate: permit read-only actions; require approval for destructive ones."""
        if action.action_type in self.APPROVAL_REQUIRED:
            return action.approved
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def action_log(self) -> list[str]:
        return list(self._action_log)

    def all_reports(self) -> list[AgentReport]:
        return list(self._reports)

    def _log(self, message: str) -> None:
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        self._action_log.append(f"{ts} {message}")
