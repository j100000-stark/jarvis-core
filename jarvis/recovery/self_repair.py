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
    # ── Full diagnostic record (spec: never a bare flag toggle) ──────────
    component: str = ""          # subsystem the failure belongs to
    root_cause: str = ""         # diagnosed root cause, sanitized
    evidence: str = ""           # sanitized failure message / observation
    files_involved: tuple[str, ...] = ()
    proposed_repair: str = ""    # what strategy was chosen and why
    tests_run: tuple[str, ...] = ()
    test_results: str = ""       # honest outcome; "" when no tests ran


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
        # One RepairAgent per manager so its per-incident attempt budget is
        # shared across all repairs in this session (never reset per call).
        self._repair_agent = None  # lazy — created on first use

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
        result = self._enrich_diagnostics(result, failure_message, failure_step)
        self._record(result, goal)
        return result

    def incident_count(self) -> int:
        return len(self._incidents)

    def reset_attempts(self) -> None:
        """Reset attempt counter — call between independent user goals."""
        self._attempts = 0

    # ── Diagnostics enrichment (spec: full diagnostic record) ───────────────

    _COMPONENT_MAP = {
        "tts_": "TextToSpeech",
        "web_research": "WebResearch",
        "tool_not_found": "ToolRegistry",
        "cloudflare_blocked": "LLMTransport",
        "auth_error": "LLMTransport",
        "rate_limited": "LLMTransport",
        "timeout": "Network",
        "network_error": "Network",
        "llm_error": "LLMBrain",
    }

    def _enrich_diagnostics(
        self, result: RepairResult, failure_message: str, failure_step: str | None
    ) -> RepairResult:
        """Fill the diagnostic-record fields so every incident is complete.

        Never overwrites values a strategy set explicitly; evidence is
        always sanitized before storage.
        """
        from dataclasses import replace

        component = result.component
        if not component:
            component = "Unknown"
            for prefix, name in self._COMPONENT_MAP.items():
                if result.failure_type.startswith(prefix) or result.failure_type == prefix:
                    component = name
                    break

        evidence = result.evidence or self._sanitize(failure_message[:300])
        if failure_step:
            evidence = f"step={failure_step}: {evidence}"
        root_cause = result.root_cause or (
            result.actions[0] if result.actions else result.message
        )
        proposed = result.proposed_repair or next(
            (a for a in result.actions if a.lower().startswith(("strategy", "repair", "fix"))),
            result.message,
        )
        return replace(
            result,
            component=component,
            root_cause=root_cause,
            evidence=evidence,
            proposed_repair=proposed,
            test_results=result.test_results
            or ("" if result.tests_run else "no automated tests executed for this repair"),
        )

    @staticmethod
    def _sanitize(text: str) -> str:
        """Redact anything that looks like a secret/token from diagnostics."""
        try:
            from ..diagnostics import _redact_env_values  # type: ignore[attr-defined]
            return _redact_env_values(text)
        except Exception:
            import re as _re
            return _re.sub(r"[A-Za-z0-9_\-]{32,}", "[REDACTED]", text)

    # ── Classification ──────────────────────────────────────────────────────

    def _classify(self, message: str, step: str | None) -> str:
        combined = f"{message} {step or ''}".lower()

        # TTS failure categories (spec Phase 11) — passed through verbatim
        # from the API server's structured TTS error codes.
        for tts_cat in (
            "tts_api_key_missing", "tts_auth_failed", "tts_voice_not_found",
            "tts_model_invalid", "tts_upstream_error", "tts_network_error",
            "tts_invalid_audio", "tts_playback_error",
            "tts_quota_or_billing", "tts_forbidden",
            "tts_voice_or_endpoint_not_found", "tts_invalid_request",
            "tts_rate_limited", "tts_upstream_server_error",
        ):
            if tts_cat in combined:
                return tts_cat

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
        if failure_type.startswith("tts_"):
            return self._repair_tts(failure_type)

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

    def _repair_tts(self, failure_type: str) -> RepairResult:
        """Dedicated TTS repair strategies (spec Phase 11).

        Never changes secrets, never invents voice IDs or model names.
        Transient categories signal a bounded retry; configuration/auth
        categories report the exact user action required.
        """
        if failure_type in ("tts_network_error", "tts_invalid_audio", "tts_rate_limited"):
            return RepairResult(
                success=True,  # bounded retry (attempt counter still applies)
                failure_type=failure_type,
                actions=[
                    f"Diagnosed: transient TTS failure ({failure_type}).",
                    "Strategy: retry synthesis once.",
                ],
                message=f"Transient TTS failure ({failure_type}) — retrying once.",
            )
        if failure_type == "tts_playback_error":
            return RepairResult(
                success=False,
                failure_type=failure_type,
                actions=[
                    "Diagnosed: audio playback failed in the browser (frontend), "
                    "not a synthesis failure (server).",
                    "Strategy: frontend falls back to browser SpeechSynthesis; "
                    "user may need to tap the mic button to unlock iOS audio.",
                ],
                message="Playback failed in the browser — synthesis itself succeeded.",
            )
        if failure_type in (
            "tts_api_key_missing", "tts_auth_failed",
            "tts_quota_or_billing", "tts_forbidden",
        ):
            return RepairResult(
                success=False,
                failure_type=failure_type,
                actions=[
                    f"Diagnosed: {failure_type}.",
                    "Secrets are never modified by self-repair.",
                    "User action required: verify ELEVENLABS_API_KEY in the secret "
                    "store, and check the ElevenLabs plan/quota for billing errors.",
                ],
                message="ElevenLabs auth/billing problem — user action required.",
            )
        if failure_type in (
            "tts_voice_not_found", "tts_model_invalid",
            "tts_voice_or_endpoint_not_found", "tts_invalid_request",
        ):
            return RepairResult(
                success=False,
                failure_type=failure_type,
                actions=[
                    f"Diagnosed: {failure_type}.",
                    "Self-repair never invents voice IDs or model names.",
                    "User action required: verify ELEVENLABS_VOICE_ID / ELEVENLABS_MODEL "
                    "against the ElevenLabs account.",
                ],
                message="ElevenLabs voice/model configuration error — user action required.",
            )
        # tts_upstream_error and anything else: report, no blind retry loop
        return RepairResult(
            success=False,
            failure_type=failure_type,
            actions=[
                f"Diagnosed: {failure_type} (ElevenLabs upstream).",
                "Strategy: report — upstream service errors are outside local control.",
            ],
            message="ElevenLabs upstream error — cannot repair locally.",
        )

    def _repair_web_research(self, settings: object) -> RepairResult:
        """Persistent configuration repair via the RepairAgent (spec Phase 10).

        Lifecycle: root cause → checkpoint → patch (ConfigStore, persists to
        runtime_config.json AND os.environ) → verify (Settings rebuild) →
        rollback on failure.  The patch survives process restarts because
        Settings.from_environment() applies the overlay on every boot.
        """
        from ..config import ConfigStore, Settings
        from .repair_agent import RepairAgent

        mem_file = str(getattr(settings, "memory_file", "data/memory.json"))
        store = ConfigStore()
        if self._repair_agent is None:
            self._repair_agent = RepairAgent(self._data_dir)
        agent = self._repair_agent
        rebuilt: dict = {}

        def _patch() -> list[str]:
            store.set_value("JARVIS_WEB_RESEARCH_ENABLED", "true")
            return [str(store.path)]

        def _verify() -> bool:
            new_settings = Settings.from_environment(memory_file=mem_file)
            if not new_settings.web_research_enabled:
                return False
            # Confirm persistence: the overlay file itself must carry the value
            if store.get("JARVIS_WEB_RESEARCH_ENABLED") != "true":
                return False
            rebuilt["settings"] = new_settings
            return True

        outcome = agent.run_repair(
            component="config",
            error_category="web_research_disabled",
            root_cause=(
                "web_research tool registered but web_research_enabled=False "
                "in runtime settings (JARVIS_WEB_RESEARCH_ENABLED unset or false)."
            ),
            repair_plan=[
                "Persist JARVIS_WEB_RESEARCH_ENABLED=true to runtime_config.json",
                "Mirror value into process environment",
                "Rebuild Settings and verify flag + persistence",
            ],
            patch=_patch,
            verify=_verify,
        )
        actions = list(outcome.incident.stages)
        if outcome.success:
            return RepairResult(
                success=True,
                failure_type="web_research_disabled",
                actions=actions,
                message="Web research enabled and persisted. Retrying goal.",
                repaired_settings=rebuilt.get("settings"),
            )
        return RepairResult(
            success=False,
            failure_type="web_research_disabled",
            actions=actions,
            message=f"Could not apply persistent config repair: {outcome.message}",
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
            # Full diagnostic record (spec §6)
            "component": result.component,
            "root_cause": result.root_cause,
            "evidence": result.evidence,
            "files_involved": list(result.files_involved),
            "proposed_repair": result.proposed_repair,
            "tests_run": list(result.tests_run),
            "test_results": result.test_results,
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
