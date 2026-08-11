"""Plugin lifecycle without automatic arbitrary module execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


class PluginNotFound(LookupError):
    """Raised when a requested plugin has not been explicitly registered."""


class PluginManager:
    """Discover candidates and load only explicitly registered factories."""

    def __init__(self, plugin_root: Path) -> None:
        self.plugin_root = plugin_root.resolve()
        self._factories: dict[str, Callable[[], Any]] = {}

    def discover(self) -> tuple[str, ...]:
        """List Python plugin candidates without importing or executing them."""
        if not self.plugin_root.exists():
            return ()
        return tuple(sorted(path.stem for path in self.plugin_root.glob("*.py") if path.is_file()))

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        if not name or name in self._factories:
            raise ValueError(f"Invalid or duplicate plugin: {name}")
        self._factories[name] = factory

    def load(self, name: str) -> Any:
        try:
            factory = self._factories[name]
        except KeyError as error:
            raise PluginNotFound(name) from error
        return factory()

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
