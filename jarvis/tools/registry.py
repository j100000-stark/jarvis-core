"""Registry and context objects for JARVIS tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..config import Settings
from ..memory import MemoryStore
from ..sandbox import Sandbox


@dataclass(slots=True)
class ToolContext:
    """Dependencies explicitly available to a tool."""

    settings: Settings
    memory: MemoryStore
    sandbox: Sandbox


class Tool(Protocol):
    """Protocol implemented by every assistant tool."""

    name: str
    description: str

    def run(self, argument: str, context: ToolContext) -> str:
        ...


class ToolRegistry:
    """Map safe, local tool names to their implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name.casefold())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def help_text(self) -> str:
        lines = ["Available commands:"]
        lines.extend(
            f"  {name:<10} {self._tools[name].description}" for name in self.names()
        )
        lines.extend(
            [
                "  remember   Save a local memory: remember <fact>",
                "  recall     Search local memories: recall [query]",
                "  status     Show runtime and module status",
                "  help       Show this list",
            ]
        )
        return "\n".join(lines)
