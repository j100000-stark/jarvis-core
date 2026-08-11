"""Proposal-only self-improvement workflow."""

from __future__ import annotations

from ..memory import MemoryStore
from .brain import Brain
from .code_agent import CodeAgent, CodeAgentResult
from .models import ExecutionReport, ImprovementProposal


class SelfImprovementManager:
    """Generate improvement proposals and require explicit approval to apply."""

    def __init__(
        self,
        brain: Brain,
        memory: MemoryStore,
        code_agent: CodeAgent,
    ) -> None:
        self.brain = brain
        self.memory = memory
        self.code_agent = code_agent

    def propose(self, report: ExecutionReport) -> ImprovementProposal:
        context = tuple(record.content for record in self.memory.search(report.goal))
        return self.brain.propose_improvement(report, context)

    def apply(
        self, proposal: ImprovementProposal, *, approved: bool = False
    ) -> CodeAgentResult:
        if not approved:
            raise PermissionError(
                "Self-improvement is proposal-only until a human explicitly approves it."
            )
        allowed_files = tuple(change.path for change in proposal.changes)
        return self.code_agent.apply_changes(
            proposal.rationale,
            proposal.changes,
            allowed_files,
        )
