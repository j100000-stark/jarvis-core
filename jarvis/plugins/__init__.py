"""Explicit plugin registration boundary."""

from .manager import PluginManager, PluginNotFound

__all__ = ["PluginManager", "PluginNotFound"]
