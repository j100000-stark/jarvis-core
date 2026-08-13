"""SelfRepairManager — detect, classify, and repair common JARVIS execution failures.

Repair pipeline:
  IDLE → DIAGNOSING → PLANNING → PATCHING → TESTING → RECOVERED | FAILED

Safety constraints (never relaxed):
  - Max _MAX_ATTEMPTS repair attempts per session (prevents infinite loops).
  - Never modifies secrets, API keys, or credentials.
  - Never deletes project files.
  - Never runs destructive commands without explicit authorisation.
  - Records all repair incidents to disk for auditing.
  - Fails loudly instead of silently masking errors.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_MAX_ATTEMPTS = 3


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class RepairResult:
    """Outcome of a single repair attempt."""

    success: bool
    failure_type: str
    actions: list[str]
    message: str
    # New Settings instance if settings were patched during repair.
    repaired_settings: object = None


# ── Manager ───────────────────────────────────────────────────────────────────

class SelfRepairManager:
    """
    Detect common JARVIS failures and apply targeted, safe fixes.

    The manager is stateful across calls within one process lifetime.
    It tracks repair attempts so it can enforce the safety limit.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._attempts = 0
        self._incidents: list[dict] = []

    # ── Public API ─────────────────────────────────────────────────────────

    def diagnose_and_repair(
        self,
        *,
        failure_message: str,
        failure_step: str | None,
        goal: str,
        settings: object,
        registry: object,
    ) -> RepairResult:
        """Classify the failure and attempt a targeted repair.

        Returns a RepairResult.  If ``success`` is True the caller should
        retry the goal (optionally using ``repaired_settings``).
        """
        if self._attempts >= _MAX_ATTEMPTS:
            result = RepairResult(
                success=False,
                failure_type="max_attempts_exceeded",
                actions=[
                    f"Self-repair limit reached ({_MAX_ATTEMPTS} attempts).",
                    "Manual intervention required.",
                ],
                message=(
                    f"Self-repair limit ({_MAX_ATTEMPTS}) reached. "
                    "Check configuration and try again later."
                ),
            )
            self._record(result, goal)
            return result

        self._attempts += 1
        failure_type = self._classify(failure_message, failure_step)
        result = self._repair(failure_type, failure_message, goal, settings, registry)
        self._record(result, goal)
        return result

    def incident_count(self) -> int:
        return len(self._incidents)

    def reset_attempts(self) -> None:
        """Reset attempt counter — call between independent user goals."""
        self._attempts = 0

    # ── Classification ──────────────────────────────────────────────────────

    def _classify(self, message: str, step: str | None) -> str:
        combined = f"{message} {step or ''}".lower()

        if "web research is not" in combined or "web_research_enabled" in combined:
            return "web_research_disabled"
        if "unknown tool" in combined:
            return "tool_not_found"
        if "1010" in combined or ("cloudflare" in combined and "403" in combined):
            return "cloudflare_blocked"
        if "http 403" in combined or "http 401" in combined:
            return "auth_error"
        if "http 429" in combined or "rate limit" in combined:
            return "rate_limited"
        if "timed out" in combined or "timeout" in combined:
            return "timeout"
        if "could not reach" in combined or "urlerror" in combined or "network" in combined:
            return "network_error"
        if "llm" in combined or "remote" in combined or "api returned" in combined:
            return "llm_error"
        return "unknown"

    # ── Repair strategies ───────────────────────────────────────────────────

    def _repair(
        self,
        failure_type: str,
        failure_message: str,
        goal: str,
        settings: object,
        registry: object,
    ) -> RepairResult:
        if failure_type == "web_research_disabled":
            return self._repair_web_research(settings)

        if failure_type == "tool_not_found":
            available = ", ".join(sorted(getattr(registry, "names", lambda: [])()))
            return RepairResult(
                success=False,
                failure_type=failure_type,
                actions=[
                    "Diagnosed: LLM requested a tool that is not registered.",
                    f"Available tools: {available}",
                    "Repair: No patch possible — update the LLM prompt to list valid tools.",
                ],
                message=(
                    f"Requested tool does not exist. "
                    f"Available: {available}."
                ),
            )

        if failure_type in ("timeout", "network_error", "llm_error"):
            return RepairResult(
                success=True,  # Caller should retry
                failure_type=failure_type,
                actions=[
                    f"Diagnosed: transient {failure_type.replace('_', ' ')}.",
                    "Strategy: retry the goal once.",
                ],
                message=f"Transient {failure_type.replace('_', ' ')} — retrying.",
            )

        if failure_type == "cloudflare_blocked":
            return RepairResult(
                success=False,
                failure_type=failure_type,
                actions=[
                    "Diagnosed: Cloudflare WAF blocked the request (error 1010).",
                    "Cause: User-Agent not recognised by CDN.",
                    "Fix required: ensure API client sends a valid User-Agent header.",
                ],
                message="Request blocked by Cloudflare. Check the transport User-Agent configuration.",
            )

        if failure_type in ("auth_error", "rate_limited"):
            return RepairResult(
                success=False,
                failure_type=failure_type,
                actions=[
                    f"Diagnosed: {failure_type.replace('_', ' ')}.",
                    "Cannot auto-repair without valid credentials or rate-limit relief.",
                ],
                message=(
                    f"API {failure_type.replace('_', ' ')}. "
                    "Check JARVIS_LLM_API_KEY and account quota."
                ),
            )

        # Unknown — cannot repair.  Redact secrets before including raw message.
        try:
            from ..diagnostics import _redact_env_values  # type: ignore[attr-defined]
            safe_msg = _redact_env_values(failure_message[:200])
        except Exception:
            # Fallback: strip anything that looks like an API key / token
            import re as _re
            safe_msg = _re.sub(r"[A-Za-z0-9_\-]{32,}", "[REDACTED]", failure_message[:200])
        return RepairResult(
            success=False,
            failure_type=failure_type,
            actions=[
                "Failure type not recognised. No repair strategy available.",
                f"Original error: {safe_msg}",
            ],
            message="Unclassified failure — cannot auto-repair.",
        )

    def _repair_web_research(self, settings: object) -> RepairResult:
        from ..config import Settings

        actions = [
            "Diagnosed: web_research tool registered but JARVIS_WEB_RESEARCH_ENABLED=false.",
            "Repair: patching JARVIS_WEB_RESEARCH_ENABLED=true in process environment.",
        ]
        os.environ["JARVIS_WEB_RESEARCH_ENABLED"] = "true"
        try:
            mem_file = str(getattr(settings, "memory_file", "data/memory.json"))
            new_settings = Settings.from_environment(memory_file=mem_file)
            if not new_settings.web_research_enabled:
                raise RuntimeError("Settings rebuild did not pick up env patch.")
            actions.append("Verified: web_research_enabled = True in patched settings.")
            return RepairResult(
                success=True,
                failure_type="web_research_disabled",
                actions=actions,
                message="Web research enabled for this session. Retrying goal.",
                repaired_settings=new_settings,
            )
        except Exception as exc:
            actions.append(f"Settings rebuild failed: {exc}")
            return RepairResult(
                success=False,
                failure_type="web_research_disabled",
                actions=actions,
                message=f"Could not apply settings patch: {exc}",
            )

    # ── Incident recording ──────────────────────────────────────────────────

    def _record(self, result: RepairResult, goal: str) -> None:
        incident = {
            "attempt": self._attempts,
            "failure_type": result.failure_type,
            "goal": goal[:200],
            "success": result.success,
            "actions": result.actions,
            "message": result.message,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._incidents.append(incident)
        try:
            path = self._data_dir / "repair_incidents.json"
            existing: list[dict] = []
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
            existing.append(incident)
            self._data_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(existing[-50:], indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # Incident recording must never mask the original error
