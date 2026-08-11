"""Restricted Python code generation, testing, and rollback workflow."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

from ..memory import MemoryStore
from ..recovery import RecoveryManager
from ..rollback import RollbackManager
from ..sandbox import Sandbox
from .brain import Brain
from .models import CodeChange, CodeGenerationRequest


@dataclass(frozen=True, slots=True)
class CodeAgentResult:
    """Outcome of applying and sandbox-testing generated changes."""

    success: bool
    checkpoint_id: str | None
    changed_files: tuple[str, ...] = ()
    error: str | None = None


class CodeAgent:
    """Apply only complete Python file changes within the sandbox root."""

    def __init__(
        self,
        brain: Brain,
        sandbox: Sandbox,
        rollback: RollbackManager,
        recovery: RecoveryManager,
        memory: MemoryStore | None = None,
    ) -> None:
        self.brain = brain
        self.sandbox = sandbox
        self.rollback = rollback
        self.recovery = recovery
        self.memory = memory

    def apply(self, goal: str, allowed_files: tuple[str, ...]) -> CodeAgentResult:
        """Generate, checkpoint, write, compile-test, and commit changes."""
        existing = {
            path: self.sandbox.resolve_path(path).read_text(encoding="utf-8")
            for path in allowed_files
            if self.sandbox.resolve_path(path).is_file()
        }
        request = CodeGenerationRequest(goal, allowed_files, existing)
        changes = self.brain.generate_code(request)
        return self.apply_changes(goal, changes, allowed_files)

    def apply_changes(
        self,
        goal: str,
        changes: tuple[CodeChange, ...],
        allowed_files: tuple[str, ...],
    ) -> CodeAgentResult:
        """Apply an already-approved set of changes through the same safety flow."""
        self._validate_changes(changes, allowed_files)
        paths = [change.path for change in changes]
        checkpoint = self.rollback.create_checkpoint(paths)
        try:
            for change in changes:
                destination = self.sandbox.resolve_path(change.path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".jarvis.tmp")
                temporary.write_text(change.content, encoding="utf-8")
                os.replace(temporary, destination)

            result = self.sandbox.test_python_files(paths)
            if not result.ok:
                raise SyntaxError(result.error or "Sandbox test failed.")

            self.rollback.commit(checkpoint.identifier)
            if self.memory is not None:
                self.memory.remember(f"Code change completed: {goal}")
            return CodeAgentResult(True, checkpoint.identifier, tuple(paths))
        except Exception as error:
            self.rollback.restore(checkpoint.identifier)
            incident = self.recovery.record(error, operation="code-agent")
            return CodeAgentResult(
                False,
                checkpoint.identifier,
                tuple(paths),
                f"Change rolled back after incident #{incident.identifier}: {error}",
            )

    def _validate_changes(
        self, changes: tuple[CodeChange, ...], allowed_files: tuple[str, ...]
    ) -> None:
        if not changes:
            raise ValueError("Brain returned no code changes.")
        allowed = set(allowed_files)
        for change in changes:
            if change.path not in allowed:
                raise PermissionError(f"Code change is outside the allowed file set: {change.path}")
            if Path(change.path).suffix != ".py":
                raise ValueError("CodeAgent only permits Python files.")
            self.sandbox.resolve_path(change.path)
            ast.parse(change.content, filename=change.path)
