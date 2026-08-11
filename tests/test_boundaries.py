from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jarvis.network import NetworkAccessDenied, NetworkManager, NetworkPolicy
from jarvis.plugins import PluginManager, PluginNotFound
from jarvis.rollback import RollbackManager
from jarvis.sandbox import Sandbox
from jarvis.system import SystemMonitor


class SandboxTests(unittest.TestCase):
    def test_sandbox_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Sandbox(Path(directory))
            with self.assertRaises(PermissionError):
                sandbox.resolve_path("../outside.py")

    def test_sandbox_runs_and_times_out_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Sandbox(Path(directory), timeout_seconds=0.1)
            self.assertEqual(sandbox.run(lambda: "ok").value, "ok")

            import time

            result = sandbox.run(lambda: time.sleep(0.2))
            self.assertFalse(result.ok)


class RollbackTests(unittest.TestCase):
    def test_checkpoint_restores_original_and_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.py").write_text("old = True\n")
            sandbox = Sandbox(root)
            manager = RollbackManager(sandbox)
            checkpoint = manager.create_checkpoint(["existing.py", "new.py"])
            (root / "existing.py").write_text("new = True\n")
            (root / "new.py").write_text("created = True\n")
            manager.restore(checkpoint.identifier)
            self.assertEqual((root / "existing.py").read_text(), "old = True\n")
            self.assertFalse((root / "new.py").exists())


class SystemMonitorTests(unittest.TestCase):
    def test_monitor_returns_read_only_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = SystemMonitor(Path(directory)).snapshot()
            self.assertGreaterEqual(snapshot.cpu_count, 1)
            self.assertGreater(snapshot.disk_free_bytes, 0)


class NetworkTests(unittest.TestCase):
    def test_network_is_disabled_by_default(self) -> None:
        with self.assertRaises(NetworkAccessDenied):
            NetworkManager().authorize("https://example.com")

    def test_network_allow_list(self) -> None:
        manager = NetworkManager(
            NetworkPolicy(allow_external=True, allowed_hosts=frozenset({"localhost"}))
        )
        self.assertEqual(manager.authorize("http://localhost:8000/health"), "localhost")
        with self.assertRaises(NetworkAccessDenied):
            manager.authorize("https://example.com")


class PluginTests(unittest.TestCase):
    def test_plugins_are_discovered_without_importing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "candidate.py").write_text("raise RuntimeError('must not import')\n")
            manager = PluginManager(root)
            self.assertEqual(manager.discover(), ("candidate",))
            with self.assertRaises(PluginNotFound):
                manager.load("candidate")

    def test_registered_plugin_factory_loads_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = PluginManager(Path(directory))
            manager.register_factory("test", lambda: {"ready": True})
            self.assertEqual(manager.load("test"), {"ready": True})


if __name__ == "__main__":
    unittest.main()
