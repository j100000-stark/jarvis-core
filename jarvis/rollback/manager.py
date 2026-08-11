"""In-process checkpoints for restricted workspace changes."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..sandbox import Sandbox


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Original bytes for files captured before a change."""

    identifier: str
    files: dict[str, bytes | None]


class RollbackManager:
    """Create and restore checkpoints only through a Sandbox path boundary."""

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox
        self._checkpoints: dict[str, Checkpoint] = {}

    def create_checkpoint(self, paths: list[str]) -> Checkpoint:
        files: dict[str, bytes | None] = {}
        for path in paths:
            resolved = self.sandbox.resolve_path(path)
            files[path] = resolved.read_bytes() if resolved.is_file() else None
        checkpoint = Checkpoint(str(uuid4()), files)
        self._checkpoints[checkpoint.identifier] = checkpoint
        return checkpoint

    def restore(self, identifier: str) -> None:
        checkpoint = self._checkpoints[identifier]
        for path, contents in checkpoint.files.items():
            resolved = self.sandbox.resolve_path(path)
            if contents is None:
                if resolved.exists():
                    resolved.unlink()
                continue
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(contents)

    def commit(self, identifier: str) -> None:
        self._checkpoints.pop(identifier, None)

    def has_checkpoint(self, identifier: str) -> bool:
        return identifier in self._checkpoints
