"""Tests for jarvis.diagnostics — secret redaction, error classification,
and structured error export.

Test categories:
  1. sanitize_message — redaction patterns
  2. sanitize_trace   — traceback redaction
  3. build_execution_error — component / code / recoverable / fields
  4. Integration: execute_goal_structured returns `error` field on exception
  5. Secret redaction never leaks env values into exported dicts
"""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from jarvis.diagnostics import (
    build_execution_error,
    sanitize_message,
    sanitize_trace,
)


# ── Minimal Incident stub ─────────────────────────────────────────────────────

@dataclass
class _FakeIncident:
    identifier: int
    error_type: str
    message: str
    operation: str
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat(timespec="seconds")


def _incident(
    error_type: str,
    operation: str,
    message: str = "test error",
    identifier: int = 42,
) -> _FakeIncident:
    return _FakeIncident(
        identifier=identifier,
        error_type=error_type,
        message=message,
        operation=operation,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. sanitize_message
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeMessage(unittest.TestCase):

    def test_redacts_sk_prefix_api_key(self):
        msg = "Error calling API: sk-abc123def456ghi789jkl012 was rejected"
        result = sanitize_message(msg)
        self.assertNotIn("sk-abc123def456ghi789jkl012", result)
        self.assertIn("[REDACTED]", result)

    def test_redacts_gsk_prefix_api_key(self):
        msg = "Groq rejected key gsk_abcdefghijklmnopqrstuvwx"
        result = sanitize_message(msg)
        self.assertNotIn("gsk_abcdefghijklmnopqrstuvwx", result)
        self.assertIn("[REDACTED]", result)

    def test_redacts_bearer_token(self):
        msg = "Authorization failed: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc"
        result = sanitize_message(msg)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc", result)

    def test_redacts_32_char_hex_key(self):
        msg = "ElevenLabs rejected key a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        result = sanitize_message(msg)
        self.assertNotIn("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", result)

    def test_preserves_normal_message(self):
        msg = "Brain returned a plan for a different goal."
        result = sanitize_message(msg)
        self.assertEqual(result, msg)

    def test_preserves_short_words(self):
        msg = "step-1 failed: tool not found"
        result = sanitize_message(msg)
        self.assertIn("step-1", result)
        self.assertIn("failed", result)

    def test_empty_string_returns_unchanged(self):
        self.assertEqual(sanitize_message(""), "")

    def test_redacts_env_value_if_secret_like(self):
        with patch.dict(os.environ, {"TEST_SECRET_KEY_DIAG": "sk-secretvalue1234567890abcdef"}):
            msg = "Key sk-secretvalue1234567890abcdef was rejected"
            result = sanitize_message(msg)
            self.assertNotIn("sk-secretvalue1234567890abcdef", result)


# ─────────────────────────────────────────────────────────────────────────────
# 2. sanitize_trace
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeTrace(unittest.TestCase):

    def test_redacts_api_key_in_traceback(self):
        trace = (
            'Traceback (most recent call last):\n'
            '  File "brain.py", line 42, in create_plan\n'
            '    headers = {"Authorization": "Bearer sk-abcdefghijklmnopqrstuvwxyz0123"}\n'
            'RemoteLLMConfigError: request failed\n'
        )
        result = sanitize_trace(trace)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz0123", result)

    def test_preserves_stack_frame_structure(self):
        trace = (
            'Traceback (most recent call last):\n'
            '  File "assistant.py", line 22, in execute\n'
            'ValueError: empty goal\n'
        )
        result = sanitize_trace(trace)
        self.assertIn("assistant.py", result)
        self.assertIn("ValueError", result)

    def test_empty_trace_returns_empty(self):
        self.assertEqual(sanitize_trace(""), "")


# ─────────────────────────────────────────────────────────────────────────────
# 3. build_execution_error — component / code / recoverable / fields
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildExecutionError(unittest.TestCase):

    # ── component inference ──────────────────────────────────────────────────

    def test_brain_unavailable_maps_to_brain_component(self):
        inc = _incident("BrainUnavailableError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["component"], "brain")

    def test_remote_llm_config_maps_to_brain_component(self):
        inc = _incident("RemoteLLMConfigError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["component"], "brain")

    def test_value_error_in_execute_maps_to_assistant(self):
        inc = _incident("ValueError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["component"], "assistant")

    def test_step_operation_maps_to_executor(self):
        inc = _incident("ToolExecutionError", "step:step-2")
        result = build_execution_error(inc)
        self.assertEqual(result["component"], "executor")

    def test_retry_operation_maps_to_executor(self):
        inc = _incident("RuntimeError", "retry:step-1")
        result = build_execution_error(inc)
        self.assertEqual(result["component"], "executor")

    def test_unknown_operation_returns_unknown(self):
        inc = _incident("Exception", "some_other_operation")
        result = build_execution_error(inc)
        self.assertEqual(result["component"], "unknown")

    # ── step extraction ──────────────────────────────────────────────────────

    def test_step_extracted_from_step_operation(self):
        inc = _incident("RuntimeError", "step:step-3")
        result = build_execution_error(inc)
        self.assertEqual(result["step"], "step-3")

    def test_step_extracted_from_retry_operation(self):
        inc = _incident("RuntimeError", "retry:step-1")
        result = build_execution_error(inc)
        self.assertEqual(result["step"], "step-1")

    def test_failing_step_kwarg_takes_precedence(self):
        inc = _incident("RuntimeError", "execute_goal_structured")
        result = build_execution_error(inc, failing_step="step-5")
        self.assertEqual(result["step"], "step-5")

    def test_no_step_for_planner_failure(self):
        inc = _incident("ValueError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertIsNone(result["step"])

    # ── error codes ──────────────────────────────────────────────────────────

    def test_brain_unavailable_code(self):
        inc = _incident("BrainUnavailableError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["code"], "BRAIN_UNAVAILABLE")

    def test_remote_llm_config_code(self):
        inc = _incident("RemoteLLMConfigError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["code"], "LLM_CONFIG_ERROR")

    def test_value_error_code(self):
        inc = _incident("ValueError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["code"], "VALIDATION_ERROR")

    def test_timeout_error_code(self):
        inc = _incident("TimeoutError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["code"], "TIMEOUT")

    def test_unknown_error_type_gets_generic_code(self):
        inc = _incident("SomeRandomError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["code"], "EXECUTION_ERROR")

    # ── recoverable flag ─────────────────────────────────────────────────────

    def test_brain_unavailable_is_not_recoverable(self):
        inc = _incident("BrainUnavailableError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertFalse(result["recoverable"])

    def test_remote_llm_config_is_not_recoverable(self):
        inc = _incident("RemoteLLMConfigError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertFalse(result["recoverable"])

    def test_value_error_is_recoverable(self):
        inc = _incident("ValueError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertTrue(result["recoverable"])

    def test_timeout_is_recoverable(self):
        inc = _incident("TimeoutError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertTrue(result["recoverable"])

    def test_generic_exception_is_recoverable(self):
        inc = _incident("Exception", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertTrue(result["recoverable"])

    # ── required fields ──────────────────────────────────────────────────────

    def test_all_required_fields_present(self):
        inc = _incident("ValueError", "execute_goal_structured")
        result = build_execution_error(inc)
        required = {"code", "type", "message", "component", "step", "recoverable",
                    "incidentId", "operation", "timestamp"}
        for field in required:
            self.assertIn(field, result, f"missing field: {field}")

    def test_incident_id_included(self):
        inc = _incident("ValueError", "execute_goal_structured", identifier=7)
        result = build_execution_error(inc)
        self.assertEqual(result["incidentId"], 7)

    def test_error_type_included(self):
        inc = _incident("BrainUnavailableError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["type"], "BrainUnavailableError")

    def test_operation_included(self):
        inc = _incident("ValueError", "execute_goal_structured")
        result = build_execution_error(inc)
        self.assertEqual(result["operation"], "execute_goal_structured")

    # ── secret redaction in output ───────────────────────────────────────────

    def test_message_is_sanitized_sk_key(self):
        inc = _incident(
            "ValueError",
            "execute_goal_structured",
            message="API call failed with key sk-abc123def456ghi789jkl012xyz",
        )
        result = build_execution_error(inc)
        self.assertNotIn("sk-abc123def456ghi789jkl012xyz", result["message"])

    def test_message_is_sanitized_bearer_token(self):
        inc = _incident(
            "RuntimeError",
            "execute_goal_structured",
            message="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghij was rejected",
        )
        result = build_execution_error(inc)
        self.assertNotIn(
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghij",
            result["message"],
        )

    def test_env_secret_redacted_from_message(self):
        with patch.dict(os.environ, {"MY_TEST_API_KEY_DIAG": "supersecrettoken1234567890abc"}):
            inc = _incident(
                "ValueError",
                "execute_goal_structured",
                message="Key supersecrettoken1234567890abc was invalid",
            )
            result = build_execution_error(inc)
            self.assertNotIn("supersecrettoken1234567890abc", result["message"])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Integration: assistant.execute_goal_structured returns `error` field
# ─────────────────────────────────────────────────────────────────────────────

def _make_assistant():
    """Build a minimal Assistant instance with injectable brain.

    Uses __new__ to avoid touching the filesystem or network during __init__.
    All attributes that execute_goal_structured / run_goal access must be set.
    """
    from jarvis.core.assistant import Assistant
    from jarvis.config.settings import Settings
    from jarvis.recovery.manager import RecoveryManager

    settings = Settings(demo_mode=False)
    assistant = Assistant.__new__(Assistant)
    assistant.recovery       = RecoveryManager()
    assistant.settings       = settings
    assistant.brain          = MagicMock()
    assistant.memory         = MagicMock()
    assistant.memory.search  = MagicMock(return_value=[])
    # sandbox is accessed inside ToolContext passed to executor.execute
    assistant.sandbox        = MagicMock()
    assistant.crash_recovery = MagicMock()
    return assistant


class TestExecuteGoalStructuredErrorField(unittest.TestCase):

    def test_planner_exception_returns_error_field(self):
        assistant = _make_assistant()
        assistant.brain.provider_name = "llm:groq:llama3"

        from jarvis.agent.planner import Planner
        assistant.planner = MagicMock(spec=Planner)
        assistant.planner.create_plan.side_effect = ValueError(
            "Brain returned a plan for a different goal."
        )

        result = assistant.execute_goal_structured("check the network")

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIsNotNone(result["error"])
        self.assertIsInstance(result["error"], dict)

    def test_error_field_has_correct_structure(self):
        assistant = _make_assistant()
        assistant.brain.provider_name = "llm:groq:llama3"

        from jarvis.agent.planner import Planner
        assistant.planner = MagicMock(spec=Planner)
        assistant.planner.create_plan.side_effect = ValueError("malformed plan")

        result = assistant.execute_goal_structured("test")
        err = result["error"]

        required = {"code", "type", "message", "component", "step", "recoverable",
                    "incidentId", "operation", "timestamp"}
        for field in required:
            self.assertIn(field, err, f"missing field: {field}")
        self.assertEqual(err["type"], "ValueError")
        self.assertEqual(err["code"], "VALIDATION_ERROR")
        self.assertTrue(err["recoverable"])

    def test_brain_unavailable_error_field_not_recoverable(self):
        assistant = _make_assistant()
        assistant.brain.provider_name = "llm:groq:llama3"

        class BrainUnavailableError(Exception):
            pass

        from jarvis.agent.planner import Planner
        assistant.planner = MagicMock(spec=Planner)
        assistant.planner.create_plan.side_effect = BrainUnavailableError(
            "no brain configured"
        )

        result = assistant.execute_goal_structured("test")
        err = result["error"]

        self.assertFalse(err["recoverable"])
        self.assertEqual(err["type"], "BrainUnavailableError")

    def test_error_message_sanitized_in_response(self):
        assistant = _make_assistant()
        assistant.brain.provider_name = "llm:groq:llama3"

        from jarvis.agent.planner import Planner
        assistant.planner = MagicMock(spec=Planner)
        assistant.planner.create_plan.side_effect = ValueError(
            "Auth failed with sk-realSecretKey123456789012345678"
        )

        result = assistant.execute_goal_structured("test")

        full_json = str(result)
        self.assertNotIn("sk-realSecretKey123456789012345678", full_json)

    def test_failure_string_is_sanitized_in_response(self):
        assistant = _make_assistant()
        assistant.brain.provider_name = "llm:groq:llama3"

        from jarvis.agent.planner import Planner
        assistant.planner = MagicMock(spec=Planner)
        assistant.planner.create_plan.side_effect = ValueError(
            "sk-anotherSecretApiKey987654321abcde"
        )

        result = assistant.execute_goal_structured("test")

        self.assertNotIn(
            "sk-anotherSecretApiKey987654321abcde",
            result.get("failure", ""),
        )

    def test_successful_execution_has_no_error_field(self):
        """Happy path: no `error` key (or it is None) when execution succeeds."""
        from jarvis.agent.models import (
            ExecutionReport,
            Plan,
            PlanStep,
            StepReport,
            StepStatus,
            ToolResult,
        )

        plan_step = PlanStep(
            identifier="step-1",
            objective="run system status",
            tool_name="system_status",
        )
        mock_plan = Plan(
            goal="test",
            steps=(plan_step,),
            provider="llm:groq:llama3",
        )
        mock_report = ExecutionReport(
            goal="test",
            success=True,
            steps=(
                StepReport(
                    step=plan_step,
                    status=StepStatus.SUCCEEDED,
                    attempts=1,
                    result=ToolResult(ok=True, output="all nominal"),
                    verified=True,
                ),
            ),
            failure=None,
        )

        assistant = _make_assistant()
        assistant.brain.provider_name = "llm:groq:llama3"

        from jarvis.agent.planner import Planner
        from jarvis.agent.executor import AgentExecutor
        assistant.planner = MagicMock(spec=Planner)
        assistant.planner.create_plan.return_value = mock_plan
        assistant.executor = MagicMock(spec=AgentExecutor)
        assistant.executor.execute.return_value = mock_report

        result = assistant.execute_goal_structured("test")

        self.assertTrue(result["success"])
        self.assertIsNone(result.get("error"))


if __name__ == "__main__":
    unittest.main()
