"""Tests for RemoteLLMBrain — all run without a real API key or network.

Every LLM call is intercepted by MockLLMTransport so tests are hermetic.
Tests cover:
  - MockLLMTransport behaviour
  - OpenAICompatibleTransport and AnthropicTransport request construction
  - RemoteLLMBrain.create_plan JSON parsing and Plan assembly
  - RemoteLLMBrain.create_plan forces plan.goal == goal (Planner-safe)
  - RemoteLLMBrain.create_plan includes memory context and conversation history
  - RemoteLLMBrain.generate_code parsing
  - RemoteLLMBrain.propose_improvement parsing
  - Error paths: connection error, response error, missing key, bad JSON
  - build_remote_llm_brain raises RemoteLLMConfigError if API key absent
  - Settings fields for llm_enabled / llm_provider / llm_model
  - Full pipeline: RemoteLLMBrain.create_plan → Planner._validate passes
  - remember / recall tools integrated with ToolRegistry
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from jarvis.agent.remote_llm import (
    MockLLMTransport,
    RemoteLLMBrain,
    RemoteLLMConfigError,
    RemoteLLMConnectionError,
    RemoteLLMResponseError,
    build_remote_llm_brain,
)
from jarvis.config import Settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_plan_json(goal: str = "Check the system", steps: list | None = None) -> str:
    if steps is None:
        steps = [
            {
                "identifier": "step-1",
                "objective": "Describe capabilities",
                "tool_name": "echo",
                "argument": "System nominal.",
                "verification": "Output present",
                "max_retries": 0,
            }
        ]
    return json.dumps({"goal": goal, "steps": steps})


def _brain(responses: list[str]) -> RemoteLLMBrain:
    return RemoteLLMBrain(
        transport=MockLLMTransport(responses),
        model="test-model",
        provider_alias="openai",
        api_key="test-key-not-real",
        timeout_seconds=5.0,
    )


# ── MockLLMTransport ──────────────────────────────────────────────────────────

class TestMockLLMTransport(unittest.TestCase):

    def test_returns_queued_responses_in_order(self) -> None:
        t = MockLLMTransport(["first", "second"])
        r1 = t.chat_complete([], "m", "k", 5.0)
        r2 = t.chat_complete([], "m", "k", 5.0)
        self.assertEqual(r1, "first")
        self.assertEqual(r2, "second")

    def test_raises_when_queue_empty(self) -> None:
        t = MockLLMTransport([])
        with self.assertRaises(RemoteLLMConnectionError):
            t.chat_complete([], "m", "k", 5.0)

    def test_records_all_calls(self) -> None:
        t = MockLLMTransport(["a", "b"])
        msgs1 = [{"role": "user", "content": "hello"}]
        msgs2 = [{"role": "user", "content": "world"}]
        t.chat_complete(msgs1, "m", "k", 5.0)
        t.chat_complete(msgs2, "m", "k", 5.0)
        self.assertEqual(len(t.calls), 2)
        self.assertEqual(t.calls[0], msgs1)
        self.assertEqual(t.calls[1], msgs2)

    def test_remaining_count(self) -> None:
        t = MockLLMTransport(["a", "b", "c"])
        self.assertEqual(t.remaining(), 3)
        t.chat_complete([], "m", "k", 5.0)
        self.assertEqual(t.remaining(), 2)


# ── RemoteLLMBrain — provider name ────────────────────────────────────────────

class TestRemoteLLMBrainProviderName(unittest.TestCase):

    def test_provider_name_format(self) -> None:
        brain = _brain([])
        self.assertEqual(brain.provider_name, "llm:openai:test-model")

    def test_provider_name_uses_provider_alias_and_model(self) -> None:
        brain = RemoteLLMBrain(
            transport=MockLLMTransport([]),
            model="claude-3-opus",
            provider_alias="anthropic",
            api_key="k",
        )
        self.assertEqual(brain.provider_name, "llm:anthropic:claude-3-opus")

    def test_rejects_empty_model(self) -> None:
        with self.assertRaises(ValueError):
            _brain_custom = RemoteLLMBrain(
                transport=MockLLMTransport([]),
                model="   ",
                provider_alias="openai",
                api_key="k",
            )

    def test_rejects_empty_api_key(self) -> None:
        with self.assertRaises(RemoteLLMConfigError):
            RemoteLLMBrain(
                transport=MockLLMTransport([]),
                model="gpt-4o-mini",
                provider_alias="openai",
                api_key="",
            )


# ── RemoteLLMBrain — create_plan ──────────────────────────────────────────────

class TestCreatePlan(unittest.TestCase):

    def _plan(self, json_str: str, goal: str = "Check the system"):
        brain = _brain([json_str])
        return brain.create_plan(goal, ())

    def test_returns_plan_with_expected_fields(self) -> None:
        plan = self._plan(_valid_plan_json())
        self.assertEqual(plan.goal, "Check the system")
        self.assertEqual(plan.provider, "llm:openai:test-model")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].identifier, "step-1")
        self.assertEqual(plan.steps[0].tool_name, "echo")

    def test_forces_plan_goal_to_equal_input_goal(self) -> None:
        # Even if the LLM paraphrases the goal, plan.goal must match exactly.
        json_str = _valid_plan_json(goal="DIFFERENT GOAL — LLM paraphrased it")
        plan = self._plan(json_str, goal="Check the system")
        self.assertEqual(plan.goal, "Check the system")

    def test_multiple_steps_parsed_correctly(self) -> None:
        steps = [
            {"identifier": "recall-name", "objective": "Recall name", "tool_name": "recall",
             "argument": "name", "verification": "Has output", "max_retries": 0},
            {"identifier": "echo-name", "objective": "Output name", "tool_name": "echo",
             "argument": "Your name is recalled.", "verification": "Output present", "max_retries": 0},
        ]
        plan = self._plan(_valid_plan_json(steps=steps), goal="What is my name?")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].tool_name, "recall")
        self.assertEqual(plan.steps[1].tool_name, "echo")

    def test_accepts_markdown_fenced_json(self) -> None:
        fenced = f"```json\n{_valid_plan_json()}\n```"
        plan = self._plan(fenced)
        self.assertEqual(len(plan.steps), 1)

    def test_raises_response_error_on_invalid_json(self) -> None:
        brain = _brain(["not json at all"])
        with self.assertRaises(RemoteLLMResponseError):
            brain.create_plan("goal", ())

    def test_raises_response_error_when_steps_missing(self) -> None:
        brain = _brain([json.dumps({"goal": "g"})])
        with self.assertRaises(RemoteLLMResponseError):
            brain.create_plan("g", ())

    def test_raises_response_error_when_step_missing_identifier(self) -> None:
        bad = json.dumps({"goal": "g", "steps": [{"objective": "x", "tool_name": "echo"}]})
        brain = _brain([bad])
        with self.assertRaises(RemoteLLMResponseError):
            brain.create_plan("g", ())

    def test_raises_response_error_on_non_dict_json(self) -> None:
        brain = _brain([json.dumps([1, 2, 3])])
        with self.assertRaises(RemoteLLMResponseError):
            brain.create_plan("goal", ())

    def test_connection_error_propagates(self) -> None:
        brain = _brain([])  # empty queue → MockLLMTransport raises
        with self.assertRaises(RemoteLLMConnectionError):
            brain.create_plan("goal", ())

    def test_memory_context_appears_in_system_prompt(self) -> None:
        transport = MockLLMTransport([_valid_plan_json()])
        brain = RemoteLLMBrain(transport, "m", "openai", "k")
        brain.create_plan("Check system", memory_context=("name: San", "favourite colour: blue"))
        system_msg = transport.calls[0][0]
        self.assertEqual(system_msg["role"], "system")
        self.assertIn("name: San", system_msg["content"])
        self.assertIn("favourite colour: blue", system_msg["content"])

    def test_empty_memory_context_shows_placeholder(self) -> None:
        transport = MockLLMTransport([_valid_plan_json()])
        brain = RemoteLLMBrain(transport, "m", "openai", "k")
        brain.create_plan("Check system", memory_context=())
        system_msg = transport.calls[0][0]
        self.assertIn("no relevant memories", system_msg["content"])


# ── Conversation history ──────────────────────────────────────────────────────

class TestConversationHistory(unittest.TestCase):

    def test_second_call_includes_first_exchange_in_messages(self) -> None:
        transport = MockLLMTransport([
            _valid_plan_json(goal="First goal"),
            _valid_plan_json(goal="Second goal"),
        ])
        brain = RemoteLLMBrain(transport, "m", "openai", "k")
        brain.create_plan("First goal", ())
        brain.create_plan("Second goal", ())

        second_call_messages = transport.calls[1]
        roles = [m["role"] for m in second_call_messages]
        # system, user(first goal), assistant(first response), user(second goal)
        self.assertIn("system", roles)
        user_msgs = [m for m in second_call_messages if m["role"] == "user"]
        self.assertEqual(len(user_msgs), 2)
        self.assertEqual(user_msgs[0]["content"], "First goal")
        self.assertEqual(user_msgs[1]["content"], "Second goal")

    def test_history_is_bounded(self) -> None:
        """History must not grow without bound."""
        responses = [_valid_plan_json(goal=f"Goal {i}") for i in range(10)]
        transport = MockLLMTransport(responses)
        brain = RemoteLLMBrain(transport, "m", "openai", "k")
        for i in range(10):
            brain.create_plan(f"Goal {i}", ())
        # Final call should have at most system + HISTORY_LIMIT + 1 user messages
        last_call = transport.calls[-1]
        # system message + at most 6 history + 1 current user = max 8 total
        self.assertLessEqual(len(last_call), 9)


# ── generate_code ─────────────────────────────────────────────────────────────

class TestGenerateCode(unittest.TestCase):

    def test_parses_valid_code_response(self) -> None:
        payload = json.dumps({
            "changes": [{"path": "jarvis/tools/custom.py", "content": "# stub"}]
        })
        brain = _brain([payload])
        from jarvis.agent.models import CodeGenerationRequest
        request = CodeGenerationRequest(
            goal="Add a stub tool",
            existing_files={},
            allowed_files=["jarvis/tools/custom.py"],
        )
        changes = brain.generate_code(request)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, "jarvis/tools/custom.py")

    def test_raises_on_missing_changes_key(self) -> None:
        brain = _brain([json.dumps({"nope": []})])
        from jarvis.agent.models import CodeGenerationRequest
        request = CodeGenerationRequest(goal="g", existing_files={}, allowed_files=["f.py"])
        with self.assertRaises(RemoteLLMResponseError):
            brain.generate_code(request)


# ── propose_improvement ───────────────────────────────────────────────────────

class TestProposeImprovement(unittest.TestCase):

    def test_parses_valid_improvement_response(self) -> None:
        payload = json.dumps({
            "title": "Add caching",
            "rationale": "Speeds up repeated queries.",
            "changes": [{"path": "jarvis/cache.py", "content": "# cache stub"}],
        })
        brain = _brain([payload])
        from jarvis.agent.models import ExecutionReport
        report = ExecutionReport(goal="speed up", success=True, steps=())
        proposal = brain.propose_improvement(report, ())
        self.assertEqual(proposal.title, "Add caching")
        self.assertEqual(proposal.provider, "llm:openai:test-model")


# ── build_remote_llm_brain ────────────────────────────────────────────────────

class TestBuildRemoteLLMBrain(unittest.TestCase):

    def test_raises_config_error_when_api_key_absent(self) -> None:
        settings = Settings(llm_enabled=True, llm_provider="openai", llm_model="gpt-4o-mini")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_LLM_API_KEY", None)
            with self.assertRaises(RemoteLLMConfigError):
                build_remote_llm_brain(settings)

    def test_raises_config_error_when_api_key_blank(self) -> None:
        settings = Settings(llm_enabled=True, llm_provider="openai", llm_model="gpt-4o-mini")
        with patch.dict(os.environ, {"JARVIS_LLM_API_KEY": "   "}):
            with self.assertRaises(RemoteLLMConfigError):
                build_remote_llm_brain(settings)

    def test_builds_brain_when_api_key_present(self) -> None:
        settings = Settings(llm_enabled=True, llm_provider="openai", llm_model="gpt-4o-mini")
        with patch.dict(os.environ, {"JARVIS_LLM_API_KEY": "sk-test"}):
            brain = build_remote_llm_brain(settings)
        self.assertEqual(brain.provider_name, "llm:openai:gpt-4o-mini")

    def test_anthropic_provider_builds_brain(self) -> None:
        settings = Settings(
            llm_enabled=True, llm_provider="anthropic", llm_model="claude-3-haiku-20240307"
        )
        with patch.dict(os.environ, {"JARVIS_LLM_API_KEY": "sk-ant-test"}):
            brain = build_remote_llm_brain(settings)
        self.assertIn("anthropic", brain.provider_name)

    def test_groq_provider_builds_brain(self) -> None:
        settings = Settings(
            llm_enabled=True, llm_provider="groq", llm_model="llama-3.3-70b-versatile"
        )
        with patch.dict(os.environ, {"JARVIS_LLM_API_KEY": "gsk_test"}):
            brain = build_remote_llm_brain(settings)
        self.assertIn("groq", brain.provider_name)


# ── Settings fields ───────────────────────────────────────────────────────────

class TestSettingsLLMFields(unittest.TestCase):

    def test_defaults(self) -> None:
        s = Settings()
        self.assertFalse(s.llm_enabled)
        self.assertEqual(s.llm_provider, "openai")
        self.assertEqual(s.llm_model, "gpt-4o-mini")

    def test_from_environment_reads_vars(self) -> None:
        env = {
            "JARVIS_LLM_ENABLED": "true",
            "JARVIS_LLM_PROVIDER": "anthropic",
            "JARVIS_LLM_MODEL": "claude-3-haiku-20240307",
        }
        with patch.dict(os.environ, env):
            s = Settings.from_environment()
        self.assertTrue(s.llm_enabled)
        self.assertEqual(s.llm_provider, "anthropic")
        self.assertEqual(s.llm_model, "claude-3-haiku-20240307")

    def test_llm_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_LLM_ENABLED", None)
            s = Settings.from_environment()
        self.assertFalse(s.llm_enabled)


# ── Planner integration ───────────────────────────────────────────────────────

class TestPlannerIntegration(unittest.TestCase):
    """Verify that plans from RemoteLLMBrain pass Planner._validate."""

    def test_plan_passes_planner_validation(self) -> None:
        import tempfile
        from pathlib import Path
        from jarvis.agent.planner import Planner
        from jarvis.memory.store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            brain = _brain([_valid_plan_json(goal="Check the system")])
            planner = Planner(brain, MemoryStore(Path(tmp) / "mem.json"))
            plan = planner.create_plan("Check the system")
        self.assertEqual(plan.goal, "Check the system")
        self.assertGreater(len(plan.steps), 0)

    def test_plan_with_remember_step_passes_validation(self) -> None:
        import tempfile
        from pathlib import Path
        from jarvis.agent.planner import Planner
        from jarvis.memory.store import MemoryStore

        steps = [
            {"identifier": "store-name", "objective": "Store name in memory",
             "tool_name": "remember", "argument": "my name is San",
             "verification": "Memory stored", "max_retries": 0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            brain = _brain([_valid_plan_json(goal="Remember that my name is San", steps=steps)])
            planner = Planner(brain, MemoryStore(Path(tmp) / "mem.json"))
            plan = planner.create_plan("Remember that my name is San")
        self.assertEqual(plan.steps[0].tool_name, "remember")


# ── Tool registry: remember / recall ─────────────────────────────────────────

class TestRememberRecallTools(unittest.TestCase):

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        from jarvis.config import Settings
        from jarvis.memory.store import MemoryStore
        from jarvis.sandbox.runner import Sandbox
        from jarvis.tools.builtin import build_default_registry
        from jarvis.tools.registry import ToolContext

        self._tmp = tempfile.mkdtemp()
        self._registry = build_default_registry()
        self._context = ToolContext(
            settings=Settings(),
            memory=MemoryStore(Path(self._tmp) / "mem.json"),
            sandbox=Sandbox(workspace_root=Path(self._tmp), timeout_seconds=5.0),
        )

    def test_registry_includes_remember_and_recall(self) -> None:
        names = self._registry.names()
        self.assertIn("remember", names)
        self.assertIn("recall", names)

    def test_remember_stores_fact_and_returns_output(self) -> None:
        result = self._registry.execute("remember", "my name is San", self._context)
        self.assertTrue(result.ok)
        self.assertIn("San", result.output)

    def test_recall_retrieves_stored_fact(self) -> None:
        self._registry.execute("remember", "my name is San", self._context)
        result = self._registry.execute("recall", "name", self._context)
        self.assertTrue(result.ok)
        self.assertIn("San", result.output)

    def test_recall_empty_query_lists_all(self) -> None:
        self._registry.execute("remember", "fact one", self._context)
        self._registry.execute("remember", "fact two", self._context)
        result = self._registry.execute("recall", "", self._context)
        self.assertTrue(result.ok)
        self.assertIn("fact one", result.output)
        self.assertIn("fact two", result.output)

    def test_recall_no_memories_returns_ok_with_message(self) -> None:
        result = self._registry.execute("recall", "nothing", self._context)
        self.assertTrue(result.ok)
        self.assertIn("No matching", result.output)

    def test_remember_empty_argument_returns_error(self) -> None:
        result = self._registry.execute("remember", "", self._context)
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)


# ── Assistant brain selection priority ────────────────────────────────────────

class TestAssistantBrainSelection(unittest.TestCase):

    def test_demo_mode_takes_priority_over_llm(self) -> None:
        """demo_mode=True + llm_enabled=True → DemoBrain wins."""
        from jarvis.agent.demo import DemoBrain
        from jarvis.core.assistant import Assistant

        s = Settings(demo_mode=True, llm_enabled=True)
        a = Assistant(s)
        self.assertIsInstance(a.brain, DemoBrain)

    def test_llm_enabled_raises_config_error_without_key(self) -> None:
        """llm_enabled=True without JARVIS_LLM_API_KEY → RemoteLLMConfigError."""
        from jarvis.core.assistant import Assistant

        s = Settings(demo_mode=False, llm_enabled=True)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_LLM_API_KEY", None)
            with self.assertRaises(RemoteLLMConfigError):
                Assistant(s)

    def test_llm_mode_uses_remote_llm_brain(self) -> None:
        """llm_enabled=True with JARVIS_LLM_API_KEY → RemoteLLMBrain."""
        from jarvis.core.assistant import Assistant

        s = Settings(demo_mode=False, llm_enabled=True, llm_provider="openai",
                     llm_model="gpt-4o-mini")
        with patch.dict(os.environ, {"JARVIS_LLM_API_KEY": "sk-test"}):
            a = Assistant(s)
        self.assertTrue(a.brain.provider_name.startswith("llm:"))

    def test_no_mode_uses_unavailable_brain(self) -> None:
        """No demo, no llm, no local → UnavailableBrain."""
        from jarvis.agent.brain import UnavailableBrain
        from jarvis.core.assistant import Assistant

        s = Settings(demo_mode=False, llm_enabled=False, local_provider_enabled=False)
        a = Assistant(s)
        self.assertIsInstance(a.brain, UnavailableBrain)


if __name__ == "__main__":
    unittest.main()
