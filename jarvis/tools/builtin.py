"""Built-in tools that do not require external APIs.

All tools must be safe, deterministic, and local-only.  Tool names are the
only surface the LLM is allowed to reference — it cannot call anything not
registered here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..agent.models import PlanStep, ToolResult
from .registry import Tool, ToolContext, ToolRegistry


class TimeTool:
    name = "time"
    description = "Show the current UTC time."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del argument, context
        return ToolResult(ok=True, output=datetime.now(UTC).isoformat(timespec="seconds"))

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return bool(result.output)


class EchoTool:
    name = "echo"
    description = "Return text unchanged: echo <text>."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del context
        if not argument:
            return ToolResult(ok=False, error="Usage: echo <text>")
        return ToolResult(ok=True, output=argument)

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok and bool(result.output)


class RememberTool:
    """Store a fact in persistent local memory.

    Registered as the ``remember`` tool so the LLM can use it in plans.
    All storage goes through MemoryStore — no file system access beyond what
    MemoryStore already permits.
    """

    name = "remember"
    description = "Store a fact in local memory: remember <fact>."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        if not argument.strip():
            return ToolResult(ok=False, error="Usage: remember <fact>")
        record = context.memory.remember(argument.strip())
        return ToolResult(
            ok=True,
            output=f"Stored memory #{record.identifier}: {argument.strip()}",
        )

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok


class RecallTool:
    """Search persistent local memory.

    Registered as the ``recall`` tool so the LLM can retrieve facts it stored
    in earlier turns (names, preferences, past goals, etc.).
    """

    name = "recall"
    description = "Search local memories: recall <query>."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        records = context.memory.search(argument.strip())
        if not records:
            return ToolResult(ok=True, output="No matching memories found.")
        lines = "\n".join(
            f"#{r.identifier}: {r.content}" for r in records
        )
        return ToolResult(ok=True, output=lines)

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok


def build_default_registry() -> ToolRegistry:
    """Create the V0.1 tool set."""
    registry = ToolRegistry()
    registry.register(TimeTool())
    registry.register(EchoTool())
    registry.register(RememberTool())
    registry.register(RecallTool())
    return registry
