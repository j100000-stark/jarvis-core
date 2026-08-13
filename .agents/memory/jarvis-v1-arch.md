---
name: JARVIS V1 architecture
description: Key decisions across brain selection, tool registry, memory tiers, voice pipeline, and test patterns.
---

## Brain selection priority
demo_mode > llm_enabled > local_provider_enabled > UnavailableBrain
Implemented in `jarvis/core/assistant.py` `__post_init__`.

## Tool boundary
LLM cannot call anything not registered in ToolRegistry. The registry is the ONLY surface exposed to the LLM. Tool names are casefolded on lookup. `build_default_registry()` now registers 11 tools.

## RemoteLLMBrain
Forces `plan.goal = goal` after parsing LLM response so Planner validation always passes regardless of LLM paraphrasing. Rolling 6-message conversation history.

## DemoBrain bypass
DemoBrain intentionally prefixes plan.goal with DEMO label. `run_goal()` bypasses Planner for demo mode. All other safety gates remain.

## JARVIS_LLM_API_KEY
Consumed directly from `os.environ` inside `remote_llm.py` — intentionally NOT stored in Settings.

## Version
Settings.version bumped to v1.0.0 in V1.

## Test pattern
All tests use `unittest.TestCase` with tempfile.TemporaryDirectory for isolation. Network calls are patched. MockLLMTransport for LLM tests.

**Why:** Standard library only, no pytest, no external test deps.
