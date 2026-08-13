---
name: Memory search fallback
description: Why memory retrieval needs token matching + recent fallback, not phrase substring
---

- `MemoryStore.search` matches when the full query is a substring OR any query token (≥3 chars, casefold) appears in content. `MemoryStore.recent(limit, tier)` returns newest records unconditionally.
- `Planner.create_plan` and `RecallTool` fall back to the most recent memories (clearly labelled in the tool output) when search returns nothing.
- **Why:** "Come mi chiamo?" shares no substring/tokens with the stored "User's name is Sandeep" — pure phrase matching gave the LLM zero context and it honestly answered "I don't know your name". Cross-language (IT question ↔ EN fact) retrieval only works via the recent-memories fallback feeding facts into the plan prompt.
- **How to apply:** any new retrieval path must include the recent-fallback, and E2E-verify with the Italian name test (store "Mi chiamo X. Ricordalo." → ask "Come mi chiamo?").
