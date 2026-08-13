"""Tests for SelfRepairManager.

Covers:
  - Failure classification
  - Each repair strategy
  - Max attempts safety limit
  - web_research_disabled repair (env patch + settings rebuild)
  - Incident recording
  - tool_not_found reporting
  - Transient-error retry signals
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from jarvis.recovery.self_repair import SelfRepairManager, RepairResult


def _manager(tmp: str) -> SelfRepairManager:
    return SelfRepairManager(Path(tmp))


def _mock_registry(names: list[str]) -> MagicMock:
    reg = MagicMock()
    reg.names.return_value = names
    return reg


def _mock_settings(web_enabled: bool = False) -> MagicMock:
    s = MagicMock()
    s.web_research_enabled = web_enabled
    s.memory_file = "data/memory.json"
    return s


class TestClassification(unittest.TestCase):
    def _classify(self, message: str, step: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            return m._classify(message, step)

    def test_web_research_disabled(self) -> None:
        self.assertEqual(
            self._classify("Web research is not currently enabled."),
            "web_research_disabled",
        )

    def test_tool_not_found(self) -> None:
        self.assertEqual(self._classify("Unknown tool: weather"), "tool_not_found")

    def test_cloudflare_block(self) -> None:
        self.assertEqual(self._classify("1010 cloudflare 403"), "cloudflare_blocked")

    def test_timeout(self) -> None:
        self.assertEqual(self._classify("Request timed out"), "timeout")

    def test_network_error(self) -> None:
        self.assertEqual(self._classify("Could not reach LLM API at https://..."), "network_error")

    def test_rate_limited(self) -> None:
        self.assertEqual(self._classify("HTTP 429 Too Many Requests"), "rate_limited")

    def test_auth_error(self) -> None:
        self.assertEqual(self._classify("LLM API returned HTTP 403: Forbidden"), "auth_error")

    def test_unknown_falls_through(self) -> None:
        self.assertEqual(self._classify("Something completely unexpected"), "unknown")


class TestWebResearchRepair(unittest.TestCase):
    def test_repair_enables_web_research(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Ensure it starts disabled
            os.environ.pop("JARVIS_WEB_RESEARCH_ENABLED", None)
            m = _manager(tmp)
            settings = _mock_settings(web_enabled=False)

            result = m.diagnose_and_repair(
                failure_message="Web research is not currently enabled.",
                failure_step=None,
                goal="cerca online il meteo di Milano",
                settings=settings,
                registry=_mock_registry(["web_research", "echo"]),
            )
            # Should succeed and provide patched settings
            self.assertTrue(result.success)
            self.assertEqual(result.failure_type, "web_research_disabled")
            self.assertIsNotNone(result.repaired_settings)
            # Env var should be set
            self.assertEqual(os.environ.get("JARVIS_WEB_RESEARCH_ENABLED"), "true")

    def test_repair_provides_new_settings_with_enabled_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JARVIS_WEB_RESEARCH_ENABLED"] = "true"
            m = _manager(tmp)
            settings = _mock_settings(web_enabled=False)

            result = m.diagnose_and_repair(
                failure_message="Web research is not currently enabled.",
                failure_step=None,
                goal="cerca notizie",
                settings=settings,
                registry=_mock_registry(["web_research"]),
            )
            self.assertTrue(result.success)
            if result.repaired_settings is not None:
                self.assertTrue(result.repaired_settings.web_research_enabled)


class TestToolNotFound(unittest.TestCase):
    def test_tool_not_found_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            result = m.diagnose_and_repair(
                failure_message="Unknown tool: weather_forecast",
                failure_step=None,
                goal="che tempo fa a Milano?",
                settings=_mock_settings(),
                registry=_mock_registry(["echo", "time", "web_research"]),
            )
            self.assertFalse(result.success)
            self.assertEqual(result.failure_type, "tool_not_found")
            # Available tools should be listed in the actions
            self.assertTrue(any("echo" in a for a in result.actions))


class TestTransientErrors(unittest.TestCase):
    def test_timeout_signals_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            result = m.diagnose_and_repair(
                failure_message="Request timed out",
                failure_step=None,
                goal="qualcosa",
                settings=_mock_settings(),
                registry=_mock_registry([]),
            )
            self.assertTrue(result.success)  # retry signal
            self.assertEqual(result.failure_type, "timeout")

    def test_network_error_signals_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            result = m.diagnose_and_repair(
                failure_message="Could not reach LLM API",
                failure_step=None,
                goal="qualcosa",
                settings=_mock_settings(),
                registry=_mock_registry([]),
            )
            self.assertTrue(result.success)

    def test_llm_error_signals_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            result = m.diagnose_and_repair(
                failure_message="LLM API returned HTTP 500",
                failure_step="planning",
                goal="qualcosa",
                settings=_mock_settings(),
                registry=_mock_registry([]),
            )
            self.assertTrue(result.success)


class TestSafetyLimit(unittest.TestCase):
    def test_max_attempts_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            settings = _mock_settings()
            reg = _mock_registry([])

            # Exhaust attempts
            for _ in range(3):
                m.diagnose_and_repair(
                    failure_message="timeout",
                    failure_step=None,
                    goal="test",
                    settings=settings,
                    registry=reg,
                )

            # 4th attempt should be blocked
            result = m.diagnose_and_repair(
                failure_message="timeout",
                failure_step=None,
                goal="test",
                settings=settings,
                registry=reg,
            )
            self.assertFalse(result.success)
            self.assertEqual(result.failure_type, "max_attempts_exceeded")

    def test_reset_attempts_allows_new_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            settings = _mock_settings()
            reg = _mock_registry([])

            # Exhaust
            for _ in range(3):
                m.diagnose_and_repair(
                    failure_message="timeout", failure_step=None, goal="g",
                    settings=settings, registry=reg,
                )

            m.reset_attempts()

            result = m.diagnose_and_repair(
                failure_message="timeout", failure_step=None, goal="g",
                settings=settings, registry=reg,
            )
            self.assertNotEqual(result.failure_type, "max_attempts_exceeded")


class TestIncidentRecording(unittest.TestCase):
    def test_incidents_written_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            m.diagnose_and_repair(
                failure_message="timeout",
                failure_step=None,
                goal="test goal",
                settings=_mock_settings(),
                registry=_mock_registry([]),
            )
            incident_file = Path(tmp) / "repair_incidents.json"
            self.assertTrue(incident_file.exists())
            import json
            data = json.loads(incident_file.read_text())
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)
            self.assertEqual(data[0]["failure_type"], "timeout")

    def test_incident_count_increments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            self.assertEqual(m.incident_count(), 0)
            m.diagnose_and_repair(
                failure_message="timeout", failure_step=None, goal="g",
                settings=_mock_settings(), registry=_mock_registry([]),
            )
            self.assertEqual(m.incident_count(), 1)


class TestNonDestructive(unittest.TestCase):
    """Repair must never expose secrets or delete unrelated files."""

    def test_repair_does_not_expose_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            os.environ["JARVIS_LLM_API_KEY"] = "supersecret"
            try:
                result = m.diagnose_and_repair(
                    failure_message="LLM API returned HTTP 401",
                    failure_step=None,
                    goal="test",
                    settings=_mock_settings(),
                    registry=_mock_registry([]),
                )
                combined = " ".join(result.actions) + result.message
                self.assertNotIn("supersecret", combined)
            finally:
                os.environ.pop("JARVIS_LLM_API_KEY", None)

    def test_unknown_failure_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = _manager(tmp)
            result = m.diagnose_and_repair(
                failure_message="some totally alien error",
                failure_step=None,
                goal="test",
                settings=_mock_settings(),
                registry=_mock_registry([]),
            )
            self.assertFalse(result.success)
            self.assertEqual(result.failure_type, "unknown")


if __name__ == "__main__":
    unittest.main()
