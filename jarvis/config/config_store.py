"""Persistent runtime configuration overlay — the authoritative mutable config source.

Precedence when building Settings (see settings.py):
    1. Environment variable (explicit operator intent, highest priority)
    2. runtime_config.json (persisted overrides, survives restarts)
    3. Dataclass default

Self-repair MUST use this store (not bare os.environ patches) so that
configuration repairs survive process restarts.  set_value() updates both
the JSON file (persistence) and os.environ (immediate visibility for code
that reads the environment directly).

The store only accepts JARVIS_* / REPAIR_* keys and never stores secrets:
keys containing API_KEY / SECRET / TOKEN / PASSWORD are rejected loudly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_FORBIDDEN_FRAGMENTS = ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
_ALLOWED_PREFIXES = ("JARVIS_", "REPAIR_")

DEFAULT_CONFIG_PATH = Path("data/runtime_config.json")


class ConfigStoreError(ValueError):
    """Raised when a config operation violates safety constraints."""


def _validate_key(key: str) -> None:
    if not any(key.startswith(p) for p in _ALLOWED_PREFIXES):
        raise ConfigStoreError(
            f"Config key {key!r} must start with one of {_ALLOWED_PREFIXES}."
        )
    upper = key.upper()
    if any(frag in upper for frag in _FORBIDDEN_FRAGMENTS):
        raise ConfigStoreError(
            f"Config key {key!r} looks like a secret — secrets must be managed "
            "through the platform secret store, never runtime_config.json."
        )


class ConfigStore:
    """Read/write access to the persistent runtime configuration overlay."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_CONFIG_PATH

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, str]:
        """Return all persisted overrides ({} when the file is absent/corrupt)."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def get(self, key: str) -> str | None:
        return self.load().get(key)

    def set_value(self, key: str, value: str) -> None:
        """Persist an override and mirror it into os.environ.

        Raises ConfigStoreError for non-JARVIS keys or secret-looking keys.
        """
        _validate_key(key)
        data = self.load()
        data[key] = str(value)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)
        os.environ[key] = str(value)

    def delete(self, key: str) -> bool:
        data = self.load()
        if key not in data:
            return False
        del data[key]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)
        os.environ.pop(key, None)
        return True

    def apply_to_environ(self) -> list[str]:
        """Load persisted overrides into os.environ for keys not already set.

        Environment variables set by the operator always win — overlays only
        fill gaps.  Returns the list of keys applied.
        """
        applied: list[str] = []
        for key, value in self.load().items():
            if key not in os.environ:
                os.environ[key] = value
                applied.append(key)
        return applied
