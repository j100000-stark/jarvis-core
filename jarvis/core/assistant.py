"""The JARVIS orchestration layer.

The core owns conversation flow and delegates storage, tools, configuration,
sandbox policy, and recovery to their respective modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..config import Settings
from ..memory import MemoryStore
from ..recovery import RecoveryManager
from ..sandbox import Sandbox
from ..tools import ToolContext, ToolRegistry, build_default_registry


@dataclass(slots=True)
class Assistant:
    """Coordinate JARVIS capabilities without coupling them together."""

    settings: Settings
    memory: MemoryStore = field(init=False)
    sandbox: Sandbox = field(init=False)
    recovery: RecoveryManager = field(init=False)
    tools: ToolRegistry = field(init=False)

    def __post_init__(self) -> None:
        self.memory = MemoryStore(
            self.settings.memory_file,
            max_items=self.settings.max_memory_items,
        )
        self.sandbox = Sandbox(
            workspace_root=self.settings.data_dir.parent,
            timeout_seconds=self.settings.sandbox_timeout_seconds,
        )
        self.recovery = RecoveryManager()
        self.tools: ToolRegistry = build_default_registry()

    def startup_message(self) -> str:
        """Return a concise session greeting."""
        return (
            f"{self.settings.name} v{self.settings.version} online. "
            "Type 'help' for commands or 'exit' to leave."
        )

    def respond(self, message: str) -> str:
        """Process one user message and return a human-readable response."""
        normalized = message.strip()
        if not normalized:
            return "I need a message to work with."

        try:
            if normalized.lower() == "help":
                return self.tools.help_text()
            if normalized.lower() == "status":
                return self.status_text()
            if normalized.lower().startswith("remember "):
                value = normalized[9:].strip()
                if not value:
                    return "Tell me what you would like me to remember."
                record = self.memory.remember(value)
                return f"Stored memory #{record.identifier}."
            if normalized.lower().startswith("recall"):
                query = normalized[6:].strip()
                records = self.memory.search(query)
                if not records:
                    return "I could not find any matching memories."
                return "\n".join(
                    f"#{record.identifier} — {record.content}" for record in records
                )

            tool_name, _, argument = normalized.partition(" ")
            tool = self.tools.get(tool_name)
            if tool is not None:
                context = ToolContext(
                    settings=self.settings,
                    memory=self.memory,
                    sandbox=self.sandbox,
                )
                return tool.run(argument.strip(), context)

            return (
                "I am ready for a local command. Try 'help', 'remember <fact>', "
                "'recall', 'time', or 'status'."
            )
        except Exception as error:
            incident = self.recovery.record(error, operation="respond")
            return (
                f"I hit a recoverable error ({incident.identifier}). "
                "The incident was recorded locally."
            )

    def status_text(self) -> str:
        """Describe the current local runtime state."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        return "\n".join(
            [
                f"{self.settings.name} v{self.settings.version}",
                f"Local time: {now}",
                f"Memories: {self.memory.count()}",
                f"Tools: {', '.join(self.tools.names())}",
                f"Recovery incidents: {self.recovery.count()}",
                "External APIs: disabled",
            ]
        )
