from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.agent import (
    CodeChange,
    CodeGenerationRequest,
    LocalAIProvider,
    LocalProviderResponseError,
    ProcessLocalModelTransport,
)
from jarvis.agent.models import ExecutionReport
from jarvis.config import Settings


class MockLocalTransport:
    """Deterministic local-runtime stand-in; no model or network is used."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, float]] = []

    def complete(self, prompt: str, model_name: str, timeout_seconds: float) -> str:
        self.calls.append((prompt, model_name, timeout_seconds))
        if not self.responses:
            raise AssertionError("Mock local transport has no response left")
        return self.responses.pop(0)


class LocalProviderTests(unittest.TestCase):
    def test_local_provider_converts_plan_json_into_core_plan(self) -> None:
        transport = MockLocalTransport(
            [
                json.dumps(
                    {
                        "goal": "organize notes",
                        "steps": [
                            {
                                "identifier": "step-1",
                                "objective": "echo a confirmation",
                                "tool_name": "echo",
                                "argument": "done",
                                "verification": "non-empty output",
                                "max_retries": 1,
                            }
                        ],
                    }
                )
            ]
        )
        provider = LocalAIProvider(transport, "pi-model", timeout_seconds=4.5)

        plan = provider.create_plan("organize notes", ("use local files",))

        self.assertEqual(provider.name, "local:pi-model")
        self.assertEqual(plan.steps[0].tool_name, "echo")
        self.assertEqual(plan.steps[0].max_retries, 1)
        self.assertEqual(transport.calls[0][1:], ("pi-model", 4.5))
        self.assertIn("organize notes", transport.calls[0][0])

    def test_local_provider_converts_code_and_improvement_json(self) -> None:
        transport = MockLocalTransport(
            [
                '{"changes":[{"path":"worker.py","content":"value = 1\\n"}]}',
                '{"title":"Tighten worker","rationale":"Observed failure","changes":[{"path":"worker.py","content":"value = 2\\n"}]}',
            ]
        )
        provider = LocalAIProvider(transport, "pi-model")

        changes = provider.generate_code(
            CodeGenerationRequest("update worker", ("worker.py",))
        )
        proposal = provider.propose_improvement(
            ExecutionReport("goal", False, (), "failed"),
            (),
        )

        self.assertEqual(changes, (CodeChange("worker.py", "value = 1\n"),))
        self.assertEqual(proposal.title, "Tighten worker")
        self.assertEqual(proposal.changes[0].content, "value = 2\n")

    def test_local_provider_accepts_json_fence_but_rejects_fake_text(self) -> None:
        fenced = MockLocalTransport(
            ['```json\n{"changes":[{"path":"x.py","content":"x = 1"}]}\n```']
        )
        provider = LocalAIProvider(fenced, "pi-model")
        self.assertEqual(
            provider.generate_code(CodeGenerationRequest("write x", ("x.py",)))[0].path,
            "x.py",
        )

        invalid = LocalAIProvider(MockLocalTransport(["I cannot do that"]), "pi-model")
        with self.assertRaises(LocalProviderResponseError):
            invalid.generate_code(CodeGenerationRequest("write x", ("x.py",)))

    def test_settings_configure_local_endpoint_and_process(self) -> None:
        environment = {
            "JARVIS_LOCAL_PROVIDER_ENABLED": "true",
            "JARVIS_LOCAL_PROVIDER_MODE": "endpoint",
            "JARVIS_LOCAL_ENDPOINT": "http://127.0.0.1:9000/generate",
            "JARVIS_LOCAL_MODEL_NAME": "tiny-pi",
            "JARVIS_LOCAL_PROVIDER_TIMEOUT": "12.5",
        }
        with patch.dict(os.environ, environment, clear=False):
            settings = Settings.from_environment()
        self.assertTrue(settings.local_provider_enabled)
        self.assertEqual(settings.local_endpoint, environment["JARVIS_LOCAL_ENDPOINT"])
        self.assertEqual(settings.local_model_name, "tiny-pi")
        self.assertEqual(settings.local_provider_timeout_seconds, 12.5)

        process_settings = Settings(
            local_provider_enabled=True,
            local_provider_mode="process",
            local_process_command="python -m local_runtime --model tiny",
            local_model_name="tiny",
        )
        provider = LocalAIProvider.from_settings(process_settings)
        self.assertEqual(provider.model_name, "tiny")
        self.assertIsInstance(provider.transport, ProcessLocalModelTransport)
        self.assertEqual(
            provider.transport.command,
            ("python", "-m", "local_runtime", "--model", "tiny"),
        )

    def test_http_transport_rejects_non_local_endpoint(self) -> None:
        from jarvis.agent import HttpLocalModelTransport

        with self.assertRaises(ValueError):
            HttpLocalModelTransport("https://example.com/generate")


if __name__ == "__main__":
    unittest.main()
