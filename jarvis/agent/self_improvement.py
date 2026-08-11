"""Proposal-only self-improvement workflow with capability request gating."""

from __future__ import annotations

import uuid

from ..memory import MemoryStore
from .brain import Brain
from .code_agent import CodeAgent, CodeAgentResult
from .models import CapabilityRequest, ExecutionReport, ImprovementProposal


class SelfImprovementManager:
    """Generate improvement proposals and require explicit approval to apply.

    New capabilities that require additional privileges generate an explicit
    CapabilityRequest instead of silently expanding permissions.
    """

    def __init__(
        self,
        brain: Brain,
        memory: MemoryStore,
        code_agent: CodeAgent,
    ) -> None:
        self.brain = brain
        self.memory = memory
        self.code_agent = code_agent
        self._capability_requests: list[CapabilityRequest] = []

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

    # ------------------------------------------------------------------
    # Capability requests
    # ------------------------------------------------------------------

    def request_capability(
        self,
        title: str,
        rationale: str,
        requested_capability: str,
        risk_level: str = "medium",
    ) -> CapabilityRequest:
        """Create a capability request that must be approved before granting.

        New privileges are NEVER silently self-granted.  The request is
        recorded and must be explicitly approved by the operator.
        """
        from .models import AlertSeverity

        try:
            severity = AlertSeverity(risk_level.lower())
        except ValueError:
            severity = AlertSeverity.MEDIUM

        request = CapabilityRequest(
            request_id=str(uuid.uuid4())[:8],
            title=title,
            rationale=rationale,
            requested_capability=requested_capability,
            risk_level=severity,
            approved=False,
        )
        self._capability_requests.append(request)
        return request

    def approve_capability(self, request_id: str) -> CapabilityRequest | None:
        """Return a new approved CapabilityRequest, or None if not found."""
        for i, req in enumerate(self._capability_requests):
            if req.request_id == request_id:
                approved = CapabilityRequest(
                    request_id=req.request_id,
                    title=req.title,
                    rationale=req.rationale,
                    requested_capability=req.requested_capability,
                    risk_level=req.risk_level,
                    approved=True,
                )
                self._capability_requests[i] = approved
                return approved
        return None

    def pending_capability_requests(self) -> list[CapabilityRequest]:
        """Return all unapproved capability requests."""
        return [r for r in self._capability_requests if not r.approved]

    def all_capability_requests(self) -> list[CapabilityRequest]:
        return list(self._capability_requests)
