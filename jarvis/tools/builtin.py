"""Built-in tools that do not require external APIs.

All tools must be safe, deterministic, and local-only.  Tool names are the
only surface the LLM is allowed to reference — it cannot call anything not
registered here.

V1 tools registered by build_default_registry():
  echo            — return text unchanged
  time            — current UTC time
  remember        — store a long-term memory
  recall          — search long-term memory
  system_status   — runtime status without subprocess
  network_status  — TCP probe of public DNS hosts
  calculate       — safe AST math evaluator
  analyze_text    — word/sentence/keyword statistics
  web_research    — safe HTTP fetch (gated by settings.web_research_enabled)
  security_status — safety boundary summary
  report          — format a timestamped structured report
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..agent.models import PlanStep, ToolResult
from .extended import build_extended_registry_additions
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
    """Store a fact in persistent long-term memory.

    Registered as the ``remember`` tool so the LLM can use it in plans.
    All storage goes through MemoryStore — no file system access beyond what
    MemoryStore already permits.
    """

    name = "remember"
    description = "Store a fact in long-term memory: remember <fact>."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        if not argument.strip():
            return ToolResult(ok=False, error="Usage: remember <fact>")
        record = context.memory.remember(argument.strip(), tier="long_term")
        return ToolResult(
            ok=True,
            output=f"Stored memory #{record.identifier}: {argument.strip()}",
        )

    def verify(self, result: ToolResult, step: PlanStep) -> bool:
        del step
        return result.ok


class RecallTool:
    """Search persistent long-term memory.

    Registered as the ``recall`` tool so the LLM can retrieve facts it stored
    in earlier turns (names, preferences, past goals, etc.).
    """

    name = "recall"
    description = "Search long-term memories: recall <query>."

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        records = context.memory.search(argument.strip(), tier="long_term")
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
    """Create the V1 default tool set.

    Registers core tools (echo, time, remember, recall) plus all V1 extended
    tools (system_status, network_status, calculate, analyze_text,
    web_research, security_status, report).
    """
    registry = ToolRegistry()
    # Core tools
    registry.register(TimeTool())
    registry.register(EchoTool())
    registry.register(RememberTool())
    registry.register(RecallTool())
    # V1 extended tools
    for tool in build_extended_registry_additions():
        registry.register(tool)
    return registry
