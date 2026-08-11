"""Integration tests for DemoBrain end-to-end execution.

Covers:
- DemoBrain activation via JARVIS_DEMO_MODE
- DemoProvider status
- All canonical demo goals
- Agent orchestration flow
- Tool execution through safe boundary
- Verification of step outputs
- Memory steps
- System report with demo fields
- execute_goal_structured() JSON shape
- UI/API response shape contract
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _make_assistant(demo_mode: bool = True) -> "Assistant":
    from jarvis.config import Settings
    from jarvis.core import Assistant
    env = {"JARVIS_DEMO_MODE": "true" if demo_mode else "false"}
    with patch.dict(os.environ, env, clear=False):
        s = Settings.from_environment()
    return Assistant(s)


class TestDemoBrainActivation(unittest.TestCase):
    """DemoBrain is wired when JARVIS_DEMO_MODE=true."""

    def test_demo_mode_setting_true(self) -> None:
        from jarvis.config import Settings
        with patch.dict(os.environ, {"JARVIS_DEMO_MODE": "true"}, clear=False):
            s = Settings.from_environment()
        self.assertTrue(s.demo_mode)

    def test_demo_mode_setting_false(self) -> None:
        from jarvis.config import Settings
        with patch.dict(os.environ, {"JARVIS_DEMO_MODE": "false"}, clear=False):
            s = Settings.from_environment()
        self.assertFalse(s.demo_mode)

    def test_demo_mode_wires_demo_brain(self) -> None:
        from jarvis.agent.demo import DemoBrain
        assistant = _make_assistant(demo_mode=True)
        self.assertIsInstance(assistant.brain, DemoBrain)

    def test_non_demo_mode_does_not_wire_demo_brain(self) -> None:
        from jarvis.agent.demo import DemoBrain
        assistant = _make_assistant(demo_mode=False)
        self.assertNotIsInstance(assistant.brain, DemoBrain)

    def test_startup_message_includes_demo_label(self) -> None:
        from jarvis.agent.demo import DEMO_LABEL
        assistant = _make_assistant(demo_mode=True)
        msg = assistant.startup_message()
        self.assertIn(DEMO_LABEL, msg)

    def test_status_text_includes_demo_yes(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        status = assistant.status_text()
        self.assertIn("Demo mode: yes", status)
        self.assertIn("Brain provider: demo", status)

    def test_status_text_non_demo_says_no(self) -> None:
        assistant = _make_assistant(demo_mode=False)
        status = assistant.status_text()
        self.assertIn("Demo mode: no", status)


class TestDemoProviderStatus(unittest.TestCase):
    """DemoProvider behaves correctly as an AIProvider."""

    def test_provider_name(self) -> None:
        from jarvis.agent.demo import DemoProvider, DEMO_PROVIDER_NAME
        p = DemoProvider()
        self.assertEqual(p.provider_name, DEMO_PROVIDER_NAME)

    def test_is_available(self) -> None:
        from jarvis.agent.demo import DemoProvider
        p = DemoProvider()
        self.assertTrue(p.is_available())

    def test_complete_includes_demo_label(self) -> None:
        from jarvis.agent.demo import DemoProvider, DEMO_LABEL
        p = DemoProvider()
        out = p.complete("any prompt")
        self.assertIn(DEMO_LABEL, out)

    def test_demo_brain_provider_name(self) -> None:
        from jarvis.agent.demo import DemoBrain, DEMO_PROVIDER_NAME
        b = DemoBrain()
        self.assertEqual(b.provider_name, DEMO_PROVIDER_NAME)

    def test_demo_brain_is_available(self) -> None:
        from jarvis.agent.demo import DemoBrain
        b = DemoBrain()
        self.assertTrue(b.is_available())


class TestDemoGoalExecution(unittest.TestCase):
    """Each canonical demo goal produces expected steps and labelled output."""

    def _run(self, goal: str) -> "ExecutionReport":
        assistant = _make_assistant(demo_mode=True)
        return assistant.run_goal(goal)

    def test_system_check_goal(self) -> None:
        report = self._run("Check the system")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-collect", ids)
        self.assertIn("demo-analyze", ids)
        self.assertIn("demo-report", ids)

    def test_system_check_all_steps_verified(self) -> None:
        report = self._run("Check the system")
        for step in report.steps:
            with self.subTest(step=step.step.identifier):
                self.assertTrue(step.verified)

    def test_network_status_goal(self) -> None:
        report = self._run("Check network status")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-net-probe", ids)
        self.assertIn("demo-net-report", ids)

    def test_security_check_goal(self) -> None:
        report = self._run("Run a security check")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-sentinel", ids)
        self.assertIn("demo-investigate", ids)
        self.assertIn("demo-posture", ids)
        self.assertIn("demo-commander", ids)

    def test_memory_goal(self) -> None:
        report = self._run("Remember that my name is San")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-memory-store", ids)
        self.assertIn("demo-memory-confirm", ids)

    def test_system_report_goal(self) -> None:
        report = self._run("Give me a system report")
        self.assertTrue(report.success)
        # Should route to system-check (contains "system" and "report")
        ids = [s.step.identifier for s in report.steps]
        self.assertTrue(len(ids) >= 2)

    def test_planning_goal(self) -> None:
        report = self._run("Prepare a concise plan")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-plan", ids)

    def test_generic_goal(self) -> None:
        report = self._run("Do something completely unexpected")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-step-1", ids)
        self.assertIn("demo-step-2", ids)

    def test_step_outputs_include_demo_label(self) -> None:
        report = self._run("Check the system")
        for step in report.steps:
            with self.subTest(step=step.step.identifier):
                self.assertIn("[DEMO]", step.result.output)

    def test_all_steps_use_safe_tools_only(self) -> None:
        """All demo steps must use only echo or time (safe tools)."""
        from jarvis.agent.demo import DemoBrain
        brain = DemoBrain()
        safe_tools = {"echo", "time"}
        for goal in [
            "Check the system",
            "Check network status",
            "Run a security check",
            "Remember that my name is San",
            "Give me a system report",
            "Prepare a concise plan",
            "Something else entirely",
        ]:
            plan = brain.plan(goal)
            for step in plan.steps:
                with self.subTest(goal=goal, step=step.identifier):
                    self.assertIn(step.tool_name, safe_tools,
                                  f"Step {step.identifier!r} uses non-safe tool {step.tool_name!r}")

    def test_plan_goal_prefixed_with_demo_label(self) -> None:
        from jarvis.agent.demo import DemoBrain, DEMO_LABEL
        brain = DemoBrain()
        plan = brain.plan("Check the system")
        self.assertTrue(plan.goal.startswith(f"[{DEMO_LABEL}]"))


class TestAgentOrchestration(unittest.TestCase):
    """AgentOrchestrator selects and dispatches correctly in demo mode."""

    def _make_orchestrator(self):
        from jarvis.agent.orchestrator import AgentOrchestrator
        from jarvis.tools import build_default_registry
        from jarvis.recovery import RecoveryManager
        return AgentOrchestrator(build_default_registry(), RecoveryManager())

    def test_no_agents_registered_returns_successful_report(self) -> None:
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from jarvis.memory import MemoryManager
        from jarvis.sandbox import Sandbox

        orch = self._make_orchestrator()
        settings = Settings()
        ctx = ToolContext(
            settings=settings,
            memory=MemoryManager(settings.memory_file),
            sandbox=Sandbox(settings.data_dir.parent),
        )
        report = orch.run("any goal", ctx)
        self.assertTrue(report.success)
        self.assertEqual(report.agent_name, "AgentOrchestrator")

    def test_registered_agent_is_dispatched(self) -> None:
        from jarvis.agent.models import AgentTask, AgentReport
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from jarvis.memory import MemoryManager
        from jarvis.sandbox import Sandbox

        orch = self._make_orchestrator()
        dispatched: list[AgentTask] = []

        def my_agent(task: AgentTask) -> AgentReport:
            dispatched.append(task)
            return AgentReport(task_id=task.task_id, agent_name=task.agent_name,
                               success=True, summary="done")

        orch.register_agent("my-agent", ["special"], my_agent)
        settings = Settings()
        ctx = ToolContext(
            settings=settings,
            memory=MemoryManager(settings.memory_file),
            sandbox=Sandbox(settings.data_dir.parent),
        )
        report = orch.run("Do something special please", ctx)
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0].goal, "Do something special please")
        self.assertTrue(report.success)

    def test_failed_agent_produces_failed_report(self) -> None:
        from jarvis.agent.models import AgentTask, AgentReport
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from jarvis.memory import MemoryManager
        from jarvis.sandbox import Sandbox

        orch = self._make_orchestrator()

        def bad_agent(task: AgentTask) -> AgentReport:
            raise RuntimeError("agent exploded")

        orch.register_agent("bad-agent", ["explode"], bad_agent)
        settings = Settings()
        ctx = ToolContext(
            settings=settings,
            memory=MemoryManager(settings.memory_file),
            sandbox=Sandbox(settings.data_dir.parent),
        )
        report = orch.run("Please explode for me", ctx)
        self.assertFalse(report.success)

    def test_all_reports_accumulate(self) -> None:
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from jarvis.memory import MemoryManager
        from jarvis.sandbox import Sandbox

        orch = self._make_orchestrator()
        settings = Settings()
        ctx = ToolContext(
            settings=settings,
            memory=MemoryManager(settings.memory_file),
            sandbox=Sandbox(settings.data_dir.parent),
        )
        orch.run("goal one", ctx)
        orch.run("goal two", ctx)
        self.assertEqual(len(orch.all_reports()), 2)


class TestToolExecution(unittest.TestCase):
    """Demo steps use the registered echo/time tools correctly."""

    def _ctx(self):
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from jarvis.memory import MemoryManager
        from jarvis.sandbox import Sandbox
        s = Settings()
        return ToolContext(settings=s, memory=MemoryManager(s.memory_file), sandbox=Sandbox(s.data_dir.parent))

    def test_echo_tool_returns_argument(self) -> None:
        from jarvis.tools import build_default_registry
        reg = build_default_registry()
        result = reg.execute("echo", "hello world", self._ctx())
        self.assertTrue(result.ok)
        self.assertIn("hello world", result.output)

    def test_time_tool_returns_output(self) -> None:
        from jarvis.tools import build_default_registry
        reg = build_default_registry()
        result = reg.execute("time", "", self._ctx())
        self.assertTrue(result.ok)
        self.assertTrue(len(result.output) > 0)

    def test_executor_runs_demo_plan(self) -> None:
        from jarvis.agent.demo import DemoBrain
        from jarvis.agent.executor import AgentExecutor
        from jarvis.tools import build_default_registry
        from jarvis.recovery import RecoveryManager

        brain = DemoBrain()
        plan = brain.plan("Check the system")
        executor = AgentExecutor(build_default_registry(), RecoveryManager())
        report = executor.execute(plan, self._ctx())
        self.assertTrue(report.success)
        self.assertIsNone(report.failure)


class TestVerification(unittest.TestCase):
    """Step verification strings are present and match after execution."""

    def test_system_check_verifications(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.run_goal("Check the system")
        verifications = [s.step.verification for s in report.steps]
        self.assertIn("Status collected", verifications)
        self.assertIn("Analysis complete", verifications)
        self.assertIn("Report produced", verifications)

    def test_security_verifications(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.run_goal("Run a security check")
        verifications = [s.step.verification for s in report.steps]
        self.assertIn("Events collected", verifications)
        self.assertIn("Investigation complete", verifications)
        self.assertIn("Posture check complete", verifications)
        self.assertIn("Security report ready", verifications)

    def test_network_verifications(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.run_goal("Check network status")
        verifications = [s.step.verification for s in report.steps]
        self.assertIn("Network probe complete", verifications)
        self.assertIn("Network report ready", verifications)


class TestMemory(unittest.TestCase):
    """Memory operations work correctly in demo mode."""

    def test_remember_via_respond(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        resp = assistant.respond("remember my name is San")
        self.assertIn("Stored memory", resp)

    def test_recall_after_remember(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        assistant.respond("remember my name is San")
        resp = assistant.respond("recall San")
        self.assertIn("San", resp)

    def test_memory_count_increases(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        before = assistant.memory.count()
        assistant.respond("remember the sky is blue")
        self.assertEqual(assistant.memory.count(), before + 1)

    def test_demo_memory_goal_steps(self) -> None:
        """Memory demo goal executes echo steps, not real MemoryManager calls."""
        assistant = _make_assistant(demo_mode=True)
        report = assistant.run_goal("Remember that my name is San")
        self.assertTrue(report.success)
        ids = [s.step.identifier for s in report.steps]
        self.assertIn("demo-memory-store", ids)


class TestSystemReport(unittest.TestCase):
    """system_report() includes demo fields when demo_mode is enabled."""

    def test_demo_mode_true_in_report(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.system_report()
        self.assertTrue(report["demoMode"])

    def test_demo_label_in_report_when_demo(self) -> None:
        from jarvis.agent.demo import DEMO_LABEL
        assistant = _make_assistant(demo_mode=True)
        report = assistant.system_report()
        self.assertEqual(report["demoLabel"], DEMO_LABEL)

    def test_demo_mode_false_in_report(self) -> None:
        assistant = _make_assistant(demo_mode=False)
        report = assistant.system_report()
        self.assertFalse(report["demoMode"])

    def test_demo_label_none_when_not_demo(self) -> None:
        assistant = _make_assistant(demo_mode=False)
        report = assistant.system_report()
        self.assertIsNone(report["demoLabel"])

    def test_health_is_list(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.system_report()
        self.assertIsInstance(report["health"], list)

    def test_network_has_connectivity(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.system_report()
        self.assertIn("connectivity", report["network"])

    def test_security_keys_present(self) -> None:
        assistant = _make_assistant(demo_mode=True)
        report = assistant.system_report()
        sec = report["security"]
        for key in ("alertCount", "findingCount", "highestSeverity", "lastAssessmentAt"):
            with self.subTest(key=key):
                self.assertIn(key, sec)


class TestExecuteGoalStructured(unittest.TestCase):
    """execute_goal_structured() returns the correct JSON contract."""

    def _run(self, goal: str) -> dict:
        assistant = _make_assistant(demo_mode=True)
        return assistant.execute_goal_structured(goal)

    def test_required_top_level_keys(self) -> None:
        result = self._run("Check the system")
        for key in ("success", "goal", "response", "providerName",
                    "demoMode", "demoLabel", "executionSteps", "failure"):
            with self.subTest(key=key):
                self.assertIn(key, result)

    def test_success_true_for_demo_goal(self) -> None:
        result = self._run("Check the system")
        self.assertTrue(result["success"])

    def test_provider_name_is_demo(self) -> None:
        result = self._run("Check the system")
        self.assertEqual(result["providerName"], "demo")

    def test_demo_mode_true(self) -> None:
        result = self._run("Check the system")
        self.assertTrue(result["demoMode"])

    def test_demo_label_correct(self) -> None:
        from jarvis.agent.demo import DEMO_LABEL
        result = self._run("Check the system")
        self.assertEqual(result["demoLabel"], DEMO_LABEL)

    def test_execution_steps_is_list(self) -> None:
        result = self._run("Check the system")
        self.assertIsInstance(result["executionSteps"], list)

    def test_execution_steps_not_empty(self) -> None:
        result = self._run("Check the system")
        self.assertGreater(len(result["executionSteps"]), 0)

    def test_execution_step_fields(self) -> None:
        result = self._run("Check the system")
        step = result["executionSteps"][0]
        for field in ("stepId", "objective", "tool", "output", "error", "verified", "verification"):
            with self.subTest(field=field):
                self.assertIn(field, step)

    def test_execution_step_verified_true(self) -> None:
        result = self._run("Check the system")
        for step in result["executionSteps"]:
            with self.subTest(step=step["stepId"]):
                self.assertTrue(step["verified"])

    def test_failure_is_none_on_success(self) -> None:
        result = self._run("Check the system")
        self.assertIsNone(result["failure"])

    def test_response_includes_goal_completed(self) -> None:
        result = self._run("Check the system")
        self.assertIn("Goal completed", result["response"])

    def test_all_canonical_goals_succeed(self) -> None:
        for goal in [
            "Check the system",
            "Check network status",
            "Run a security check",
            "Remember that my name is San",
            "Give me a system report",
            "Prepare a concise plan",
        ]:
            with self.subTest(goal=goal):
                result = self._run(goal)
                self.assertTrue(result["success"], f"Goal failed: {goal} — {result.get('failure')}")

    def test_result_is_json_serialisable(self) -> None:
        result = self._run("Check the system")
        serialised = json.dumps(result)
        roundtrip = json.loads(serialised)
        self.assertEqual(result["success"], roundtrip["success"])
        self.assertEqual(result["providerName"], roundtrip["providerName"])

    def test_goal_json_cli_flag(self) -> None:
        """--goal-json produces valid JSON on stdout."""
        with patch.dict(os.environ, {"JARVIS_DEMO_MODE": "true"}, clear=False):
            from io import StringIO
            import sys
            from jarvis.main import main
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                main(["--goal-json", "Check the system"])
            finally:
                sys.stdout = old_stdout
            output = captured.getvalue()
        data = json.loads(output)
        self.assertTrue(data["success"])
        self.assertTrue(data["demoMode"])

    def test_system_report_cli_flag(self) -> None:
        """--system-report produces valid JSON with demoMode."""
        with patch.dict(os.environ, {"JARVIS_DEMO_MODE": "true"}, clear=False):
            from io import StringIO
            import sys
            from jarvis.main import main
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                main(["--system-report"])
            finally:
                sys.stdout = old_stdout
            output = captured.getvalue()
        data = json.loads(output)
        self.assertTrue(data["demoMode"])


if __name__ == "__main__":
    unittest.main()
