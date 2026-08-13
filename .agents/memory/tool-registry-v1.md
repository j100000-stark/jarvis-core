---
name: Tool registry V1
description: All 11 registered tools, their names, capabilities, and gating rules.
---

## Registered tools (sorted)
analyze_text, calculate, echo, network_status, recall, remember, report, security_status, system_status, time, web_research

## Key rules
- `web_research` is gated by `context.settings.web_research_enabled` (env: JARVIS_WEB_RESEARCH_ENABLED). If false, returns a clear error — never fabricates.
- `calculate` uses `ast.parse(mode='eval')` + recursive `_safe_eval()` — no `eval()`. Supports: +, -, *, /, **, %, //. Rejects calls, strings, imports.
- `network_status` uses `socket.create_connection()` to 1.1.1.1:53 and 8.8.8.8:53.
- `system_status` reads from `context.settings` and `context.memory.count()` — no subprocess.
- `remember` stores with `tier="long_term"`. `recall` searches `tier="long_term"` only.

## Files
- `jarvis/tools/builtin.py` — core tools (echo, time, remember, recall) + calls build_extended_registry_additions()
- `jarvis/tools/extended.py` — 7 V1 tools
- `jarvis/tools/__init__.py` — exports all

**Why:** Tool registry is the ONLY LLM-accessible surface. Gating web_research prevents unrestricted outbound access.
