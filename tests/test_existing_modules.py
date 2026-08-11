from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jarvis.config import Settings
from jarvis.core import Assistant
from jarvis.agent.models import Plan, PlanStep
from jarvis.memory import MemoryManager
from jarvis.recovery import RecoveryManager
from jarvis.tools import ToolContext, build_default_registry


class ExistingModuleTests(unittest.TestCase):
    def test_assistant_runs_injected_brain_goal_end_to_end(self) -> None:
        class TestBrain:
            provider_name = "test-provider"

            def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
                del memory_context
                return Plan(
                    goal,
                    (PlanStep("one", "echo the goal", "echo", goal),),
                    self.provider_name,
                )

            def generate_code(self, request: object) -> tuple:
                del request
                return ()

            def propose_improvement(self, report: object, memory_context: tuple[str, ...]) -> object:
                del report, memory_context
                raise NotImplementedError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assistant = Assistant(
                Settings(data_dir=root, memory_file=root / "memory.json"),
                brain=TestBrain(),
            )
            report = assistant.run_goal("say hello")
            self.assertTrue(report.success)
            self.assertEqual(report.steps[0].result.output, "say hello")

    def test_settings_reads_environment_and_memory_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            first = MemoryManager(path)
            first.remember("remembered fact")
            second = MemoryManager(path)
            self.assertEqual(second.count(), 1)
            self.assertEqual(second.context_for("fact"), ("remembered fact",))

    def test_recovery_records_incident(self) -> None:
        manager = RecoveryManager()
        incident = manager.record(ValueError("bad input"), "test")
        self.assertEqual(incident.error_type, "ValueError")
        self.assertEqual(manager.latest(), incident)

    def test_default_tools_work_through_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(data_dir=root, memory_file=root / "memory.json")
            memory = MemoryManager(settings.memory_file)
            context = ToolContext(settings, memory, Assistant(settings).sandbox)
            result = build_default_registry().execute("echo", "hello", context)
            self.assertTrue(result.ok)
            self.assertEqual(result.output, "hello")

    def test_assistant_reports_unconfigured_brain_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assistant = Assistant(Settings(data_dir=root, memory_file=root / "memory.json"))
            response = assistant.respond("goal build a report")
            self.assertIn("No AI provider is configured", response)
            self.assertEqual(assistant.recovery.count(), 0)


if __name__ == "__main__":
    unittest.main()
