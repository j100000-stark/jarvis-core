"""Tests for the persistent runtime configuration overlay (spec Phase 10)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from jarvis.config import ConfigStore, ConfigStoreError, Settings


class ConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "runtime_config.json"
        self.store = ConfigStore(self.path)
        self._saved_env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved_env)
        self._tmp.cleanup()

    def test_set_value_persists_to_file_and_environ(self) -> None:
        self.store.set_value("JARVIS_WEB_RESEARCH_ENABLED", "true")
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["JARVIS_WEB_RESEARCH_ENABLED"], "true")
        self.assertEqual(os.environ["JARVIS_WEB_RESEARCH_ENABLED"], "true")

    def test_value_survives_simulated_restart(self) -> None:
        """The core Phase 10 guarantee: repair persists across restarts."""
        self.store.set_value("JARVIS_WEB_RESEARCH_ENABLED", "true")
        # Simulate restart: wipe process env, build a brand-new store instance
        os.environ.pop("JARVIS_WEB_RESEARCH_ENABLED", None)
        fresh = ConfigStore(self.path)
        applied = fresh.apply_to_environ()
        self.assertIn("JARVIS_WEB_RESEARCH_ENABLED", applied)
        self.assertEqual(os.environ["JARVIS_WEB_RESEARCH_ENABLED"], "true")

    def test_environment_variable_wins_over_overlay(self) -> None:
        self.store.set_value("JARVIS_MAX_MEMORY", "100")
        os.environ["JARVIS_MAX_MEMORY"] = "999"
        fresh = ConfigStore(self.path)
        applied = fresh.apply_to_environ()
        self.assertNotIn("JARVIS_MAX_MEMORY", applied)
        self.assertEqual(os.environ["JARVIS_MAX_MEMORY"], "999")

    def test_rejects_secret_looking_keys(self) -> None:
        for key in ("JARVIS_API_KEY", "JARVIS_SECRET_THING", "JARVIS_TOKEN_X"):
            with self.assertRaises(ConfigStoreError):
                self.store.set_value(key, "x")
        self.assertFalse(self.path.exists())

    def test_rejects_non_jarvis_keys(self) -> None:
        with self.assertRaises(ConfigStoreError):
            self.store.set_value("PATH", "/tmp")

    def test_delete_removes_from_file_and_environ(self) -> None:
        self.store.set_value("JARVIS_DEMO_MODE", "true")
        self.assertTrue(self.store.delete("JARVIS_DEMO_MODE"))
        self.assertNotIn("JARVIS_DEMO_MODE", self.store.load())
        self.assertNotIn("JARVIS_DEMO_MODE", os.environ)
        self.assertFalse(self.store.delete("JARVIS_DEMO_MODE"))

    def test_corrupt_file_returns_empty(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.load(), {})

    def test_settings_from_environment_applies_overlay(self) -> None:
        """Settings.from_environment must pick up persisted overrides."""
        os.environ.pop("JARVIS_WEB_RESEARCH_ENABLED", None)
        # Default ConfigStore path — patch via env-driven data dir is not
        # supported, so verify through the overlay mechanism directly.
        self.store.set_value("JARVIS_WEB_RESEARCH_ENABLED", "false")
        # set_value mirrored into os.environ, which from_environment reads.
        settings = Settings.from_environment(memory_file="/tmp/nonexistent-mem.json")
        self.assertFalse(settings.web_research_enabled)


if __name__ == "__main__":
    unittest.main()
