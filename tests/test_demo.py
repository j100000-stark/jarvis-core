"""Tests for DemoBrain and DemoProvider."""

from __future__ import annotations

import unittest

from jarvis.agent.demo import DEMO_LABEL, DEMO_PROVIDER_NAME, DemoBrain, DemoProvider
from jarvis.agent.models import ExecutionReport, StepReport, StepStatus, ToolResult, PlanStep


class TestDemoProvider(unittest.TestCase):
    def setUp(self):
        self.provider = DemoProvider()

    def test_provider_name(self):
        self.assertEqual(self.provider.provider_name, DEMO_PROVIDER_NAME)

    def test_is_available(self):
        self.assertTrue(self.provider.is_available())

    def test_complete_labels_as_demo(self):
        response = self.provider.complete("What should I do?")
        self.assertIn(DEMO_LABEL, response)

    def test_complete_does_not_claim_to_be_real_ai(self):
        response = self.provider.complete("test")
        self.assertNotIn("language model processed this", response.split(DEMO_LABEL)[0])
        self.assertIn("No language model processed this prompt", response)


class TestDemoBrain(unittest.TestCase):
    def setUp(self):
        self.brain = DemoBrain()

    def test_provider_name(self):
        self.assertEqual(self.brain.provider_name, DEMO_PROVIDER_NAME)

    def test_is_available(self):
        self.assertTrue(self.brain.is_available())

    def test_plan_labels_goal_as_demo(self):
        plan = self.brain.plan("do something")
        self.assertIn(DEMO_LABEL, plan.goal)
        self.assertEqual(plan.provider, DEMO_PROVIDER_NAME)

    def test_plan_has_steps(self):
        plan = self.brain.plan("do something")
        self.assertGreater(len(plan.steps), 0)

    def test_system_check_goal_gets_system_steps(self):
        plan = self.brain.plan("Check whether my computer is behaving normally.")
        step_ids = [s.identifier for s in plan.steps]
        self.assertTrue(any("collect" in sid or "analyze" in sid or "report" in sid for sid in step_ids))

    def test_security_goal_gets_security_steps(self):
        plan = self.brain.plan("Run a security assessment")
        step_ids = [s.identifier for s in plan.steps]
        self.assertTrue(any("sentinel" in sid or "invest" in sid or "check" in sid for sid in step_ids))

    def test_planning_goal_gets_planning_steps(self):
        plan = self.brain.plan("Prepare a concise plan for next steps")
        step_ids = [s.identifier for s in plan.steps]
        self.assertTrue(any("plan" in sid for sid in step_ids))

    def test_generic_goal_gets_generic_steps(self):
        plan = self.brain.plan("XYZ unknown goal 12345")
        self.assertGreater(len(plan.steps), 0)

    def test_generate_code_labels_as_demo(self):
        from jarvis.agent.models import CodeGenerationRequest
        req = CodeGenerationRequest(
            goal="fix a bug",
            allowed_files=("jarvis/tools/builtin.py",),
        )
        changes = self.brain.generate_code(req)
        self.assertEqual(len(changes), 1)
        self.assertIn(DEMO_LABEL, changes[0].content)

    def test_propose_improvement_labels_as_demo(self):
        step = PlanStep(
            identifier="s1",
            objective="obj",
            tool_name="time",
        )
        sr = StepReport(
            step=step,
            status=StepStatus.SUCCEEDED,
            attempts=1,
            result=ToolResult(ok=True, output="now"),
            verified=True,
        )
        report = ExecutionReport(
            goal="test goal",
            success=True,
            steps=(sr,),
        )
        proposal = self.brain.propose_improvement(report)
        self.assertIn(DEMO_LABEL, proposal.title)
        self.assertEqual(proposal.provider, DEMO_PROVIDER_NAME)

    def test_demo_brain_clearly_not_real_llm(self):
        # The plan goal must always carry the DEMO_LABEL
        for goal in [
            "status",
            "security scan",
            "plan my day",
            "something completely different",
        ]:
            plan = self.brain.plan(goal)
            self.assertIn(DEMO_LABEL, plan.goal, f"DEMO label missing for goal: {goal}")


if __name__ == "__main__":
    unittest.main()
