from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jarvis.agent import (
    AgentExecutor,
    BrainUnavailableError,
    CodeAgent,
    CodeChange,
    ExecutionReport,
    Planner,
    Plan,
    PlanStep,
    ProviderBrain,
    SelfImprovementManager,
    UnavailableBrain,
)
from jarvis.agent.models import CodeGenerationRequest, ImprovementProposal, ToolResult
from jarvis.config import Settings
from jarvis.memory import MemoryManager
from jarvis.recovery import RecoveryManager
from jarvis.rollback import RollbackManager
from jarvis.sandbox import Sandbox
from jarvis.tools import ToolContext, ToolRegistry


class ScriptedBrain:
    name = "test-provider"
    provider_name = name

    def __init__(self, plan: Plan | None = None, changes: tuple[CodeChange, ...] = ()) -> None:
        self.plan = plan
        self.changes = changes

    def create_plan(self, goal: str, memory_context: tuple[str, ...]) -> Plan:
        del memory_context
        if self.plan is None:
            raise AssertionError("No test plan configured")
        return self.plan

    def generate_code(self, request: CodeGenerationRequest) -> tuple[CodeChange, ...]:
        del request
        return self.changes

    def propose_improvement(
        self, report: ExecutionReport, memory_context: tuple[str, ...]
    ) -> ImprovementProposal:
        del report, memory_context
        return ImprovementProposal(
            "Improve test",
            "Test proposal",
            self.changes,
            self.name,
        )


class EchoTool:
    name = "echo"
    description = "echo"

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del context
        return ToolResult(ok=bool(argument), output=argument, error=None if argument else "empty")


class FailingTool:
    name = "fail"
    description = "fail"

    def run(self, argument: str, context: ToolContext) -> ToolResult:
        del argument, context
        return ToolResult(ok=False, error="intentional failure")


class BrainAndPlannerTests(unittest.TestCase):
    def test_provider_brain_delegates_to_provider(self) -> None:
        plan = Plan("goal", (), "test-provider")
        provider = ScriptedBrain(plan=plan)
        brain = ProviderBrain(provider)
        self.assertEqual(brain.provider_name, "test-provider")
        self.assertEqual(brain.create_plan("goal", ()).goal, "goal")

    def test_unavailable_brain_never_fakes_plan(self) -> None:
        with self.assertRaises(BrainUnavailableError):
            UnavailableBrain().create_plan("do something", ())

    def test_planner_normalizes_and_validates_plan(self) -> None:
        plan = Plan(
            "clean room",
            (PlanStep("one", "say it", "echo", "done", "has output"),),
            "test-provider",
        )
        with tempfile.TemporaryDirectory() as directory:
            memory = MemoryManager(Path(directory) / "memory.json")
            result = Planner(ScriptedBrain(plan), memory).create_plan("  clean   room ")
        self.assertEqual(result.steps[0].tool_name, "echo")

    def test_planner_rejects_duplicate_step_ids(self) -> None:
        plan = Plan(
            "goal",
            (
                PlanStep("same", "first", "echo"),
                PlanStep("same", "second", "echo"),
            ),
            "test-provider",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                Planner(
                    ScriptedBrain(plan),
                    MemoryManager(Path(directory) / "memory.json"),
                ).create_plan("goal")


class ExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.settings = Settings(data_dir=root, memory_file=root / "memory.json")
        self.memory = MemoryManager(self.settings.memory_file)
        self.sandbox = Sandbox(root)
        self.context = ToolContext(self.settings, self.memory, self.sandbox)
        self.recovery = RecoveryManager()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_executor_selects_registered_tool_and_verifies(self) -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        plan = Plan("say", (PlanStep("one", "say", "echo", "hello", "output"),), "test")
        report = AgentExecutor(registry, self.recovery).execute(plan, self.context)
        self.assertTrue(report.success)
        self.assertEqual(report.steps[0].result.output, "hello")

    def test_executor_stops_and_records_failed_step(self) -> None:
        registry = ToolRegistry()
        registry.register(FailingTool())
        plan = Plan("fail", (PlanStep("one", "fail", "fail", max_retries=1),), "test")
        report = AgentExecutor(registry, self.recovery).execute(plan, self.context)
        self.assertFalse(report.success)
        self.assertEqual(report.steps[0].attempts, 2)
        self.assertGreater(self.recovery.count(), 0)


class CodeAgentTests(unittest.TestCase):
    def test_code_agent_commits_valid_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sandbox = Sandbox(root)
            code_agent = CodeAgent(
                ScriptedBrain(changes=(CodeChange("work.py", "value = 1\n"),)),
                sandbox,
                RollbackManager(sandbox),
                RecoveryManager(),
            )
            result = code_agent.apply("create work file", ("work.py",))
            self.assertTrue(result.success)
            self.assertEqual((root / "work.py").read_text(), "value = 1\n")

    def test_code_agent_rolls_back_failed_sandbox_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "work.py"
            target.write_text("original = True\n")
            sandbox = Sandbox(root)
            original_test = sandbox.test_python_files
            sandbox.test_python_files = lambda paths: ToolResult(  # type: ignore[method-assign]
                ok=False,
                error="test failed",
            )
            recovery = RecoveryManager()
            code_agent = CodeAgent(
                ScriptedBrain(changes=(CodeChange("work.py", "changed = True\n"),)),
                sandbox,
                RollbackManager(sandbox),
                recovery,
            )
            result = code_agent.apply("break work file", ("work.py",))
            sandbox.test_python_files = original_test
            self.assertFalse(result.success)
            self.assertEqual(target.read_text(), "original = True\n")
            self.assertEqual(recovery.count(), 1)

    def test_code_agent_rejects_file_outside_allow_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sandbox = Sandbox(root)
            code_agent = CodeAgent(
                ScriptedBrain(changes=(CodeChange("other.py", "x = 1"),)),
                sandbox,
                RollbackManager(sandbox),
                RecoveryManager(),
            )
            with self.assertRaises(PermissionError):
                code_agent.apply("write elsewhere", ("allowed.py",))


class SelfImprovementTests(unittest.TestCase):
    def test_self_improvement_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryManager(root / "memory.json")
            sandbox = Sandbox(root)
            brain = ScriptedBrain(changes=(CodeChange("improve.py", "ok = True\n"),))
            code_agent = CodeAgent(brain, sandbox, RollbackManager(sandbox), RecoveryManager())
            manager = SelfImprovementManager(brain, memory, code_agent)
            report = ExecutionReport("goal", True, ())
            proposal = manager.propose(report)
            with self.assertRaises(PermissionError):
                manager.apply(proposal)
            result = manager.apply(proposal, approved=True)
            self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
