"""State recovery: persist and restore service state before risky operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StateRecoveryManager:
    """Persist and restore service state snapshots around risky operations.

    Snapshots are JSON-serializable dicts written to the data directory.
    Only simple, JSON-serializable types are supported to keep this
    standard-library-only.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: dict[str, dict[str, Any]] = {}

    def _path_for(self, service_name: str) -> Path:
        safe = service_name.replace("/", "_").replace("\\", "_")
        return self._data_dir / f"state_{safe}.json"

    def save(self, service_name: str, state: dict[str, Any]) -> None:
        """Persist a state snapshot for a named service."""
        if not isinstance(state, dict):
            raise TypeError("State must be a JSON-serializable dict.")
        self._snapshots[service_name] = dict(state)
        path = self._path_for(service_name)
        try:
            path.write_text(json.dumps(state, default=str), encoding="utf-8")
        except OSError:
            pass  # In-memory snapshot remains available

    def load(self, service_name: str) -> dict[str, Any] | None:
        """Return the most recent snapshot for a service, or None."""
        if service_name in self._snapshots:
            return dict(self._snapshots[service_name])
        path = self._path_for(service_name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._snapshots[service_name] = data
                return dict(data)
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def delete(self, service_name: str) -> None:
        """Remove a snapshot from memory and disk."""
        self._snapshots.pop(service_name, None)
        path = self._path_for(service_name)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def has_snapshot(self, service_name: str) -> bool:
        """Return True if a snapshot exists for the named service."""
        if service_name in self._snapshots:
            return True
        return self._path_for(service_name).exists()

    def all_service_names(self) -> list[str]:
        """Return the names of all services with in-memory snapshots."""
        return list(self._snapshots.keys())
