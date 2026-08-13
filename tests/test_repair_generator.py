"""Tests for the LLM-backed repair generator layer (spec §7 continuation)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.agent.remote_llm import MockLLMTransport
from jarvis.recovery.code_repair import CodeRepairPipeline
from jarvis.recovery.repair_generator import (
    LLMPatchGenerator,
    RepairGeneratorUnavailable,
    build_repair_generator,
)

_ENV = {
    "REPAIR_LLM_PROVIDER": "groq",
    "REPAIR_LLM_MODEL": "test-model",
    "REPAIR_LLM_API_KEY": "test-key",
}


def _generator(responses: list[str]) -> LLMPatchGenerator:
    with patch.dict(os.environ, _ENV):
        return LLMPatchGenerator(transport=MockLLMTransport(responses))


def _proposal(patches: dict[str, str], analysis: str = "root cause") -> str:
    return json.dumps({"analysis": analysis, "patches": patches})


class RepairGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "jarvis").mkdir()
        self.target = self.root / "jarvis" / "broken.py"
        self.target.write_text("def f(:\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pipeline(self, gen, **kw) -> CodeRepairPipeline:
        return CodeRepairPipeline(
            project_root=self.root, data_dir=self.root / "data",
            generator=gen, allowed_roots=("jarvis",), **kw,
        )

    # 1 — successful generated repair (gated by runtime verification)
    def test_successful_generated_repair(self):
        fixed = "def f():\n    return 1\n"
        gen = _generator([_proposal({"jarvis/broken.py": fixed})])
        report = self._pipeline(gen).repair(
            failure_message="syntax error in broken.py",
            relevant_files=["jarvis/broken.py"], dry_run=False, verify=lambda: True,
        )
        self.assertTrue(report.success)
        self.assertTrue(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), fixed)
        self.assertEqual(gen.last_analysis, "root cause")

    # 2 — invalid patch (non-JSON model output) never applied
    def test_invalid_model_output_rejected(self):
        gen = _generator(["Sure! Here's the fix: def f(): pass"])
        report = self._pipeline(gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        self.assertFalse(report.success)
        self.assertFalse(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    # 3 — unauthorized file proposed by the model
    def test_unauthorized_file_rejected(self):
        gen = _generator([_proposal({"secrets/steal.py": "x = 1\n"})])
        report = self._pipeline(gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        self.assertFalse(report.success)
        self.assertFalse((self.root / "secrets").exists())

    # 4 — path traversal proposed by the model
    def test_path_traversal_rejected(self):
        gen = _generator([_proposal({"../outside.py": "x = 1\n"})])
        report = self._pipeline(gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        self.assertFalse(report.success)
        self.assertFalse((self.root.parent / "outside.py").exists())

    # 5 — secret leakage: secrets never reach the model; responses sanitized
    def test_secrets_never_reach_model_and_are_redacted(self):
        secret = "sk_live_" + "a" * 40
        self.target.write_text(f'KEY = "{secret}"\ndef f(:\n', encoding="utf-8")
        transport = MockLLMTransport([_proposal(
            {"jarvis/broken.py": "def f():\n    return 1\n"},
            analysis=f"found key {secret}",
        )])
        with patch.dict(os.environ, _ENV):
            gen = LLMPatchGenerator(transport=transport)
        gen("failure mentioning " + secret, {"jarvis/broken.py": self.target.read_text(encoding="utf-8")})
        # Prompt sent to the model must not contain the raw secret
        sent = json.dumps(transport.calls)
        self.assertNotIn(secret, sent)
        # Model response analysis is sanitized before exposure
        self.assertNotIn(secret, gen.last_analysis)
        self.assertIn("[REDACTED]", gen.last_analysis)

    # 6 — failed tests gate application
    def test_failed_tests_prevent_repair(self):
        gen = _generator([_proposal({"jarvis/broken.py": "def f():\n    return 1\n"})])
        report = self._pipeline(
            gen, test_command=("python", "-c", "import sys; sys.exit(1)"),
        ).repair(failure_message="x", relevant_files=["jarvis/broken.py"], dry_run=False)
        self.assertFalse(report.success)
        self.assertFalse(report.applied)

    # 7 — rollback restores original content after failed verification
    def test_rollback_after_failed_verification(self):
        gen = _generator([_proposal({"jarvis/broken.py": "def f():\n    return 1\n"})])
        report = self._pipeline(gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: False,
        )
        self.assertFalse(report.success)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")
        self.assertIn("ROLLBACK", report.stages)

    # 8 — dry run: validated proposal, nothing applied
    def test_dry_run_with_generated_patch(self):
        gen = _generator([_proposal({"jarvis/broken.py": "def f():\n    return 1\n"})])
        report = self._pipeline(gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"], dry_run=True,
        )
        self.assertTrue(report.success)
        self.assertFalse(report.applied)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    # 9 — provider unavailable (no configuration)
    def test_provider_unavailable(self):
        env = {k: "" for k in (
            "REPAIR_LLM_PROVIDER", "REPAIR_LLM_MODEL", "REPAIR_LLM_API_KEY",
            "JARVIS_LLM_PROVIDER", "JARVIS_LLM_MODEL", "JARVIS_LLM_API_KEY",
        )}
        with patch.dict(os.environ, env):
            self.assertIsNone(build_repair_generator())
            with self.assertRaises(RepairGeneratorUnavailable):
                LLMPatchGenerator()
            report = self._pipeline(None, use_llm_generator=True).repair(
                failure_message="x", relevant_files=["jarvis/broken.py"],
                dry_run=False, verify=lambda: True,
            )
        self.assertFalse(report.success)
        self.assertIn("REPAIR_GENERATOR UNAVAILABLE", report.message)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    # 10 — model unavailable (transport failure at call time)
    def test_model_unavailable_reported_honestly(self):
        class FailingTransport:
            def chat_complete(self, **kwargs):
                raise ConnectionError("connection refused")

        with patch.dict(os.environ, _ENV):
            gen = LLMPatchGenerator(transport=FailingTransport())
        report = self._pipeline(gen).repair(
            failure_message="x", relevant_files=["jarvis/broken.py"],
            dry_run=False, verify=lambda: True,
        )
        self.assertFalse(report.success)
        self.assertIn("REPAIR_GENERATOR UNAVAILABLE", report.message)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    # Extra guards
    def test_unknown_provider_alias_unavailable(self):
        with patch.dict(os.environ, {**_ENV, "REPAIR_LLM_PROVIDER": "not-a-provider"}):
            with self.assertRaises(RepairGeneratorUnavailable):
                LLMPatchGenerator()

    def test_short_credentials_and_pem_redacted_in_prompt(self):
        content = (
            'db = "postgres://admin:hunter2@db.example.com/app"\n'
            "password = 'abc12345'\n"
            "-----BEGIN PRIVATE KEY-----\nMIIshort\n-----END PRIVATE KEY-----\n"
            "def f(:\n"
        )
        transport = MockLLMTransport([_proposal({"jarvis/broken.py": "def f():\n    pass\n"})])
        with patch.dict(os.environ, _ENV):
            gen = LLMPatchGenerator(transport=transport)
        gen("diag", {"jarvis/broken.py": content})
        sent = json.dumps(transport.calls)
        self.assertNotIn("hunter2", sent)
        self.assertNotIn("abc12345", sent)
        self.assertNotIn("MIIshort", sent)
        self.assertIn("untrusted-data", sent)

    def test_prompt_respects_total_context_budget(self):
        big = "x = 1\n" * 5000  # 30k chars
        transport = MockLLMTransport([_proposal({"jarvis/a.py": "x = 2\n"})])
        with patch.dict(os.environ, _ENV):
            gen = LLMPatchGenerator(transport=transport, max_context_chars=4000)
        gen("diag", {"jarvis/a.py": big, "jarvis/b.py": big})
        user_msg = transport.calls[0][-1]["content"]
        self.assertLess(len(user_msg), 6000)  # framing + capped snippets
        # Both files got a share — the first did not starve the second
        self.assertIn("jarvis/b.py", user_msg)

    def test_patch_echoing_env_secret_rejected(self):
        secret = "super-secret-value-123456"
        with patch.dict(os.environ, {**_ENV, "MY_API_SECRET": secret}):
            gen = _generator([_proposal(
                {"jarvis/broken.py": f'KEY = "{secret}"\ndef f():\n    return 1\n'}
            )])
            report = self._pipeline(gen).repair(
                failure_message="x", relevant_files=["jarvis/broken.py"],
                dry_run=False, verify=lambda: True,
            )
        self.assertFalse(report.success)
        self.assertTrue(any("MY_API_SECRET" in e for e in report.validation_errors))
        self.assertEqual(self.target.read_text(encoding="utf-8"), "def f(:\n")

    def test_markdown_fenced_json_tolerated(self):
        fixed = "def f():\n    return 2\n"
        gen = _generator(["```json\n" + _proposal({"jarvis/broken.py": fixed}) + "\n```"])
        patches = gen("diag", {"jarvis/broken.py": "def f(:\n"})
        self.assertEqual(patches["jarvis/broken.py"], fixed)


if __name__ == "__main__":
    unittest.main()
