"""Network access policy without making external requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


class NetworkAccessDenied(PermissionError):
    """Raised when a tool requests a host outside the network policy."""


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Explicit allow-list policy; external access is off by default."""

    allow_external: bool = False
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)


class NetworkManager:
    """Authorize future network tools while keeping V0.1 request-free."""

    def __init__(self, policy: NetworkPolicy | None = None) -> None:
        self.policy = policy or NetworkPolicy()

    def authorize(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise NetworkAccessDenied("Only HTTP(S) URLs with a hostname are supported.")
        if not self.policy.allow_external:
            raise NetworkAccessDenied("External network access is disabled in V0.1.")
        if self.policy.allowed_hosts and parsed.hostname not in self.policy.allowed_hosts:
            raise NetworkAccessDenied(f"Host is not allow-listed: {parsed.hostname}")
        return parsed.hostname
