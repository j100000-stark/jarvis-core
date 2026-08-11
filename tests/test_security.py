"""Tests for the defensive security subsystem."""

from __future__ import annotations

import unittest

from jarvis.agent.models import AlertSeverity, SecurityAlert, SecurityEvent
from jarvis.security.commander import SecurityCommander
from jarvis.security.defender import (
    ActionType,
    DefenderAction,
    SafetyPolicyDenied,
    SecurityDefender,
)
from jarvis.security.investigator import SecurityInvestigator
from jarvis.security.sentinel import SecuritySentinel
from jarvis.security.test_agent import AuthorizationError, SecurityTestAgent


# ---------------------------------------------------------------------------
# SecuritySentinel tests
# ---------------------------------------------------------------------------


class TestSecuritySentinel(unittest.TestCase):
    def setUp(self):
        self.sentinel = SecuritySentinel()

    def test_process_snapshot_returns_events(self):
        events = self.sentinel.collect_process_snapshot()
        self.assertGreater(len(events), 0)
        self.assertEqual(events[0].event_type, "process_snapshot")

    def test_network_interface_snapshot_returns_events(self):
        events = self.sentinel.collect_network_interfaces()
        self.assertGreater(len(events), 0)

    def test_detect_anomalies_empty_events(self):
        # No events yet — detect_anomalies should return empty list
        alerts = self.sentinel.detect_anomalies()
        self.assertEqual(alerts, [])

    def test_error_event_creates_low_severity_alert(self):
        error_event = SecurityEvent(
            event_type="process_snapshot_error",
            source="test",
            description="Cannot read /proc",
        )
        self.sentinel._events.append(error_event)
        alerts = self.sentinel.detect_anomalies()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, AlertSeverity.LOW)

    def test_high_process_count_creates_alert(self):
        high_count_event = SecurityEvent(
            event_type="process_snapshot",
            source="sentinel.process",
            description="Many processes",
            raw_data="pids_count=600;platform=Linux",
        )
        self.sentinel._events.append(high_count_event)
        alerts = self.sentinel.detect_anomalies()
        self.assertTrue(any(a.severity == AlertSeverity.MEDIUM for a in alerts))

    def test_clear_events(self):
        self.sentinel.collect_process_snapshot()
        self.assertGreater(len(self.sentinel.all_events()), 0)
        self.sentinel.clear_events()
        self.assertEqual(len(self.sentinel.all_events()), 0)

    def test_alerts_retained_after_clear(self):
        error_event = SecurityEvent(
            event_type="process_snapshot_error",
            source="test",
            description="Error",
        )
        self.sentinel._events.append(error_event)
        self.sentinel.detect_anomalies()
        self.sentinel.clear_events()
        self.assertGreater(len(self.sentinel.all_alerts()), 0)


# ---------------------------------------------------------------------------
# SecurityInvestigator tests
# ---------------------------------------------------------------------------


class TestSecurityInvestigator(unittest.TestCase):
    def setUp(self):
        self.inv = SecurityInvestigator()

    def test_empty_inputs_reports_no_data(self):
        report = self.inv.investigate("T-01", events=[], alerts=[])
        self.assertTrue(report.success)
        self.assertIn("No events", report.findings[0].title)

    def test_alert_becomes_finding(self):
        alert = SecurityAlert(
            identifier="A-01",
            severity=AlertSeverity.HIGH,
            title="High severity alert",
            description="Something suspicious",
            events=(),
        )
        report = self.inv.investigate("T-02", events=[], alerts=[alert])
        self.assertTrue(report.success)
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].severity, AlertSeverity.HIGH)

    def test_risk_level_in_summary(self):
        alert = SecurityAlert(
            identifier="A-01",
            severity=AlertSeverity.CRITICAL,
            title="Critical",
            description="Bad",
            events=(),
        )
        report = self.inv.investigate("T-03", events=[], alerts=[alert])
        self.assertIn("critical", report.summary.lower())

    def test_timeline_in_raw_data(self):
        event = SecurityEvent(
            event_type="process_snapshot",
            source="test",
            description="Snapshot",
        )
        report = self.inv.investigate("T-04", events=[event], alerts=[])
        self.assertIn("timeline", report.raw_data)

    def test_evidence_not_marked_as_assumption(self):
        alert = SecurityAlert(
            identifier="A-01",
            severity=AlertSeverity.MEDIUM,
            title="Medium",
            description="desc",
            events=(SecurityEvent(
                event_type="test", source="s", description="d"
            ),),
        )
        report = self.inv.investigate("T-05", events=[], alerts=[alert])
        for finding in report.findings:
            self.assertFalse(finding.is_assumption)

    def test_reports_accumulate(self):
        self.inv.investigate("T-01", events=[], alerts=[])
        self.inv.investigate("T-02", events=[], alerts=[])
        self.assertEqual(len(self.inv.all_reports()), 2)


# ---------------------------------------------------------------------------
# SecurityDefender tests
# ---------------------------------------------------------------------------


class TestSecurityDefender(unittest.TestCase):
    def setUp(self):
        self.defender = SecurityDefender()

    def test_evidence_preservation_allowed_without_approval(self):
        action = DefenderAction(
            action_type=ActionType.PRESERVE_EVIDENCE,
            target="test_log",
            rationale="safety check",
            requires_approval=False,
        )
        report = self.defender.execute(action)
        self.assertTrue(report.success)

    def test_log_event_allowed_without_approval(self):
        action = DefenderAction(
            action_type=ActionType.LOG_EVENT,
            target="event_target",
            rationale="logging test",
            requires_approval=False,
        )
        report = self.defender.execute(action)
        self.assertTrue(report.success)

    def test_stop_process_requires_approval(self):
        action = DefenderAction(
            action_type=ActionType.STOP_LOCAL_PROCESS,
            target="pid:9999",
            rationale="suspicious process",
            requires_approval=True,
            approved=False,
        )
        with self.assertRaises(SafetyPolicyDenied):
            self.defender.execute(action)

    def test_stop_process_succeeds_when_approved(self):
        action = DefenderAction(
            action_type=ActionType.STOP_LOCAL_PROCESS,
            target="pid:9999",
            rationale="suspicious process",
            requires_approval=True,
            approved=True,
        )
        report = self.defender.execute(action)
        self.assertTrue(report.success)

    def test_disable_service_requires_approval(self):
        action = DefenderAction(
            action_type=ActionType.DISABLE_LOCAL_SERVICE,
            target="test-service",
            rationale="anomaly detected",
            requires_approval=True,
            approved=False,
        )
        with self.assertRaises(SafetyPolicyDenied):
            self.defender.execute(action)

    def test_isolate_interface_requires_approval(self):
        action = DefenderAction(
            action_type=ActionType.ISOLATE_INTERFACE,
            target="eth0",
            rationale="isolation",
            requires_approval=True,
            approved=False,
        )
        with self.assertRaises(SafetyPolicyDenied):
            self.defender.execute(action)

    def test_custom_safety_gate_can_block_action(self):
        def deny_all(action):
            return False

        defender = SecurityDefender(safety_gate=deny_all)
        action = DefenderAction(
            action_type=ActionType.PRESERVE_EVIDENCE,
            target="log",
            rationale="test",
            requires_approval=False,
        )
        with self.assertRaises(SafetyPolicyDenied):
            defender.execute(action)

    def test_action_log_records_every_attempt(self):
        action = DefenderAction(
            action_type=ActionType.PRESERVE_EVIDENCE,
            target="log",
            rationale="test",
            requires_approval=False,
        )
        self.defender.execute(action)
        self.assertGreater(len(self.defender.action_log()), 0)

    def test_denied_action_logged(self):
        action = DefenderAction(
            action_type=ActionType.STOP_LOCAL_PROCESS,
            target="pid:1",
            rationale="test",
            requires_approval=True,
            approved=False,
        )
        try:
            self.defender.execute(action)
        except SafetyPolicyDenied:
            pass
        log = self.defender.action_log()
        self.assertTrue(any("DENIED" in entry for entry in log))


# ---------------------------------------------------------------------------
# SecurityTestAgent tests
# ---------------------------------------------------------------------------


class TestSecurityTestAgent(unittest.TestCase):
    def setUp(self):
        self.agent = SecurityTestAgent()

    def test_raises_without_authorization(self):
        with self.assertRaises(AuthorizationError):
            self.agent.run_posture_check()

    def test_authorized_check_returns_report(self):
        import tempfile, os
        self.agent.authorize_target(tempfile.gettempdir())
        report = self.agent.run_posture_check()
        self.assertTrue(report.success)
        self.assertGreater(len(report.findings), 0)

    def test_revoke_authorization_prevents_check(self):
        self.agent.authorize_target("/tmp")
        self.agent.revoke_authorization()
        self.assertFalse(self.agent.is_authorized())
        with self.assertRaises(AuthorizationError):
            self.agent.run_posture_check()

    def test_platform_finding_is_info(self):
        import tempfile
        self.agent.authorize_target(tempfile.gettempdir())
        report = self.agent.run_posture_check()
        platform_findings = [f for f in report.findings if f.category == "platform"]
        self.assertEqual(len(platform_findings), 1)
        self.assertEqual(platform_findings[0].severity, AlertSeverity.INFO)

    def test_findings_are_not_assumptions_for_concrete_data(self):
        import tempfile
        self.agent.authorize_target(tempfile.gettempdir())
        report = self.agent.run_posture_check()
        # Platform finding is always concrete
        platform_f = next(f for f in report.findings if f.category == "platform")
        self.assertFalse(platform_f.is_assumption)

    def test_reports_accumulate(self):
        import tempfile
        self.agent.authorize_target(tempfile.gettempdir())
        self.agent.run_posture_check("T1")
        self.agent.run_posture_check("T2")
        self.assertEqual(len(self.agent.all_reports()), 2)


# ---------------------------------------------------------------------------
# SecurityCommander tests
# ---------------------------------------------------------------------------


class TestSecurityCommander(unittest.TestCase):
    def test_run_returns_unified_report(self):
        cmd = SecurityCommander()
        report = cmd.run("Check whether my computer is behaving normally.")
        self.assertTrue(report.success)
        self.assertEqual(report.agent_name, "SecurityCommander")
        self.assertIn("SecurityCommander", report.agent_name)

    def test_report_includes_findings(self):
        cmd = SecurityCommander()
        report = cmd.run("security check")
        self.assertIsNotNone(report.findings)

    def test_goal_recorded_in_raw_data(self):
        cmd = SecurityCommander()
        goal = "run a defensive check"
        report = cmd.run(goal)
        self.assertEqual(report.raw_data.get("goal"), goal)

    def test_posture_check_included_when_target_authorized(self):
        import tempfile
        cmd = SecurityCommander()
        report = cmd.run(
            "security",
            include_posture_check=True,
            authorized_target=tempfile.gettempdir(),
        )
        self.assertIn("test_agent", report.summary)

    def test_posture_check_skipped_without_target(self):
        cmd = SecurityCommander()
        report = cmd.run("security", include_posture_check=True, authorized_target=None)
        self.assertTrue(report.success)

    def test_multiple_runs_accumulate_reports(self):
        cmd = SecurityCommander()
        cmd.run("first goal")
        cmd.run("second goal")
        self.assertEqual(len(cmd.all_reports()), 2)


if __name__ == "__main__":
    unittest.main()
