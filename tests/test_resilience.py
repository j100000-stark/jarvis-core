"""Tests for the resilience subsystem."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.agent.models import ServiceState
from jarvis.resilience.crash_recovery import CrashRecoveryManager
from jarvis.resilience.health_check import HealthCheckManager
from jarvis.resilience.state_recovery import StateRecoveryManager
from jarvis.resilience.supervisor import ServiceSupervisor
from jarvis.resilience.watchdog import WatchdogManager


class TestWatchdogManager(unittest.TestCase):
    def setUp(self):
        self.wd = WatchdogManager()

    def test_register_and_poll_healthy(self):
        self.wd.register("svc", lambda: True)
        incidents = self.wd.poll()
        self.assertEqual(incidents, [])
        self.assertEqual(self.wd.state_of("svc"), ServiceState.RUNNING)

    def test_failed_service_creates_incident(self):
        self.wd.register("svc", lambda: False)
        incidents = self.wd.poll()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0].service_name, "svc")
        self.assertEqual(self.wd.state_of("svc"), ServiceState.FAILED)

    def test_crash_loop_detection(self):
        self.wd.register("svc", lambda: False)
        for _ in range(WatchdogManager.CRASH_LOOP_THRESHOLD):
            self.wd.poll()
        self.assertTrue(self.wd.in_crash_loop("svc"))
        self.assertEqual(self.wd.state_of("svc"), ServiceState.CRASH_LOOP)

    def test_check_exception_creates_incident(self):
        def bad_check():
            raise RuntimeError("probe failed")
        self.wd.register("svc", bad_check)
        incidents = self.wd.poll()
        self.assertEqual(len(incidents), 1)
        self.assertIn("probe failed", incidents[0].reason)

    def test_recovery_resets_failure_count(self):
        call_count = [0]

        def check():
            call_count[0] += 1
            return call_count[0] > 2  # Fail first two polls

        self.wd.register("svc", check)
        self.wd.poll()  # fail
        self.wd.poll()  # fail
        self.assertEqual(self.wd.state_of("svc"), ServiceState.FAILED)
        self.wd.poll()  # pass — resets
        self.assertEqual(self.wd.state_of("svc"), ServiceState.RUNNING)

    def test_deregister_removes_service(self):
        self.wd.register("svc", lambda: True)
        self.wd.deregister("svc")
        self.assertIsNone(self.wd.state_of("svc"))

    def test_healthy_services_list(self):
        self.wd.register("a", lambda: True)
        self.wd.register("b", lambda: False)
        self.wd.poll()
        healthy = self.wd.healthy_services()
        self.assertIn("a", healthy)
        self.assertNotIn("b", healthy)

    def test_all_incidents_accumulate(self):
        self.wd.register("svc", lambda: False)
        self.wd.poll()
        self.wd.poll()
        self.assertEqual(len(self.wd.all_incidents()), 2)


class TestCrashRecoveryManager(unittest.TestCase):
    def setUp(self):
        self.mgr = CrashRecoveryManager(default_max_restarts=3)

    def test_record_failure_returns_incident(self):
        incident = self.mgr.record_failure("svc", "test failure")
        self.assertEqual(incident.service_name, "svc")
        self.assertEqual(incident.restart_count, 1)

    def test_crash_loop_after_budget_exhausted(self):
        for _ in range(4):  # max_restarts=3, so 4th hits crash loop
            self.mgr.record_failure("svc", "fail")
        self.assertTrue(self.mgr.in_crash_loop("svc"))
        self.assertFalse(self.mgr.can_restart("svc"))

    def test_recovery_resets_state(self):
        for _ in range(2):
            self.mgr.record_failure("svc", "fail")
        self.mgr.record_recovery("svc")
        self.assertFalse(self.mgr.in_crash_loop("svc"))
        self.assertEqual(self.mgr.restart_count("svc"), 0)

    def test_incidents_for_service(self):
        self.mgr.record_failure("svc-a", "x")
        self.mgr.record_failure("svc-b", "y")
        self.mgr.record_failure("svc-a", "z")
        incidents = self.mgr.incidents_for("svc-a")
        self.assertEqual(len(incidents), 2)
        self.assertTrue(all(i.service_name == "svc-a" for i in incidents))

    def test_auto_register_unknown_service(self):
        incident = self.mgr.record_failure("new_svc", "first fail")
        self.assertIsNotNone(incident)
        self.assertEqual(incident.service_name, "new_svc")

    def test_state_of_returns_none_for_unknown(self):
        self.assertIsNone(self.mgr.state_of("unknown"))

    def test_bounded_restart_stops_indefinite_loops(self):
        # Each failure should increment count; crash loop stops retries
        self.mgr.register_service("looper", max_restarts=2)
        self.mgr.record_failure("looper", "1")
        self.mgr.record_failure("looper", "2")
        self.mgr.record_failure("looper", "3")
        self.assertTrue(self.mgr.in_crash_loop("looper"))
        # Further failures should not change can_restart
        self.assertFalse(self.mgr.can_restart("looper"))


class TestServiceSupervisor(unittest.TestCase):
    def _make_supervisor(self):
        sup = ServiceSupervisor()
        # Override sleep to be instant in tests
        sup._sleep = lambda s: None
        return sup

    def test_supervise_creates_initial_instance(self):
        sup = self._make_supervisor()
        sup.supervise("svc", lambda: {"alive": True})
        inst = sup.get("svc")
        self.assertIsNotNone(inst)

    def test_restart_replaces_instance(self):
        sup = self._make_supervisor()
        counter = [0]

        def factory():
            counter[0] += 1
            return {"id": counter[0]}

        sup.supervise("svc", factory)
        self.assertEqual(sup.get("svc")["id"], 1)
        sup.restart("svc", "test restart")
        self.assertEqual(sup.get("svc")["id"], 2)

    def test_crash_loop_raises_after_budget(self):
        sup = self._make_supervisor()
        sup.supervise("svc", lambda: {}, max_restarts=2)
        sup.restart("svc", "r1")
        sup.restart("svc", "r2")
        with self.assertRaises(RuntimeError):
            sup.restart("svc", "r3")

    def test_failed_factory_records_incident(self):
        sup = self._make_supervisor()
        sup.supervise("svc", lambda: {}, max_restarts=5)

        def bad_factory():
            raise RuntimeError("factory failed")

        # Replace factory to fail
        sup._services["svc"].factory = bad_factory
        sup.restart("svc", "test")
        self.assertEqual(sup.state_of("svc"), ServiceState.FAILED)

    def test_unknown_service_raises_key_error(self):
        sup = self._make_supervisor()
        with self.assertRaises(KeyError):
            sup.restart("nonexistent", "r")


class TestHealthCheckManager(unittest.TestCase):
    def setUp(self):
        self.hcm = HealthCheckManager()

    def test_healthy_check_passes(self):
        self.hcm.register("db", lambda: True)
        status = self.hcm.check("db")
        self.assertTrue(status.healthy)
        self.assertEqual(status.state, "healthy")

    def test_unhealthy_check_fails(self):
        self.hcm.register("db", lambda: False)
        status = self.hcm.check("db")
        self.assertFalse(status.healthy)
        self.assertEqual(status.state, "unhealthy")

    def test_check_exception_is_unhealthy(self):
        def bad():
            raise RuntimeError("disk full")
        self.hcm.register("disk", bad)
        status = self.hcm.check("disk")
        self.assertFalse(status.healthy)
        self.assertEqual(status.state, "error")
        self.assertIn("disk full", status.details)

    def test_unknown_component_is_unhealthy(self):
        status = self.hcm.check("unknown")
        self.assertFalse(status.healthy)

    def test_all_healthy_requires_all_pass(self):
        self.hcm.register("a", lambda: True)
        self.hcm.register("b", lambda: False)
        self.assertFalse(self.hcm.all_healthy())

    def test_check_all_returns_all_statuses(self):
        self.hcm.register("x", lambda: True)
        self.hcm.register("y", lambda: True)
        statuses = self.hcm.check_all()
        self.assertEqual(len(statuses), 2)

    def test_detail_fn_included(self):
        self.hcm.register("mem", lambda: True, detail_fn=lambda: "256MB free")
        status = self.hcm.check("mem")
        self.assertIn("256MB free", status.details)


class TestStateRecoveryManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mgr = StateRecoveryManager(Path(self.tmp))

    def test_save_and_load(self):
        self.mgr.save("svc", {"key": "value", "count": 42})
        loaded = self.mgr.load("svc")
        self.assertEqual(loaded, {"key": "value", "count": 42})

    def test_load_returns_none_when_absent(self):
        result = self.mgr.load("missing")
        self.assertIsNone(result)

    def test_has_snapshot(self):
        self.assertFalse(self.mgr.has_snapshot("svc"))
        self.mgr.save("svc", {"x": 1})
        self.assertTrue(self.mgr.has_snapshot("svc"))

    def test_delete_removes_snapshot(self):
        self.mgr.save("svc", {"x": 1})
        self.mgr.delete("svc")
        self.assertFalse(self.mgr.has_snapshot("svc"))
        self.assertIsNone(self.mgr.load("svc"))

    def test_save_non_dict_raises(self):
        with self.assertRaises(TypeError):
            self.mgr.save("svc", "not a dict")  # type: ignore

    def test_persists_across_instances(self):
        self.mgr.save("svc", {"data": "persistent"})
        new_mgr = StateRecoveryManager(Path(self.tmp))
        loaded = new_mgr.load("svc")
        self.assertEqual(loaded, {"data": "persistent"})


if __name__ == "__main__":
    unittest.main()
