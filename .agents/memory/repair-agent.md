---
name: RepairAgent + persistent config
description: Transactional repair lifecycle, config overlay precedence, and sanitization rules
---

## Persistent config overlay (Phase 10)
- `data/runtime_config.json` is the authoritative *mutable* config source; `ConfigStore` in `jarvis/config/config_store.py`.
- Precedence: env var > overlay file > dataclass default. `Settings.from_environment()` calls `ConfigStore().apply_to_environ()` (fills only unset env keys) on every build.
- `set_value()` writes file + os.environ atomically (tmp+replace); rejects non-`JARVIS_`/`REPAIR_` keys and any secret-looking key (API_KEY/SECRET/TOKEN/...).
- **Why:** os.environ-only patches were lost on restart; repairs must persist and survive reboots.

## RepairAgent (jarvis/recovery/repair_agent.py)
- Lifecycle: incident → diagnosis → root cause → plan → CHECKPOINT → patch → test → verify → retry, or ROLLBACK on any failure.
- Checkpoint snapshots allowlisted files AND the `JARVIS_*`/`REPAIR_*` env subset (`_env_snapshot.json`); rollback restores BOTH — a repair is only transactional if env mutations are undone too.
- Patch allowlist: only `data/runtime_config.json` + `data/memory.json`. Max 3 attempts per incident key. `SelfRepairManager` holds ONE shared RepairAgent so the budget is never reset per call.
- `_record()` sanitizes EVERY string field of the incident before persisting — callers cannot be trusted to pre-sanitize.
- Model slot: `REPAIR_LLM_PROVIDER`/`REPAIR_LLM_MODEL` (falls back to JARVIS_LLM_*); strategies are currently deterministic.

## TTS repair strategies (Phase 11)
- Categories flow verbatim from api-server tts.ts codes into `SelfRepairManager._classify`. Auth/voice/model → report user action (never invent IDs, never touch secrets); network/invalid-audio → one bounded retry; upstream → report only.

## Sanitization gotcha
- `sanitize_message` patterns live in jarvis/diagnostics.py; originally missed `sk_live_`-style underscore keys — new secret formats need a pattern AND a test in tests/test_repair_agent.py.
