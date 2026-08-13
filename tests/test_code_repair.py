"""Tests for the AI-assisted code-repair pipeline (spec §7)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis.recovery.code_repair import CodeRepairPipeline


def _pipeline(root: Path, generator=None, test_command=None) -> CodeRepairPipeline:
    return CodeRepairPipeline(
        project_root=root,
        data_dir=root / "data",
        generator=generator,
        allowed_roots=("jarvis",),
        test_command=test_command,
    )


class CodeRepairPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "jarvis").mkdir()
        self.target = self.root / "jarvis" / "broken.py"
        self.target.write_text("def f(:\n", encoding="utf-8")  # broken source

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ── Safety ──────────────────────────────────────────────────────────

    def test_no_generator_changes_nothing(self):
        report = _pipeline(self.root).repair(
            failure_message="syntax error", relevant_files=["jarvis/broken.py"],
            dry_run=False,
        )
        self.assertFalse(report.success)
        self.assertFalse(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    def test_rejects_paths_outside_allowlist(self):
        gen = lambda diag, files: {"secrets/x.py": "x = 1\n"}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"], dry_run=False,
        )
        self.assertFalse(report.success)
        self.assertTrue(any("Forbidden" in e or "allowed roots" in e
                            for e in report.validation_errors))
        self.assertFalse((self.root / "secrets").exists())

    def test_rejects_env_and_traversal(self):
        p = _pipeline(self.root)
        self.assertIsNotNone(p._path_error("../etc/passwd.py"))
        self.assertIsNotNone(p._path_error(".env"))
        self.assertIsNotNone(p._path_error("jarvis/.env.py"))
        self.assertIsNotNone(p._path_error("/abs/path.py"))

    def test_invalid_python_patch_never_written(self):
        gen = lambda diag, files: {"jarvis/broken.py": "def f(:\n  still broken"}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"], dry_run=False,
        )
        self.assertFalse(report.success)
        self.assertFalse(report.applied)
        self.assertTrue(any("Syntax error" in e for e in report.validation_errors))
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    # ── Dry run ─────────────────────────────────────────────────────────

    def test_dry_run_validates_but_does_not_apply(self):
        gen = lambda diag, files: {"jarvis/broken.py": "def f():\n    return 1\n"}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"], dry_run=True,
        )
        self.assertTrue(report.success)
        self.assertTrue(report.dry_run)
        self.assertFalse(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")
        self.assertIn("DRY_RUN_COMPLETE", report.stages)

    # ── Apply + rollback ────────────────────────────────────────────────

    def test_valid_patch_applied_with_verification(self):
        fixed = "def f():\n    return 1\n"
        gen = lambda diag, files: {"jarvis/broken.py": fixed}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        self.assertTrue(report.success)
        self.assertTrue(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), fixed)

    def test_apply_refused_without_any_verification(self):
        fixed = "def f():\n    return 1\n"
        gen = lambda diag, files: {"jarvis/broken.py": fixed}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"], dry_run=False,
        )
        self.assertFalse(report.success)
        self.assertFalse(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    def test_patch_outside_identified_files_rejected(self):
        other = self.root / "jarvis" / "other.py"
        other.write_text("x = 1\n", encoding="utf-8")
        gen = lambda diag, files: {"jarvis/other.py": "x = 2\n"}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        self.assertFalse(report.success)
        self.assertTrue(any("outside the identified set" in e
                            for e in report.validation_errors))
        self.assertEqual(other.read_text(encoding="utf-8"), "x = 1\n")

    def test_rollback_restores_exact_disk_state_of_new_file(self):
        # Patch creates a file that did not exist before → rollback deletes it.
        new_rel = "jarvis/created.py"
        gen = lambda diag, files: {new_rel: "y = 1\n"}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=[new_rel],
            dry_run=False, verify=lambda: False,
        )
        self.assertFalse(report.success)
        self.assertFalse((self.root / new_rel).exists())

    def test_diagnosis_and_results_are_sanitized(self):
        fixed = "def f():\n    return 1\n"
        gen = lambda diag, files: {"jarvis/broken.py": fixed}  # noqa: E731
        secret = "sk_" + "a" * 40
        report = _pipeline(self.root, gen).repair(
            failure_message=f"crash with token {secret}",
            relevant_files=["jarvis/broken.py"], dry_run=True,
        )
        self.assertNotIn(secret, report.diagnosis)
        self.assertIn("[REDACTED]", report.diagnosis)

    def test_failing_tests_roll_back(self):
        fixed = "def f():\n    return 1\n"
        gen = lambda diag, files: {"jarvis/broken.py": fixed}  # noqa: E731
        report = _pipeline(
            self.root, gen, test_command=("python", "-c", "import sys; sys.exit(1)"),
        ).repair(failure_message="x", relevant_files=["jarvis/broken.py"],
                 dry_run=False, verify=lambda: True)
        self.assertFalse(report.success)
        self.assertFalse(report.applied)
        self.assertIn("ROLLBACK", report.stages)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    def test_failing_runtime_verification_rolls_back(self):
        fixed = "def f():\n    return 1\n"
        gen = lambda diag, files: {"jarvis/broken.py": fixed}  # noqa: E731
        report = _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: False,
        )
        self.assertFalse(report.success)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    # ── Incident recording ──────────────────────────────────────────────

    def test_incident_recorded_without_patch_contents(self):
        gen = lambda diag, files: {"jarvis/broken.py": "def f():\n    return 1\n"}  # noqa: E731
        _pipeline(self.root, gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        data = json.loads(
            (self.root / "data" / "code_repair_incidents.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(data), 1)
        self.assertIsInstance(data[0]["patched_files"]["jarvis/broken.py"], int)
        self.assertNotIn("proposed_patch", data[0])  # never persist raw contents


class SelfRepairDiagnosticRecordTests(unittest.TestCase):
    def test_incident_contains_full_diagnostic_record(self):
        import tempfile as _tf
        from jarvis.recovery.self_repair import SelfRepairManager

        with _tf.TemporaryDirectory() as td:
            mgr = SelfRepairManager(Path(td))
            mgr.diagnose_and_repair(
                failure_message="tts_quota_or_billing: upstream 402",
                failure_step="speak",
                goal="say hello",
                settings=None,
                registry=None,
            )
            data = json.loads(
                (Path(td) / "repair_incidents.json").read_text(encoding="utf-8")
            )
            rec = data[0]
            for key in ("component", "root_cause", "evidence", "files_involved",
                        "proposed_repair", "tests_run", "test_results"):
                self.assertIn(key, rec)
            self.assertEqual(rec["component"], "TextToSpeech")
            self.assertIn("402", rec["evidence"])


if __name__ == "__main__":
    unittest.main()
