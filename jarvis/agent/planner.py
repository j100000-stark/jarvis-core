"""Goal-to-plan orchestration."""

from __future__ import annotations

from ..memory import MemoryStore
from .brain import Brain
from .models import Plan


class Planner:
    """Ask the configured brain for a validated, executable plan."""

    def __init__(self, brain: Brain, memory: MemoryStore) -> None:
        self.brain = brain
        self.memory = memory

    def create_plan(self, goal: str) -> Plan:
        """Create a plan using relevant local memory as context."""
        cleaned_goal = " ".join(goal.split())
        if not cleaned_goal:
            raise ValueError("A high-level goal cannot be empty.")

        # Query-matched memories first; when nothing matches (e.g. the goal is
        # in a different language than the stored fact), fall back to the most
        # recent memories so the brain still sees known facts.
        matched = self.memory.search(cleaned_goal)
        context = matched if matched else self.memory.recent(limit=8)
        plan = self.brain.create_plan(
            cleaned_goal,
            tuple(record.content for record in context),
        )
        self._validate(plan, cleaned_goal)
        return plan

    @staticmethod
    def _validate(plan: Plan, goal: str) -> None:
        if plan.goal != goal:
            raise ValueError("Brain returned a plan for a different goal.")
        if not plan.provider:
            raise ValueError("Brain returned a plan without a provider name.")
        identifiers = [step.identifier for step in plan.steps]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Plan step identifiers must be unique.")
        for step in plan.steps:
            if not step.identifier or not step.objective or not step.tool_name:
                raise ValueError("Every plan step needs an ID, objective, and tool.")
            if step.max_retries < 0:
                raise ValueError("Plan retry limits cannot be negative.")
