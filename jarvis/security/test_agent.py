"""SecurityTestAgent: safe defensive security checks against an authorized target.

IMPORTANT:
- Only checks configuration, permissions, and basic security posture.
- Does NOT implement exploitation, credential attacks, malware,
  persistence, evasion, or scanning of unauthorized hosts.
- All checks are read-only and require an explicit authorized target.
"""

from __future__ import annotations

import os
import platform
import socket
import stat
from pathlib import Path

from ..agent.models import AgentReport, AlertSeverity, SecurityFinding


class AuthorizationError(PermissionError):
    """Raised when a test target has not been authorized."""


class SecurityTestAgent:
    """Perform defensive security posture checks on an authorized local target.

    The authorized target must be explicitly set.  Checks run against the
    local filesystem, process environment, and local service configuration
    only — no external network scanning.
    """

    def __init__(self) -> None:
        self._authorized_target: str | None = None
        self._reports: list[AgentReport] = []
        self._counter = 0

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def authorize_target(self, target: str) -> None:
        """Explicitly authorize a local target (path or hostname) for testing."""
        self._authorized_target = target

    def revoke_authorization(self) -> None:
        """Remove the current authorization."""
        self._authorized_target = None

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def run_posture_check(self, task_id: str = "") -> AgentReport:
        """Run all defensive posture checks against the authorized target.

        Returns a structured AgentReport with findings and remediation.
        Raises AuthorizationError if no target has been authorized.
        """
        self._counter += 1
        tid = task_id or f"SEC-TEST-{self._counter:04d}"

        if self._authorized_target is None:
            raise AuthorizationError(
                "No authorized test target configured. "
                "Call authorize_target() with an explicit local target first."
            )

        findings: list[SecurityFinding] = []
        checks = [
            self._check_platform_info,
            self._check_world_writable_paths,
            self._check_environment_secrets,
            self._check_local_ports,
        ]

        for check in checks:
            try:
                finding = check(tid)
                if finding:
                    findings.append(finding)
            except Exception as exc:
                findings.append(
                    SecurityFinding(
                        identifier=f"{tid}-ERR",
                        category="check_error",
                        title="Check could not complete",
                        description=str(exc),
                        is_assumption=True,
                        severity=AlertSeverity.LOW,
                    )
                )

        severity_order = [
            AlertSeverity.INFO,
            AlertSeverity.LOW,
            AlertSeverity.MEDIUM,
            AlertSeverity.HIGH,
            AlertSeverity.CRITICAL,
        ]
        max_sev = max(
            (severity_order.index(f.severity) for f in findings if not f.is_assumption),
            default=0,
        )
        overall = severity_order[max_sev]

        summary = (
            f"Posture check for '{self._authorized_target}' completed. "
            f"{len(findings)} finding(s). Overall severity: {overall.value}."
        )

        report = AgentReport(
            task_id=tid,
            agent_name="SecurityTestAgent",
            success=True,
            summary=summary,
            findings=tuple(findings),
        )
        self._reports.append(report)
        return report

    # ------------------------------------------------------------------
    # Individual checks (read-only)
    # ------------------------------------------------------------------

    def _check_platform_info(self, tid: str) -> SecurityFinding:
        info = f"{platform.system()} {platform.release()} / Python {platform.python_version()}"
        return SecurityFinding(
            identifier=f"{tid}-PLAT",
            category="platform",
            title="Platform information",
            description=f"Running on: {info}",
            is_assumption=False,
            severity=AlertSeverity.INFO,
            remediation="No action required; informational only.",
        )

    def _check_world_writable_paths(self, tid: str) -> SecurityFinding | None:
        """Check whether the target path (if a directory) has world-writable entries."""
        target_path = Path(self._authorized_target or ".")
        if not target_path.is_dir():
            return None

        world_writable: list[str] = []
        try:
            for entry in target_path.iterdir():
                try:
                    mode = entry.stat().st_mode
                    if mode & stat.S_IWOTH:
                        world_writable.append(str(entry))
                except OSError:
                    continue
        except PermissionError:
            return SecurityFinding(
                identifier=f"{tid}-WW",
                category="permissions",
                title="World-writable check: insufficient permissions",
                description="Could not read directory permissions (permission denied).",
                is_assumption=True,
                severity=AlertSeverity.LOW,
            )

        if world_writable:
            return SecurityFinding(
                identifier=f"{tid}-WW",
                category="permissions",
                title="World-writable paths detected",
                description=f"Found {len(world_writable)} world-writable path(s).",
                evidence="; ".join(world_writable[:10]),
                is_assumption=False,
                severity=AlertSeverity.MEDIUM,
                remediation="Review and restrict permissions with chmod o-w on affected paths.",
            )
        return SecurityFinding(
            identifier=f"{tid}-WW",
            category="permissions",
            title="No world-writable paths in target directory",
            description="All checked entries have restricted write permissions.",
            is_assumption=False,
            severity=AlertSeverity.INFO,
            remediation="No action required.",
        )

    def _check_environment_secrets(self, tid: str) -> SecurityFinding:
        """Check for obviously sensitive key names in the environment.

        This is informational only — it does NOT read or expose values.
        """
        sensitive_patterns = ("password", "secret", "token", "key", "api_key", "private")
        found = [
            k for k in os.environ
            if any(p in k.lower() for p in sensitive_patterns)
        ]
        if found:
            return SecurityFinding(
                identifier=f"{tid}-ENV",
                category="environment",
                title="Sensitive variable names detected in environment",
                description=(
                    f"Found {len(found)} environment variable name(s) matching sensitive patterns. "
                    "Values were NOT read or recorded."
                ),
                evidence=f"Variable names (values not shown): {', '.join(found[:10])}",
                is_assumption=False,
                severity=AlertSeverity.LOW,
                remediation=(
                    "Ensure sensitive environment variables are managed via a secrets "
                    "manager and are not exposed to child processes unnecessarily."
                ),
            )
        return SecurityFinding(
            identifier=f"{tid}-ENV",
            category="environment",
            title="No obviously sensitive environment variable names",
            description="No variable names matching common sensitive patterns were found.",
            is_assumption=False,
            severity=AlertSeverity.INFO,
            remediation="No action required.",
        )

    def _check_local_ports(self, tid: str) -> SecurityFinding:
        """Attempt to resolve local hostname to check basic name resolution."""
        try:
            hostname = socket.gethostname()
            # We only resolve, never connect
            socket.getaddrinfo(hostname, None)
            return SecurityFinding(
                identifier=f"{tid}-NET",
                category="network",
                title="Local hostname resolves successfully",
                description=f"Local hostname '{hostname}' resolves to at least one address.",
                is_assumption=False,
                severity=AlertSeverity.INFO,
                remediation="No action required.",
            )
        except Exception as exc:
            return SecurityFinding(
                identifier=f"{tid}-NET",
                category="network",
                title="Local hostname resolution failed",
                description=f"Could not resolve local hostname: {exc}",
                is_assumption=False,
                severity=AlertSeverity.LOW,
                remediation="Check /etc/hosts and DNS configuration.",
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_reports(self) -> list[AgentReport]:
        return list(self._reports)

    def is_authorized(self) -> bool:
        return self._authorized_target is not None
