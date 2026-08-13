"""Network recovery manager: connectivity state machine with bounded reconnection.

Extends the existing NetworkManager with observable connectivity states,
diagnostics, and exponential back-off reconnection.

LocalAccessPoint / LocalNetworkFallback are interface stubs for future
Raspberry Pi hardware.  They describe a local Wi-Fi access point that
provides connectivity between authorized local devices — NOT Internet access.
"""

from __future__ import annotations

import math
import socket
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..agent.models import NetworkConnectivity, NetworkState
from .manager import NetworkManager, NetworkPolicy


# ---------------------------------------------------------------------------
# Future transport interface (Raspberry hardware stub)
# ---------------------------------------------------------------------------


@runtime_checkable
class LocalNetworkTransport(Protocol):
    """Interface for future local network transports (Raspberry, etc.)."""

    @property
    def name(self) -> str: ...

    def is_available(self) -> bool: ...

    def local_status(self) -> dict[str, str]: ...


class LocalAccessPoint(ABC):
    """Stub for a future local Wi-Fi access point on authorized hardware.

    A LocalAccessPoint provides connectivity *between authorized local
    devices only*.  It does NOT create or simulate Internet access.
    This class exists as an architectural boundary for future hardware.
    """

    @abstractmethod
    def start(self) -> None:
        """Start the local access point (future hardware only)."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Stop the local access point."""
        raise NotImplementedError

    @abstractmethod
    def connected_devices(self) -> list[str]:
        """Return identifiers of authorized connected devices."""
        raise NotImplementedError

    @abstractmethod
    def is_active(self) -> bool:
        """Return True if the access point is active."""
        raise NotImplementedError


class LocalNetworkFallback(ABC):
    """Stub for future local-network fallback (Raspberry hardware).

    When Internet connectivity is lost, JARVIS may transition to
    LOCAL_ONLY mode and use a LocalNetworkFallback to maintain
    communication with authorized local devices.  This is NOT
    Internet access.
    """

    @abstractmethod
    def activate(self) -> None:
        """Activate local-only network mode."""
        raise NotImplementedError

    @abstractmethod
    def deactivate(self) -> None:
        """Deactivate local-only network mode and restore normal routing."""
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict[str, str]:
        """Return current local network status as a string dict."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Connectivity probe (DNS / socket — reads only, never writes)
# ---------------------------------------------------------------------------


_DEFAULT_PROBE_HOSTS = ("1.1.1.1", "8.8.8.8")
_PROBE_PORT = 53
_PROBE_TIMEOUT = 2.0


def probe_host(host: str, port: int = _PROBE_PORT, timeout: float = _PROBE_TIMEOUT) -> bool:
    """Attempt a TCP connect to host:port; return True on success.

    This is a read-only connectivity probe.  It does not send application
    data.  Only local or explicitly authorized hosts should be probed in
    security-sensitive deployments.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Network Recovery Manager
# ---------------------------------------------------------------------------


class NetworkRecoveryManager:
    """Connectivity state machine with bounded reconnection and back-off.

    States
    ------
    ONLINE       — all probe hosts reachable
    DEGRADED     — some probe hosts reachable
    OFFLINE      — no probe hosts reachable
    LOCAL_ONLY   — explicitly forced to local-only mode (no probing)
    RECOVERING   — in progress of attempting reconnection

    The manager tracks events and exposes them for the web interface.
    It does NOT make autonomous outbound requests beyond the configured
    probe hosts.
    """

    MAX_BACKOFF_SECONDS = 120.0

    def __init__(
        self,
        probe_hosts: tuple[str, ...] = _DEFAULT_PROBE_HOSTS,
        max_reconnect_attempts: int = 5,
        base_backoff_seconds: float = 2.0,
        policy: NetworkPolicy | None = None,
    ) -> None:
        self._probe_hosts = probe_hosts
        self._max_reconnect_attempts = max_reconnect_attempts
        self._base_backoff_seconds = base_backoff_seconds
        self._reconnect_attempts = 0
        # UNKNOWN until the first real probe — OFFLINE is only ever the
        # result of a live probe that found no reachable hosts.
        self._connectivity = NetworkConnectivity.UNKNOWN
        self._events: list[str] = []
        self._base_manager = NetworkManager(policy)
        self._local_only_forced = False

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    @property
    def connectivity(self) -> NetworkConnectivity:
        return self._connectivity

    def force_local_only(self) -> None:
        """Switch to LOCAL_ONLY mode; no Internet probes are made."""
        self._local_only_forced = True
        self._transition(NetworkConnectivity.LOCAL_ONLY, "Forced into local-only mode.")

    def release_local_only(self) -> None:
        """Exit LOCAL_ONLY mode and probe connectivity."""
        self._local_only_forced = False
        self._log("Released local-only mode; probing connectivity.")
        self.probe()

    def probe(self) -> NetworkState:
        """Run connectivity probes and update state; return current NetworkState."""
        if self._local_only_forced:
            return self._current_state()

        reachable: list[str] = []
        unreachable: list[str] = []

        for host in self._probe_hosts:
            if self._do_probe(host):
                reachable.append(host)
            else:
                unreachable.append(host)

        if reachable and not unreachable:
            self._reconnect_attempts = 0
            self._transition(NetworkConnectivity.ONLINE, f"All hosts reachable: {reachable}")
        elif reachable:
            self._reconnect_attempts = 0
            self._transition(
                NetworkConnectivity.DEGRADED,
                f"Partial connectivity. Reachable: {reachable}; unreachable: {unreachable}",
            )
        else:
            self._transition(
                NetworkConnectivity.OFFLINE,
                f"No hosts reachable. Unreachable: {unreachable}",
            )

        return NetworkState(
            connectivity=self._connectivity,
            reachable_hosts=tuple(reachable),
            unreachable_hosts=tuple(unreachable),
            details=self._events[-1] if self._events else "",
        )

    def attempt_recovery(self) -> NetworkState:
        """Try to recover from OFFLINE state with bounded back-off.

        Returns the resulting NetworkState.  Stops retrying once the
        budget is exhausted.
        """
        if self._connectivity in (NetworkConnectivity.ONLINE, NetworkConnectivity.DEGRADED):
            return self._current_state()

        if self._reconnect_attempts >= self._max_reconnect_attempts:
            self._log(
                f"Reconnect budget exhausted after {self._reconnect_attempts} attempts."
            )
            return self._current_state()

        self._transition(NetworkConnectivity.RECOVERING, "Starting reconnect attempt.")
        self._reconnect_attempts += 1
        backoff = min(
            self._base_backoff_seconds * math.pow(2, self._reconnect_attempts - 1),
            self.MAX_BACKOFF_SECONDS,
        )
        self._sleep(backoff)
        return self.probe()

    # Seam for tests
    def _do_probe(self, host: str) -> bool:  # pragma: no cover
        return probe_host(host)

    def _sleep(self, seconds: float) -> None:  # pragma: no cover
        time.sleep(seconds)

    def _transition(self, new_state: NetworkConnectivity, detail: str) -> None:
        if new_state != self._connectivity:
            self._log(f"State: {self._connectivity} → {new_state}. {detail}")
        else:
            self._log(detail)
        self._connectivity = new_state

    def _log(self, message: str) -> None:
        self._events.append(message)

    def _current_state(self) -> NetworkState:
        return NetworkState(
            connectivity=self._connectivity,
            details=self._events[-1] if self._events else "",
        )

    # ------------------------------------------------------------------
    # Policy delegation
    # ------------------------------------------------------------------

    def authorize(self, url: str) -> str:
        """Delegate URL authorization to the underlying NetworkManager."""
        return self._base_manager.authorize(url)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def events(self) -> list[str]:
        """Return the event log (defensive copy)."""
        return list(self._events)

    def reconnect_attempts(self) -> int:
        return self._reconnect_attempts
