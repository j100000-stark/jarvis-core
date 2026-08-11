"""Built-in tools that do not require external APIs."""

from __future__ import annotations

from datetime import UTC, datetime

from .registry import Tool, ToolContext, ToolRegistry


class TimeTool:
    name = "time"
    description = "Show the current UTC time."

    def run(self, argument: str, context: ToolContext) -> str:
        del argument, context
        return datetime.now(UTC).isoformat(timespec="seconds")


class EchoTool:
    name = "echo"
    description = "Return text unchanged: echo <text>."

    def run(self, argument: str, context: ToolContext) -> str:
        del context
        return argument or "Usage: echo <text>"


def build_default_registry() -> ToolRegistry:
    """Create the V0.1 tool set."""
    registry = ToolRegistry()
    registry.register(TimeTool())
    registry.register(EchoTool())
    return registry
