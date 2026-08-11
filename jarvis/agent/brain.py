"""AI provider and intelligence-engine contracts.

No provider is bundled in V0.1. A future Raspberry Pi provider can implement
``AIProvider`` around a local model and be injected through ``ProviderBrain``.
The default ``UnavailableBrain`` fails explicitly instead of inventing plans,
code, or answers.
"""

from __future__ import annotations

from typing import Protocol

from .models import (
    CodeChange,
    CodeGenerationRequest,
    ExecutionReport,
    ImprovementProposal,
    Plan,
)


class BrainError(RuntimeError):
    """Base error for intelligence-engine failures."""


class BrainUnavailableError(BrainError):
    """Raised when no actual intelligence provider has been configured."""


class AIProvider(Protocol):
    """Structured provider contract suitable for a local LLM adapter."""

    name: str

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        """Create a structured plan from a high-level goal."""
        ...

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        """Generate complete file changes for the restricted code workspace."""
        ...

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        """Propose an improvement based on observed execution."""
        ...


class Brain(Protocol):
    """Intelligence engine used by the planner and code agent."""

    @property
    def provider_name(self) -> str:
        ...

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        ...

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        ...

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        ...


class ProviderBrain:
    """Adapt one structured AI provider to the JARVIS brain interface."""

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        return self.provider.create_plan(goal, memory_context)

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        return self.provider.generate_code(request)

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        return self.provider.propose_improvement(report, memory_context)


class UnavailableBrain:
    """Honest default used until a real local or remote provider is injected."""

    provider_name = "unconfigured"

    def _raise(self) -> None:
        raise BrainUnavailableError(
            "No AI provider is configured. Inject a local AIProvider before "
            "running autonomous planning or code generation."
        )

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        del goal, memory_context
        self._raise()

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        del request
        self._raise()

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        del report, memory_context
        self._raise()
