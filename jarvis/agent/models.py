"""Shared domain models for autonomous execution."""

from __future__ import annotations

from dataclasses import dataclass, field
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
