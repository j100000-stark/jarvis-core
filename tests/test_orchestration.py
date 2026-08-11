"""Tests for multi-agent orchestration and capability approval."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from jarvis.agent.models import (
    AgentReport,
    AgentTask,
    AlertSeverity,
    CapabilityRequest,
    ExecutionReport,
    ImprovementProposal,
    SecurityFinding,
)
from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.agent.self_improvement import SelfImprovementManager
from jarvis.recovery import RecoveryManager
from jarvis.tools import ToolRegistry


def _make_registry() -> ToolRegistry:
    from jarvis.tools.builtin import TimeTool
    reg = ToolRegistry()
    reg.register(TimeTool())
    return reg


def _make_orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator(
        registry=_make_registry(),
        recovery=RecoveryManager(),
    )


class TestAgentOrchestrator(unittest.TestCase):
    def test_no_agents_returns_honest_report(self):
        orch = _make_orchestrator()
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from pathlib import Path
        from jarvis.memory import MemoryStore
        from jarvis.sandbox import Sandbox
        import tempfile
        tmp = tempfile.mkdtemp()
        settings = Settings(name="j", version="0", data_dir=Path(tmp), memory_file=Path(tmp) / "m.json")
        context = ToolContext(
            settings=settings,
            memory=MemoryStore(Path(tmp) / "m.json"),
            sandbox=Sandbox(workspace_root=Path(tmp)),
        )
        report = orch.run("random unknown goal", context)
        self.assertTrue(report.success)
        self.assertIn("No specialized agents", report.summary)

    def test_matching_agent_is_dispatched(self):
        orch = _make_orchestrator()

        def mock_handler(task: AgentTask) -> AgentReport:
            return AgentReport(
                task_id=task.task_id,
                agent_name="MockAgent",
                success=True,
                summary="Mock agent ran",
            )

        orch.register_agent("MockAgent", keywords=["status", "check"], handler=mock_handler)

        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from pathlib import Path
        from jarvis.memory import MemoryStore
        from jarvis.sandbox import Sandbox
        import tempfile
        tmp = tempfile.mkdtemp()
        settings = Settings(name="j", version="0", data_dir=Path(tmp), memory_file=Path(tmp) / "m.json")
        context = ToolContext(
            settings=settings,
            memory=MemoryStore(Path(tmp) / "m.json"),
            sandbox=Sandbox(workspace_root=Path(tmp)),
        )
        report = orch.run("check system status", context)
        self.assertIn("MockAgent", report.raw_data.get("agents_used", ""))

    def test_failed_agent_is_handled_gracefully(self):
        orch = _make_orchestrator()

        def failing_handler(task: AgentTask) -> AgentReport:
            raise RuntimeError("Agent exploded")

        orch.register_agent("BadAgent", keywords=["bad"], handler=failing_handler)

        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from pathlib import Path
        from jarvis.memory import MemoryStore
        from jarvis.sandbox import Sandbox
        import tempfile
        tmp = tempfile.mkdtemp()
        settings = Settings(name="j", version="0", data_dir=Path(tmp), memory_file=Path(tmp) / "m.json")
        context = ToolContext(
            settings=settings,
            memory=MemoryStore(Path(tmp) / "m.json"),
            sandbox=Sandbox(workspace_root=Path(tmp)),
        )
        report = orch.run("bad agent goal", context)
        self.assertFalse(report.success)
        self.assertGreater(len(report.findings), 0)
        self.assertEqual(report.findings[0].category, "agent_error")

    def test_findings_accumulated_from_sub_reports(self):
        orch = _make_orchestrator()
        finding = SecurityFinding(
            identifier="F-01",
            category="test",
            title="Test finding",
            description="desc",
            severity=AlertSeverity.LOW,
        )

        def handler(task):
            return AgentReport(
                task_id=task.task_id,
                agent_name="A",
                success=True,
                summary="ok",
                findings=(finding,),
            )

        orch.register_agent("A", keywords=["analyze"], handler=handler)
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from pathlib import Path
        from jarvis.memory import MemoryStore
        from jarvis.sandbox import Sandbox
        import tempfile
        tmp = tempfile.mkdtemp()
        settings = Settings(name="j", version="0", data_dir=Path(tmp), memory_file=Path(tmp) / "m.json")
        context = ToolContext(
            settings=settings,
            memory=MemoryStore(Path(tmp) / "m.json"),
            sandbox=Sandbox(workspace_root=Path(tmp)),
        )
        report = orch.run("analyze system", context)
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].identifier, "F-01")

    def test_reports_accumulate(self):
        orch = _make_orchestrator()
        from jarvis.tools import ToolContext
        from jarvis.config import Settings
        from pathlib import Path
        from jarvis.memory import MemoryStore
        from jarvis.sandbox import Sandbox
        import tempfile
        tmp = tempfile.mkdtemp()
        settings = Settings(name="j", version="0", data_dir=Path(tmp), memory_file=Path(tmp) / "m.json")
        context = ToolContext(
            settings=settings,
            memory=MemoryStore(Path(tmp) / "m.json"),
            sandbox=Sandbox(workspace_root=Path(tmp)),
        )
        orch.run("goal one", context)
        orch.run("goal two", context)
        self.assertEqual(len(orch.all_reports()), 2)


class TestCapabilityApproval(unittest.TestCase):
    def _make_sim(self):
        brain = MagicMock()
        brain.propose_improvement.return_value = ImprovementProposal(
            title="test", rationale="test", changes=(), provider="mock"
        )
        memory = MagicMock()
        memory.search.return_value = []
        code_agent = MagicMock()
        return SelfImprovementManager(brain, memory, code_agent)

    def test_capability_request_created(self):
        sim = self._make_sim()
        req = sim.request_capability(
            title="Read /proc",
            rationale="Need process info",
            requested_capability="proc_read",
            risk_level="low",
        )
        self.assertIsNotNone(req.request_id)
        self.assertFalse(req.approved)
        self.assertEqual(req.requested_capability, "proc_read")

    def test_capability_not_silently_granted(self):
        sim = self._make_sim()
        req = sim.request_capability("cap", "reason", "dangerous_cap", "high")
        # Must be in pending list and not approved
        pending = sim.pending_capability_requests()
        self.assertEqual(len(pending), 1)
        self.assertFalse(pending[0].approved)

    def test_approve_capability(self):
        sim = self._make_sim()
        req = sim.request_capability("cap", "reason", "cap_x")
        approved = sim.approve_capability(req.request_id)
        self.assertIsNotNone(approved)
        self.assertTrue(approved.approved)
        # Pending list should now be empty
        self.assertEqual(sim.pending_capability_requests(), [])

    def test_approve_unknown_request_returns_none(self):
        sim = self._make_sim()
        result = sim.approve_capability("nonexistent-id")
        self.assertIsNone(result)

    def test_multiple_requests_accumulate(self):
        sim = self._make_sim()
        sim.request_capability("cap1", "r1", "c1")
        sim.request_capability("cap2", "r2", "c2")
        self.assertEqual(len(sim.all_capability_requests()), 2)

    def test_self_improvement_still_requires_approval(self):
        sim = self._make_sim()
        proposal = ImprovementProposal(title="t", rationale="r", changes=(), provider="mock")
        with self.assertRaises(PermissionError):
            sim.apply(proposal, approved=False)


if __name__ == "__main__":
    unittest.main()
