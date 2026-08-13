"""Diagnostic utilities: error classification, sanitization, and structured error export.

Security contract
-----------------
Every sanitize_*() function MUST redact secrets before any error information
crosses the process boundary (subprocess stdout → Node.js → frontend browser).
Never return raw exception messages or tracebacks without first passing them
through sanitize_message() or sanitize_trace().

Design rationale
----------------
The Python subprocess prints one JSON object to stdout.  The Node.js runtime
picks it up and forwards it verbatim to the browser.  Any secret that reaches
this dict will reach the browser.  Redaction happens here, close to the data.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .recovery.manager import Incident

# ── Secret patterns ───────────────────────────────────────────────────────────
# Ordered most-specific first so overlapping patterns don't fire out of order.

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Known API key prefixes (OpenAI, Groq, Anthropic, generic sk-)
    re.compile(r'\bsk-[A-Za-z0-9_\-]{16,}', re.IGNORECASE),
    # Stripe-style / generic underscore-prefixed keys (sk_live_, sk_test_, pk_live_, rk_...)
    re.compile(r'\b[a-z]{2}_(?:live|test)_[A-Za-z0-9]{16,}', re.IGNORECASE),
    re.compile(r'\bsk_[A-Za-z0-9_\-]{16,}', re.IGNORECASE),
    re.compile(r'\bgsk_[A-Za-z0-9_\-]{16,}', re.IGNORECASE),
    re.compile(r'\bsk-ant-[A-Za-z0-9_\-]{16,}', re.IGNORECASE),
    # ElevenLabs keys (xi-api-key header or raw value)
    re.compile(r'xi-api-key[\s"\']*[:=][\s"\']*[A-Za-z0-9_\-]{16,}', re.IGNORECASE),
    re.compile(r'\b[0-9a-f]{32}\b'),          # 32-char hex (common ElevenLabs format)
    # Bearer / Authorization tokens in headers
    re.compile(r'Bearer\s+[A-Za-z0-9_.\-]{16,}', re.IGNORECASE),
    re.compile(r'Authorization[\s"\']*[:=][\s"\']*[A-Za-z0-9_.\-]{20,}', re.IGNORECASE),
    # Key=value style (e.g. "JARVIS_LLM_API_KEY=sk-...")
    re.compile(r'(?<==)[A-Za-z0-9+/]{24,}={0,2}'),
    # Long base64-like strings (≥ 40 chars) that look like secrets
    re.compile(r'\b[A-Za-z0-9+/]{40,}={0,2}\b'),
]

_REDACTED = "[REDACTED]"


def _redact_env_values(text: str) -> str:
    """Replace active env var values that look like secrets.

    Only replaces values ≥ 16 characters that look like tokens (alphanumeric
    with possible dashes/underscores), not short config values or paths.
    """
    for value in os.environ.values():
        if not value or len(value) < 16:
            continue
        # Heuristic: looks like a token (no spaces, mostly alphanumeric)
        if re.fullmatch(r'[A-Za-z0-9+/._\-]{16,}=*', value):
            text = text.replace(value, _REDACTED)
    return text


def sanitize_message(text: str) -> str:
    """Remove secrets from an error message string.

    Safe to call on empty strings or None-converted text.
    """
    if not text:
        return text
    result = _redact_env_values(text)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def sanitize_trace(trace: str) -> str:
    """Remove secrets from a Python traceback string.

    The sanitized trace is kept server-side (not forwarded to the browser),
    but this function is exposed so tests can verify redaction is sound.
    """
    if not trace:
        return trace
    result = _redact_env_values(trace)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


# ── Error classification ──────────────────────────────────────────────────────

# Map operation name prefix → component label
_OP_TO_COMPONENT: dict[str, str] = {
    "execute_goal_structured": "assistant",
    "respond":                 "assistant",
}

# Error types → component override
_TYPE_TO_COMPONENT: dict[str, str] = {
    "BrainUnavailableError":    "brain",
    "RemoteLLMConfigError":     "brain",
    "LocalProviderConfigError": "brain",
    "PlanValidationError":      "planner",
}

# Error types → short code
_TYPE_TO_CODE: dict[str, str] = {
    "BrainUnavailableError":    "BRAIN_UNAVAILABLE",
    "RemoteLLMConfigError":     "LLM_CONFIG_ERROR",
    "LocalProviderConfigError": "LOCAL_PROVIDER_ERROR",
    "ValueError":               "VALIDATION_ERROR",
    "TypeError":                "TYPE_ERROR",
    "TimeoutError":             "TIMEOUT",
    "ConnectionError":          "NETWORK_ERROR",
    "OSError":                  "IO_ERROR",
    "KeyError":                 "MISSING_KEY",
    "AttributeError":           "ATTRIBUTE_ERROR",
    "json.JSONDecodeError":     "MALFORMED_JSON",
    "JSONDecodeError":          "MALFORMED_JSON",
}

# Types that are definitively NOT auto-recoverable (need human/config intervention)
_UNRECOVERABLE_TYPES: frozenset[str] = frozenset({
    "BrainUnavailableError",
    "RemoteLLMConfigError",
    "LocalProviderConfigError",
    "SystemExit",
    "KeyboardInterrupt",
    "MemoryError",
    "RecursionError",
})


def _infer_component(error_type: str, operation: str) -> str:
    """Infer the failing component from the error type and operation string."""
    if error_type in _TYPE_TO_COMPONENT:
        return _TYPE_TO_COMPONENT[error_type]
    if operation.startswith("step:") or operation.startswith("retry:"):
        return "executor"
    for prefix, comp in _OP_TO_COMPONENT.items():
        if operation.startswith(prefix):
            return comp
    return "unknown"


def _infer_step(operation: str) -> str | None:
    """Extract failing step identifier from an executor operation string."""
    if operation.startswith("step:") or operation.startswith("retry:"):
        return operation.split(":", 1)[-1]
    return None


# ── Public API ────────────────────────────────────────────────────────────────


def build_execution_error(
    incident: "Incident",
    *,
    goal: str = "",
    failing_step: str | None = None,
) -> dict:
    """Build a structured, sanitized error dict safe for frontend consumption.

    The raw traceback is NOT included in the returned dict; it stays server-
    side inside the Incident object.

    Fields:
        code        — short machine-readable error code
        type        — Python exception class name
        message     — sanitized human-readable description
        component   — which subsystem raised the error
        step        — failing plan step ID if known (None otherwise)
        recoverable — whether a retry/workaround is likely to help
        incidentId  — sequential incident counter for this session
        operation   — internal operation name (safe to expose)
        timestamp   — ISO-8601 timestamp of the incident
    """
    error_type = incident.error_type
    operation  = incident.operation

    component   = _infer_component(error_type, operation)
    inferred_step = failing_step or _infer_step(operation)
    code        = _TYPE_TO_CODE.get(error_type, "EXECUTION_ERROR")
    recoverable = error_type not in _UNRECOVERABLE_TYPES

    return {
        "code":        code,
        "type":        error_type,
        "message":     sanitize_message(incident.message),
        "component":   component,
        "step":        inferred_step,
        "recoverable": recoverable,
        "incidentId":  incident.identifier,
        "operation":   operation,
        "timestamp":   incident.created_at,
    }
