"""Tests for network recovery manager and state machine."""

from __future__ import annotations

import unittest

from jarvis.agent.models import NetworkConnectivity
from jarvis.network.recovery import NetworkRecoveryManager


class _FakeRecoveryManager(NetworkRecoveryManager):
    """Subclass that overrides probe and sleep for deterministic tests."""

    def __init__(self, probe_results: dict[str, bool], **kwargs):
        super().__init__(**kwargs)
        self._probe_results = probe_results

    def _do_probe(self, host: str) -> bool:
        return self._probe_results.get(host, False)

    def _sleep(self, seconds: float) -> None:
        pass  # instant in tests


class TestNetworkStateTransitions(unittest.TestCase):
    def _make(self, results: dict[str, bool], **kwargs) -> _FakeRecoveryManager:
        return _FakeRecoveryManager(
            probe_results=results,
            probe_hosts=tuple(results.keys()),
            **kwargs,
        )

    def test_online_when_all_reachable(self):
        mgr = self._make({"h1": True, "h2": True})
        state = mgr.probe()
        self.assertEqual(state.connectivity, NetworkConnectivity.ONLINE)
        self.assertEqual(set(state.reachable_hosts), {"h1", "h2"})
        self.assertEqual(state.unreachable_hosts, ())

    def test_degraded_when_partial(self):
        mgr = self._make({"h1": True, "h2": False})
        state = mgr.probe()
        self.assertEqual(state.connectivity, NetworkConnectivity.DEGRADED)
        self.assertIn("h1", state.reachable_hosts)
        self.assertIn("h2", state.unreachable_hosts)

    def test_offline_when_none_reachable(self):
        mgr = self._make({"h1": False, "h2": False})
        state = mgr.probe()
        self.assertEqual(state.connectivity, NetworkConnectivity.OFFLINE)

    def test_local_only_skips_probes(self):
        mgr = self._make({"h1": True, "h2": True})
        mgr.force_local_only()
        self.assertEqual(mgr.connectivity, NetworkConnectivity.LOCAL_ONLY)
        # probe() while local_only should NOT change state
        state = mgr.probe()
        self.assertEqual(state.connectivity, NetworkConnectivity.LOCAL_ONLY)

    def test_release_local_only_probes(self):
        mgr = self._make({"h1": True})
        mgr.force_local_only()
        mgr.release_local_only()
        self.assertEqual(mgr.connectivity, NetworkConnectivity.ONLINE)

    def test_recovery_transitions_through_recovering(self):
        mgr = self._make({"h1": False}, max_reconnect_attempts=3)
        mgr.probe()  # → OFFLINE
        mgr.attempt_recovery()
        events = mgr.events()
        # StrEnum values are lowercase; check case-insensitively
        self.assertTrue(any("recovering" in e.lower() for e in events))

    def test_recovery_succeeds_when_probe_returns_true(self):
        call_count = [0]

        class _Mgr(_FakeRecoveryManager):
            def _do_probe(self, host):
                call_count[0] += 1
                return call_count[0] > 1  # first call fails, subsequent succeed

        mgr = _Mgr(probe_results={}, probe_hosts=("h1",), max_reconnect_attempts=3)
        mgr._sleep = lambda s: None
        mgr.probe()  # → OFFLINE
        mgr.attempt_recovery()
        self.assertEqual(mgr.connectivity, NetworkConnectivity.ONLINE)

    def test_bounded_reconnect_stops_retrying(self):
        mgr = self._make({"h1": False}, max_reconnect_attempts=2)
        mgr.probe()  # → OFFLINE
        mgr.attempt_recovery()
        mgr.attempt_recovery()
        # Budget exhausted — next call should not increment
        attempts_before = mgr.reconnect_attempts()
        mgr.attempt_recovery()
        self.assertEqual(mgr.reconnect_attempts(), attempts_before)

    def test_no_recovery_when_already_online(self):
        mgr = self._make({"h1": True})
        mgr.probe()  # → ONLINE
        state = mgr.attempt_recovery()
        self.assertEqual(state.connectivity, NetworkConnectivity.ONLINE)

    def test_event_log_grows(self):
        mgr = self._make({"h1": True})
        mgr.probe()
        mgr.probe()
        self.assertGreater(len(mgr.events()), 0)

    def test_events_returns_defensive_copy(self):
        mgr = self._make({"h1": True})
        mgr.probe()
        events = mgr.events()
        events.append("tamper")
        self.assertNotIn("tamper", mgr.events())

    def test_authorize_delegates_to_base(self):
        mgr = self._make({"h1": True})
        # External access is disabled by default
        from jarvis.network.manager import NetworkAccessDenied
        with self.assertRaises(NetworkAccessDenied):
            mgr.authorize("http://example.com/")


if __name__ == "__main__":
    unittest.main()
