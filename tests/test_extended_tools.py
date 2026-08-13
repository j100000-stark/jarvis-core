"""Tests for V1 extended tools.

All network calls are avoided via patching or by disabling web_research.
The CalculateTool, AnalyzeTextTool, SystemStatusTool, and SecurityStatusTool
are tested without any mocking.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.agent.models import PlanStep, ToolResult
from jarvis.config import Settings
from jarvis.memory import MemoryManager
from jarvis.sandbox import Sandbox
from jarvis.tools.extended import (
    AnalyzeTextTool,
    CalculateTool,
    NetworkStatusTool,
    ReportTool,
    SecurityStatusTool,
    SystemStatusTool,
    WebResearchTool,
)
from jarvis.tools.registry import ToolContext


def _make_context(
    *,
    web_research_enabled: bool = False,
    demo_mode: bool = False,
) -> tuple[ToolContext, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    settings = Settings(
        data_dir=root,
        memory_file=root / "memory.json",
        web_research_enabled=web_research_enabled,
        demo_mode=demo_mode,
    )
    memory = MemoryManager(settings.memory_file)
    sandbox = Sandbox(workspace_root=root, timeout_seconds=5.0)
    ctx = ToolContext(settings=settings, memory=memory, sandbox=sandbox)
    return ctx, tmp


def _fake_step() -> PlanStep:
    return PlanStep("s1", "test objective", "test_tool", "test content")


# ─────────────────────────────────────────────
# SystemStatusTool
# ─────────────────────────────────────────────

class TestSystemStatusTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = SystemStatusTool()

    def test_name_and_description(self) -> None:
        self.assertEqual(self.tool.name, "system_status")
        self.assertIn("runtime", self.tool.description.lower())

    def test_returns_ok_result(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            result = self.tool.run("", ctx)
        self.assertTrue(result.ok)
        self.assertIn("Time (UTC):", result.output)

    def test_includes_memory_count(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            ctx.memory.remember("test fact")
            result = self.tool.run("", ctx)
        self.assertIn("Memories stored: 1", result.output)

    def test_includes_version(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            result = self.tool.run("", ctx)
        self.assertIn("JARVIS", result.output)

    def test_shows_web_research_enabled(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=True)
        with tmp:
            result = self.tool.run("", ctx)
        self.assertIn("Web research: enabled", result.output)

    def test_shows_web_research_disabled(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=False)
        with tmp:
            result = self.tool.run("", ctx)
        self.assertIn("Web research: disabled", result.output)

    def test_verify_ok_with_time(self) -> None:
        result = ToolResult(ok=True, output="Time (UTC): 2024-01-01T00:00:00+00:00")
        self.assertTrue(self.tool.verify(result, _fake_step()))

    def test_verify_fails_without_time(self) -> None:
        result = ToolResult(ok=True, output="no time here")
        self.assertFalse(self.tool.verify(result, _fake_step()))

    def test_shows_tiered_memory_counts(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            ctx.memory.remember("lt fact", tier="long_term")
            ctx.memory.remember("episodic event", tier="episodic")
            result = self.tool.run("", ctx)
        self.assertIn("long-term: 1", result.output)
        self.assertIn("episodic:  1", result.output)


# ─────────────────────────────────────────────
# NetworkStatusTool
# ─────────────────────────────────────────────

class TestNetworkStatusTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = NetworkStatusTool()

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "network_status")

    def test_online_when_hosts_reachable(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            with patch("jarvis.tools.extended.socket.create_connection"):
                result = self.tool.run("", ctx)
        self.assertTrue(result.ok)
        self.assertIn("online", result.output)
        self.assertIn("reachable", result.output)

    def test_offline_when_all_hosts_fail(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            with patch(
                "jarvis.tools.extended.socket.create_connection",
                side_effect=OSError("connection refused"),
            ):
                result = self.tool.run("", ctx)
        self.assertTrue(result.ok)
        self.assertIn("offline", result.output)
        self.assertIn("unreachable", result.output)

    def test_mixed_result(self) -> None:
        ctx, tmp = _make_context()
        call_count = [0]

        def side_effect(addr, timeout):  # noqa: ANN001
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock().__enter__()
            raise OSError("unreachable")

        with tmp:
            with patch("jarvis.tools.extended.socket.create_connection", side_effect=side_effect):
                result = self.tool.run("", ctx)
        self.assertTrue(result.ok)
        # At least one host showed up
        self.assertIn("Network:", result.output)

    def test_verify_ok(self) -> None:
        result = ToolResult(ok=True, output="Network: online\n  reachable: 1.1.1.1")
        self.assertTrue(self.tool.verify(result, _fake_step()))

    def test_verify_fails_without_prefix(self) -> None:
        result = ToolResult(ok=True, output="no network info")
        self.assertFalse(self.tool.verify(result, _fake_step()))


# ─────────────────────────────────────────────
# CalculateTool
# ─────────────────────────────────────────────

class TestCalculateTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = CalculateTool()
        ctx, self._tmp = _make_context()
        self.ctx = ctx

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _calc(self, expr: str) -> ToolResult:
        return self.tool.run(expr, self.ctx)

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "calculate")

    def test_addition(self) -> None:
        r = self._calc("2 + 3")
        self.assertTrue(r.ok)
        self.assertIn("= 5", r.output)

    def test_subtraction(self) -> None:
        r = self._calc("10 - 4")
        self.assertIn("= 6", r.output)

    def test_multiplication(self) -> None:
        r = self._calc("6 * 7")
        self.assertIn("= 42", r.output)

    def test_division(self) -> None:
        r = self._calc("10 / 4")
        self.assertTrue(r.ok)
        self.assertIn("2.5", r.output)

    def test_power(self) -> None:
        r = self._calc("2 ** 10")
        self.assertIn("= 1024", r.output)

    def test_modulo(self) -> None:
        r = self._calc("17 % 5")
        self.assertIn("= 2", r.output)

    def test_floor_division(self) -> None:
        r = self._calc("17 // 5")
        self.assertIn("= 3", r.output)

    def test_complex_expression(self) -> None:
        r = self._calc("(2 + 3) * 4 - 1")
        self.assertIn("= 19", r.output)

    def test_division_by_zero(self) -> None:
        r = self._calc("1 / 0")
        self.assertFalse(r.ok)
        self.assertIn("Cannot evaluate", r.error)

    def test_invalid_expression(self) -> None:
        r = self._calc("import os")
        self.assertFalse(r.ok)

    def test_string_argument_rejected(self) -> None:
        r = self._calc("'hello'")
        self.assertFalse(r.ok)

    def test_function_call_rejected(self) -> None:
        r = self._calc("abs(-1)")
        self.assertFalse(r.ok)

    def test_empty_argument(self) -> None:
        r = self._calc("")
        self.assertFalse(r.ok)
        self.assertIn("Usage:", r.error)

    def test_negative_number(self) -> None:
        r = self._calc("-5 + 3")
        self.assertIn("= -2", r.output)

    def test_integer_output_for_whole_float(self) -> None:
        r = self._calc("10 / 2")
        # 5.0 should be shown as 5
        self.assertIn("= 5", r.output)
        self.assertNotIn("5.0", r.output)

    def test_verify(self) -> None:
        result = ToolResult(ok=True, output="2 + 2 = 4")
        self.assertTrue(self.tool.verify(result, _fake_step()))

    def test_verify_fails_on_error(self) -> None:
        result = ToolResult(ok=False, error="bad expr")
        self.assertFalse(self.tool.verify(result, _fake_step()))


# ─────────────────────────────────────────────
# AnalyzeTextTool
# ─────────────────────────────────────────────

class TestAnalyzeTextTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = AnalyzeTextTool()
        ctx, self._tmp = _make_context()
        self.ctx = ctx

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "analyze_text")

    def test_word_count(self) -> None:
        r = self.tool.run("hello world foo bar", self.ctx)
        self.assertTrue(r.ok)
        self.assertIn("Words: 4", r.output)

    def test_char_count(self) -> None:
        r = self.tool.run("abc", self.ctx)
        self.assertIn("Characters: 3", r.output)

    def test_empty_argument(self) -> None:
        r = self.tool.run("", self.ctx)
        self.assertFalse(r.ok)
        self.assertIn("Usage:", r.error)

    def test_top_keywords_exclude_stop_words(self) -> None:
        r = self.tool.run("the cat sat on the mat the cat", self.ctx)
        self.assertIn("cat", r.output.lower())
        # "the" is a stop word — should not appear in keywords
        lines = {
            line.split(":")[0].strip(): line.split(":")[1].strip()
            for line in r.output.splitlines()
            if ":" in line
        }
        keywords = lines.get("Top keywords", "")
        self.assertNotIn("the(", keywords)

    def test_verify(self) -> None:
        result = ToolResult(ok=True, output="Words: 5\nCharacters: 20")
        self.assertTrue(self.tool.verify(result, _fake_step()))

    def test_multiple_sentences(self) -> None:
        r = self.tool.run("Hello world. This is great! Really?", self.ctx)
        self.assertIn("Sentences", r.output)


# ─────────────────────────────────────────────
# WebResearchTool
# ─────────────────────────────────────────────

class TestWebResearchTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = WebResearchTool()

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "web_research")

    def test_disabled_returns_clear_message(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=False)
        with tmp:
            r = self.tool.run("python programming", ctx)
        self.assertFalse(r.ok)
        self.assertIn("not currently enabled", r.error)

    def test_empty_query_returns_error(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=True)
        with tmp:
            r = self.tool.run("", ctx)
        self.assertFalse(r.ok)
        self.assertIn("Usage:", r.error)

    def test_url_fetch_success(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=True)

        class _FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self, n=None):
                return b"<html><body>Hello world</body></html>"
            @property
            def headers(self):
                class H:
                    def get_content_type(self):
                        return "text/html"
                return H()

        with tmp:
            with patch("jarvis.tools.extended.urllib.request.urlopen", return_value=_FakeResp()):
                r = self.tool.run("https://example.com", ctx)
        self.assertTrue(r.ok)
        self.assertIn("Fetched: https://example.com", r.output)

    def test_url_http_error_reported_honestly(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=True)
        with tmp:
            with patch(
                "jarvis.tools.extended.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError("url", 404, "Not Found", {}, None),
            ):
                r = self.tool.run("https://example.com/missing", ctx)
        self.assertFalse(r.ok)
        self.assertIn("404", r.error)

    def test_query_uses_duckduckgo(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=True)
        fake_response = json.dumps({
            "AbstractText": "Python is a programming language.",
            "AbstractURL": "https://en.wikipedia.org/wiki/Python",
            "Answer": "",
            "RelatedTopics": [],
        }).encode()

        class _FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self, n=None):
                return fake_response

        with tmp:
            with patch("jarvis.tools.extended.urllib.request.urlopen", return_value=_FakeResp()):
                r = self.tool.run("python programming language", ctx)
        self.assertTrue(r.ok)
        self.assertIn("DuckDuckGo", r.output)
        self.assertIn("Python is a programming language", r.output)

    def test_network_error_reported_honestly(self) -> None:
        ctx, tmp = _make_context(web_research_enabled=True)
        with tmp:
            with patch(
                "jarvis.tools.extended.urllib.request.urlopen",
                side_effect=urllib.error.URLError("network unreachable"),
            ):
                r = self.tool.run("https://example.com", ctx)
        self.assertFalse(r.ok)
        self.assertIn("Network error", r.error)

    def test_verify_success(self) -> None:
        result = ToolResult(ok=True, output="[Fetched: https://x.com]\nSome text")
        self.assertTrue(self.tool.verify(result, _fake_step()))

    def test_verify_failure(self) -> None:
        result = ToolResult(ok=False, error="HTTP 404")
        self.assertFalse(self.tool.verify(result, _fake_step()))


# ─────────────────────────────────────────────
# SecurityStatusTool
# ─────────────────────────────────────────────

class TestSecurityStatusTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = SecurityStatusTool()

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "security_status")

    def test_returns_ok(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            r = self.tool.run("", ctx)
        self.assertTrue(r.ok)
        self.assertIn("JARVIS V1", r.output)

    def test_lists_will_not_items(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            r = self.tool.run("", ctx)
        self.assertIn("JARVIS will NOT:", r.output)
        self.assertIn("fabricate", r.output)

    def test_shows_sandbox_status(self) -> None:
        ctx, tmp = _make_context()
        with tmp:
            r = self.tool.run("", ctx)
        self.assertIn("Sandbox enabled: yes", r.output)

    def test_verify(self) -> None:
        result = ToolResult(ok=True, output="JARVIS V1 — Security status\n...")
        self.assertTrue(self.tool.verify(result, _fake_step()))


# ─────────────────────────────────────────────
# ReportTool
# ─────────────────────────────────────────────

class TestReportTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = ReportTool()
        ctx, self._tmp = _make_context()
        self.ctx = ctx

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "report")

    def test_formats_content(self) -> None:
        r = self.tool.run("Everything is fine.", self.ctx)
        self.assertTrue(r.ok)
        self.assertIn("JARVIS REPORT", r.output)
        self.assertIn("Everything is fine.", r.output)

    def test_includes_timestamp(self) -> None:
        r = self.tool.run("Disk OK.", self.ctx)
        self.assertIn("Generated:", r.output)

    def test_empty_argument(self) -> None:
        r = self.tool.run("", self.ctx)
        self.assertFalse(r.ok)
        self.assertIn("Usage:", r.error)

    def test_verify(self) -> None:
        result = ToolResult(ok=True, output="━━━ JARVIS REPORT ━━━\nSome content")
        self.assertTrue(self.tool.verify(result, _fake_step()))


# ─────────────────────────────────────────────
# Registry integration
# ─────────────────────────────────────────────

class TestDefaultRegistryV1(unittest.TestCase):
    def test_all_v1_tools_registered(self) -> None:
        from jarvis.tools import build_default_registry
        registry = build_default_registry()
        names = registry.names()
        expected = [
            "analyze_text",
            "calculate",
            "echo",
            "network_status",
            "recall",
            "remember",
            "report",
            "security_status",
            "system_status",
            "time",
            "web_research",
        ]
        for name in expected:
            self.assertIn(name, names, f"Tool '{name}' missing from registry")

    def test_no_duplicate_names(self) -> None:
        from jarvis.tools import build_default_registry
        registry = build_default_registry()
        names = registry.names()
        self.assertEqual(len(names), len(set(names)))

    def test_all_tools_have_descriptions(self) -> None:
        from jarvis.tools import build_default_registry
        registry = build_default_registry()
        for name in registry.names():
            tool = registry.get(name)
            self.assertIsNotNone(tool)
            self.assertTrue(tool.description, f"Tool '{name}' has empty description")

    def test_calculate_works_through_registry(self) -> None:
        from jarvis.tools import build_default_registry
        registry = build_default_registry()
        ctx, tmp = _make_context()
        with tmp:
            result = registry.execute("calculate", "6 * 7", ctx)
        self.assertTrue(result.ok)
        self.assertIn("42", result.output)

    def test_system_status_works_through_registry(self) -> None:
        from jarvis.tools import build_default_registry
        registry = build_default_registry()
        ctx, tmp = _make_context()
        with tmp:
            result = registry.execute("system_status", "", ctx)
        self.assertTrue(result.ok)
        self.assertIn("JARVIS", result.output)

    def test_web_research_disabled_by_default(self) -> None:
        from jarvis.tools import build_default_registry
        registry = build_default_registry()
        ctx, tmp = _make_context(web_research_enabled=False)
        with tmp:
            result = registry.execute("web_research", "test query", ctx)
        self.assertFalse(result.ok)
        self.assertIn("not currently enabled", result.error)


if __name__ == "__main__":
    unittest.main()
