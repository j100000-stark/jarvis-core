"""Tests for the full-system-audit repairs.

Covers: planner unknown-tool rejection (fail before execution), the
web-research SSRF guard, the web-research disabled-by-default config, and
the live (cached) network probe in the system report.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from jarvis.agent.models import Plan, PlanStep
from jarvis.agent.planner import Planner
from jarvis.tools.extended import _assert_public_http_url


class _StubBrain:
    provider_name = "stub"

    def __init__(self, plan: Plan) -> None:
        self._plan = plan

    def create_plan(self, goal: str, memory_context) -> Plan:  # noqa: ANN001
        return self._plan


class _StubMemory:
    def search(self, query: str):  # noqa: ANN001
        return []

    def recent(self, limit: int = 8):  # noqa: ANN001
        return []


def _plan(tool: str) -> Plan:
    return Plan(
        goal="do the thing",
        provider="stub",
        steps=(
            PlanStep(
                identifier="s1", objective="obj", tool_name=tool,
                argument="", max_retries=0,
            ),
        ),
    )


class PlannerUnknownToolTests(unittest.TestCase):
    def test_unknown_tool_rejected_before_execution(self):
        planner = Planner(_StubBrain(_plan("does_not_exist")), _StubMemory())
        planner.set_known_tools(("respond", "remember"))
        with self.assertRaises(ValueError) as ctx:
            planner.create_plan("do the thing")
        self.assertIn("does_not_exist", str(ctx.exception))
        self.assertIn("before execution", str(ctx.exception))

    def test_known_tool_accepted_case_insensitively(self):
        planner = Planner(_StubBrain(_plan("Respond")), _StubMemory())
        planner.set_known_tools(("respond",))
        plan = planner.create_plan("do the thing")
        self.assertEqual(plan.steps[0].tool_name, "Respond")

    def test_no_known_tools_set_keeps_legacy_behavior(self):
        planner = Planner(_StubBrain(_plan("anything")), _StubMemory())
        plan = planner.create_plan("do the thing")
        self.assertEqual(len(plan.steps), 1)


class SsrfGuardTests(unittest.TestCase):
    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            _assert_public_http_url("file:///etc/passwd")

    def test_rejects_loopback(self):
        with self.assertRaises(ValueError):
            _assert_public_http_url("http://127.0.0.1/admin")
        with self.assertRaises(ValueError):
            _assert_public_http_url("http://localhost:8080/")

    def test_rejects_private_and_link_local(self):
        for url in ("http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/"):
            with self.assertRaises(ValueError):
                _assert_public_http_url(url)

    def test_accepts_public_address(self):
        # 1.1.1.1 is a global address; no DNS needed.
        _assert_public_http_url("https://1.1.1.1/")

    def test_redirect_to_private_address_blocked(self):
        import io
        import urllib.error
        from email.message import Message
        from jarvis.tools.extended import _fetch_url

        def fake_open(req, timeout):  # noqa: ANN001
            headers = Message()
            headers["Location"] = "http://127.0.0.1/admin"
            raise urllib.error.HTTPError(
                req.full_url, 302, "Found", headers, io.BytesIO(b"")
            )

        with patch("jarvis.tools.extended._open_no_redirect", fake_open):
            with self.assertRaises(ValueError) as ctx:
                _fetch_url("https://1.1.1.1/start")
        self.assertIn("non-public", str(ctx.exception))


class WebResearchDefaultTests(unittest.TestCase):
    def test_disabled_by_default(self):
        from jarvis.config.settings import Settings
        self.assertFalse(Settings().web_research_enabled)


class SystemReportNetworkProbeTests(unittest.TestCase):
    def test_probe_result_cached_and_live(self):
        import tempfile
        from pathlib import Path
        from jarvis.config.settings import Settings
        from jarvis.core.assistant import Assistant

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            settings = Settings(
                data_dir=data, memory_file=data / "memory.json", demo_mode=True,
            )
            assistant = Assistant(settings)
            calls = []

            def fake_probe():
                calls.append(1)
                from jarvis.agent.models import NetworkConnectivity, NetworkState
                assistant.network_recovery._connectivity = NetworkConnectivity.ONLINE
                return NetworkState(
                    connectivity=NetworkConnectivity.ONLINE,
                    reachable_hosts=("1.1.1.1",), unreachable_hosts=(),
                    details="probe",
                )

            with patch.object(assistant.network_recovery, "probe", fake_probe):
                r1 = assistant.system_report()
                r2 = assistant.system_report()
            self.assertEqual(r1["network"]["connectivity"], "online")
            self.assertEqual(r1["network"]["reachableHosts"], ["1.1.1.1"])
            self.assertEqual(len(calls), 1)  # second call served from cache
            self.assertEqual(r2["network"]["reachableHosts"], ["1.1.1.1"])


if __name__ == "__main__":
    unittest.main()
