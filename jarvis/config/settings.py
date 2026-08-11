"""Environment-backed configuration for JARVIS.

V0.1 deliberately has no external-service configuration. The settings object
keeps runtime choices centralized so future integrations do not leak into the
assistant core.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings with safe, local-only defaults."""

    name: str = "JARVIS"
    version: str = "0.1.0"
    data_dir: Path = Path("data")
    memory_file: Path = Path("data/memory.json")
    max_memory_items: int = 100
    sandbox_timeout_seconds: float = 2.0
    autonomous_max_retries: int = 1

    @classmethod
    def from_environment(cls, memory_file: str | None = None) -> "Settings":
        """Create settings from environment variables and CLI overrides."""
        data_dir = Path(os.getenv("JARVIS_DATA_DIR", "data"))
        configured_memory = memory_file or os.getenv("JARVIS_MEMORY_FILE")
        resolved_memory = Path(configured_memory) if configured_memory else data_dir / "memory.json"
        return cls(
            name=os.getenv("JARVIS_NAME", "JARVIS"),
            version=os.getenv("JARVIS_VERSION", "0.1.0"),
            data_dir=data_dir,
            memory_file=resolved_memory,
            max_memory_items=_positive_int(
                os.getenv("JARVIS_MAX_MEMORY_ITEMS"), default=100
            ),
            sandbox_timeout_seconds=_positive_float(
                os.getenv("JARVIS_SANDBOX_TIMEOUT"), default=2.0
            ),
            autonomous_max_retries=_positive_int(
                os.getenv("JARVIS_AUTONOMOUS_MAX_RETRIES"), default=1
            ),
        )


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
