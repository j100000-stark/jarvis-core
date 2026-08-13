---
name: Backend watchdog + code repair pipeline
description: Rules for the frontend reconnect watchdog, single-source outage reporting, and the safe AI code-repair pipeline.
---

# Backend watchdog (frontend)
- `use-backend-watchdog.ts` probes `/api/healthz`; 10 s heartbeat when online, exponential backoff 1 s→15 s when offline. Sequence: BACKEND OFFLINE → RECONNECTING → HEALTH CHECK → BACKEND ONLINE → RECONNECTING SERVICES → JARVIS READY.
- **Why effect-local state:** React 18 Strict Mode double-mounts; a shared `inFlightRef` let a cancelled effect instance strand the heartbeat forever. All timers/in-flight flags must be owned by the effect instance.
- Watchdog is the SINGLE source of outage reporting — react-query polling errors must not push their own terminal lines (contradictory OFFLINE/ONLINE messages otherwise).
- Recovery restoration is read-only (invalidate GET queries; never replay POSTs). Recognition reset uses `wakeWord.restart()` — `pause()` alone never re-arms when `enabled` didn't toggle during the outage.

# Code repair pipeline (jarvis/recovery/code_repair.py)
- Patch is applied ONLY if: allowlist + resolved-path containment (symlink check) + AST/JSON validation pass, the patch touches only the identified files, AND at least one verification mechanism (test command or runtime verify) exists; otherwise refuse to apply. Dry-run (REPAIR_DRY_RUN) validates without applying.
- Rollback snapshots are read from DISK just before apply (None = file absent → delete on rollback). Never snapshot from the pre-loaded file map.
- Sanitize failure messages and test output before persisting incidents; never persist raw patch contents (sizes only).

# Repair generator (jarvis/recovery/repair_generator.py)
- Dedicated repair model: REPAIR_LLM_PROVIDER/MODEL/API_KEY (falls back to JARVIS_LLM_*), fully separate from the reasoning brain; pipeline opts in via `use_llm_generator=True` — never contacts a provider silently (keeps tests hermetic).
- Missing config/unreachable provider → RepairGeneratorUnavailable → honest "REPAIR_GENERATOR UNAVAILABLE" report, never a fake repair.
- All outbound context (diagnosis, file contents, filenames) and inbound analyses go through `redaction.sanitize_text`; structural regexes (PEM/URL-creds/key=value/prefixed tokens) must run BEFORE env-value redaction or key-name rewriting breaks the matches.
- Generated patches echoing a live env secret are rejected via `contains_env_secret` (fail closed) — never sanitize patch content in place, reject instead.
- Untrusted data goes inside `<untrusted-data>` delimiters; total prompt honors max_context_chars with per-file budget split.

# Network status truthfulness
- NetworkConnectivity has UNKNOWN (initial, "no live probe yet"); OFFLINE only ever results from a real failed probe. Adding an enum value requires updating openapi.yaml + `pnpm --filter @workspace/api-spec run codegen` + jarvis-runtime.ts type + system-panel badge map.

# NOT_ALLOWED recognition errors
- 'not-allowed'/'service-not-allowed' must never trigger a silent restart: map to MICROPHONE_PERMISSION_REQUIRED, show MICROPHONE PERMISSION_REQUIRED + RECOGNITION BLOCKED, set micPermission denied, and wait for a user gesture.
