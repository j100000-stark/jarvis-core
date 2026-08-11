"""Conservative local sandbox boundary for future tools.

V0.1 does not execute arbitrary shell commands or user-provided code. This
module provides path validation and a small callable boundary for trusted
internal operations so future capabilities have one place to enforce policy.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Outcome of a bounded internal operation."""

    ok: bool
    value: object = None
    error: str | None = None


class Sandbox:
    """Apply basic workspace and timeout boundaries to internal operations."""

    def __init__(self, workspace_root: Path, timeout_seconds: float = 2.0) -> None:
        self.workspace_root = workspace_root.resolve()
        self.timeout_seconds = timeout_seconds

    def resolve_path(self, requested: str | Path) -> Path:
        """Resolve a path only if it remains inside the workspace root."""
        candidate = (self.workspace_root / requested).resolve()
        if candidate != self.workspace_root and self.workspace_root not in candidate.parents:
            raise PermissionError("Sandbox path escapes the workspace root.")
        return candidate

    def run(self, operation: Callable[[], T]) -> SandboxResult:
        """Run a trusted callable with a short timeout."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(operation)
            try:
                return SandboxResult(ok=True, value=future.result(timeout=self.timeout_seconds))
            except TimeoutError:
                future.cancel()
                return SandboxResult(ok=False, error="Operation exceeded sandbox timeout.")
            except Exception as error:
                return SandboxResult(ok=False, error=str(error))
