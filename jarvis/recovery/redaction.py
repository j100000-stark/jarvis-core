"""Comprehensive secret redaction shared by the repair pipeline and generator.

One sanitizer for everything that leaves the process boundary or gets
persisted: diagnoses, file contents, filenames, transport errors, model
analyses, and test output.
"""

from __future__ import annotations

import os
import re

# Long token-like runs (API keys, JWTs, hashes)
_LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{32,}")
# Known credential prefixes even when short
_PREFIXED_KEY_RE = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|ghu|ghs|xox[abps]|glpat|npm_|AKIA)[A-Za-z0-9_\-]{8,}\b"
)
# key=value / key: value assignments for secret-ish names (any value length)
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|auth|credential)"
    r"(\s*[:=]\s*)([\"']?)[^\s\"'&;]+\3"
)
# credentials embedded in URLs: scheme://user:pass@host
_URL_CRED_RE = re.compile(r"(://[^/\s:@]+:)[^@/\s]+(@)")
# PEM-style private key / certificate blocks
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]+-----[\s\S]*?-----END [A-Z ]+-----"
)
# Env var names that are secrets by construction
_SENSITIVE_ENV_RE = re.compile(
    r"(?i)(secret|token|password|passwd|credential|api[_-]?key|private)"
)


def sanitize_text(text: str) -> str:
    """Redact secrets of every recognised shape, plus live env values."""
    # 1. Structural patterns FIRST — the env redactor may rewrite key names
    #    (e.g. "password" → "[REDACTED]"), which would break these matches.
    text = _PEM_RE.sub("[REDACTED_PEM]", text)
    text = _URL_CRED_RE.sub(r"\1[REDACTED]\2", text)
    text = _ASSIGNMENT_RE.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    text = _PREFIXED_KEY_RE.sub("[REDACTED]", text)
    text = _LONG_TOKEN_RE.sub("[REDACTED]", text)
    # 2. Exact current environment values — strongest signal.
    try:
        from ..diagnostics import _redact_env_values  # type: ignore[attr-defined]
        text = _redact_env_values(text)
    except Exception:
        pass
    for key, value in os.environ.items():
        if not value or value not in text:
            continue
        # Sensitive-named vars: redact any value >= 8 chars. Others only when
        # long enough to be token-like (avoids mangling PATH/HOME/etc.).
        threshold = 8 if _SENSITIVE_ENV_RE.search(key) else 24
        if len(value) >= threshold:
            text = text.replace(value, "[REDACTED]")
    return text


def contains_env_secret(text: str) -> str | None:
    """Return the NAME of an env var whose live value appears in text, if any.

    Used to fail-close: a generated patch that echoes a real secret is
    rejected outright rather than written to disk.
    """
    for key, value in os.environ.items():
        if not value or value not in text:
            continue
        if _SENSITIVE_ENV_RE.search(key) and len(value) >= 8:
            return key
        if len(value) >= 24:
            return key
    return None
