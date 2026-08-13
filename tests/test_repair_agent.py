"""Tests for the RepairAgent transactional lifecycle (spec Phases 7-9)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis.recovery import RepairAgent


class RepairAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir()
        self.config_file = self.root / "data" / "runtime_config.json"
        self.agent = RepairAgent(self.root / "data", workspace_root=self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, patch, verify, **kwargs):
        return self.agent.run_repair(
            component="config",
            error_category="test_category",
            root_cause="test root cause",
            repair_plan=["step one"],
            patch=patch,
            verify=verify,
            **kwargs,
        )

    def test_successful_lifecycle(self) -> None:
        def patch():
            self.config_file.write_text('{"JARVIS_X": "1"}', encoding="utf-8")
            return [str(self.config_file)]

        outcome = self._run(patch, lambda: True)
        self.assertTrue(outcome.success)
        self.assertTrue(outcome.should_retry)
        self.assertEqual(outcome.incident.verification_result, "passed")
        self.assertIn("PATCH APPLIED", outcome.incident.stages)
        self.assertIn("VERIFICATION PASSED", outcome.incident.stages)

    def test_verification_failure_rolls_back(self) -> None:
        self.config_file.write_text('{"ORIGINAL": "yes"}', encoding="utf-8")

        def patch():
            self.config_file.write_text('{"BROKEN": "yes"}', encoding="utf-8")
            return [str(self.config_file)]

        outcome = self._run(patch, lambda: False)
        self.assertFalse(outcome.success)
        self.assertIn("ROLLBACK", outcome.incident.stages)
        restored = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertEqual(restored, {"ORIGINAL": "yes"})

    def test_rollback_removes_file_created_by_patch(self) -> None:
        self.assertFalse(self.config_file.exists())

        def patch():
            self.config_file.write_text("{}", encoding="utf-8")
            return [str(self.config_file)]

        outcome = self._run(patch, lambda: False)
        self.assertFalse(outcome.success)
        self.assertFalse(self.config_file.exists())

    def test_patch_outside_allowlist_rejected(self) -> None:
        illegal = self.root / "jarvis_secrets.py"

        def patch():
            illegal.write_text("x = 1", encoding="utf-8")
            return [str(illegal)]

        outcome = self._run(patch, lambda: True)
        self.assertFalse(outcome.success)
        self.assertTrue(any("REJECTED" in s for s in outcome.incident.stages))

    def test_patch_exception_rolls_back(self) -> None:
        def patch():
            raise RuntimeError("patch exploded")

        outcome = self._run(patch, lambda: True)
        self.assertFalse(outcome.success)
        self.assertIn("PATCH FAILED", outcome.incident.stages)
        self.assertIn("ROLLBACK", outcome.incident.stages)

    def test_rollback_restores_environment(self) -> None:
        """Rollback must undo os.environ mutations, not just files."""
        import os

        os.environ.pop("JARVIS_ROLLBACK_PROBE", None)

        def patch():
            os.environ["JARVIS_ROLLBACK_PROBE"] = "leaked"
            self.config_file.write_text("{}", encoding="utf-8")
            return [str(self.config_file)]

        outcome = self._run(patch, lambda: False)
        self.assertFalse(outcome.success)
        self.assertNotIn("JARVIS_ROLLBACK_PROBE", os.environ)

    def test_incident_records_are_sanitized(self) -> None:
        secret = "sk_live_" + "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"

        def patch():
            self.config_file.write_text("{}", encoding="utf-8")
            return [str(self.config_file)]

        self.agent.run_repair(
            component="config",
            error_category="test",
            root_cause=f"failed with key {secret}",
            repair_plan=[f"use {secret}"],
            patch=patch,
            verify=lambda: True,
        )
        raw = (self.root / "data" / "repair_agent_incidents.json").read_text()
        self.assertNotIn(secret, raw)

    def test_max_three_attempts_per_incident_key(self) -> None:
        def patch():
            return []

        for _ in range(3):
            outcome = self._run(patch, lambda: False)
            self.assertFalse(outcome.success)
        blocked = self._run(patch, lambda: True)
        self.assertFalse(blocked.success)
        self.assertIn("Repair limit", blocked.message)

    def test_incidents_recorded_with_full_audit_fields(self) -> None:
        def patch():
            self.config_file.write_text("{}", encoding="utf-8")
            return [str(self.config_file)]

        self._run(patch, lambda: True)
        records = self.agent.incidents()
        self.assertEqual(len(records), 1)
        record = records[0]
        for field in (
            "incidentId", "timestamp", "component", "errorCategory", "rootCause",
            "repairPlan", "filesChanged", "testsExecuted", "verificationResult",
            "rollbackResult", "retryResult", "stages",
        ):
            self.assertIn(field, record)
        self.assertEqual(record["verificationResult"], "passed")

    def test_model_config_defaults_to_main_brain(self) -> None:
        config = RepairAgent.model_config()
        self.assertIn("provider", config)
        self.assertIn("model", config)


class SelfRepairTtsStrategyTests(unittest.TestCase):
    """TTS repair strategies never invent config or touch secrets (Phase 11)."""

    def setUp(self) -> None:
        from jarvis.recovery import SelfRepairManager

        self._tmp = tempfile.TemporaryDirectory()
        self.manager = SelfRepairManager(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _repair(self, category: str):
        return self.manager.diagnose_and_repair(
            failure_message=f"TTS failed: {category}",
            failure_step=None,
            goal="say hello",
            settings=None,
            registry=None,
        )

    def test_auth_failures_require_user_action(self) -> None:
        for cat in ("TTS_API_KEY_MISSING", "TTS_AUTH_FAILED"):
            result = self._repair(cat)
            self.assertFalse(result.success)
            self.assertIn("user action", result.message.lower())

    def test_voice_model_failures_never_invent_ids(self) -> None:
        for cat in ("TTS_VOICE_NOT_FOUND", "TTS_MODEL_INVALID"):
            result = self._repair(cat)
            self.assertFalse(result.success)
            self.assertTrue(
                any("never invents" in a for a in result.actions),
                f"missing no-invention guarantee for {cat}: {result.actions}",
            )

    def test_transient_network_failure_signals_retry(self) -> None:
        result = self._repair("TTS_NETWORK_ERROR")
        self.assertTrue(result.success)

    def test_upstream_error_reports_without_retry(self) -> None:
        result = self._repair("TTS_UPSTREAM_ERROR")
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
