"""Built-in tools that do not require external APIs."""

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


def build_default_registry() -> ToolRegistry:
    """Create the V0.1 tool set."""
    registry = ToolRegistry()
    registry.register(TimeTool())
    registry.register(EchoTool())
    return registry
