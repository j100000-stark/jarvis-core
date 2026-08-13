---
name: Memory tiers
description: MemoryRecord tier field, backward compatibility, and MemoryManager tiered methods.
---

## Tiers
- `long_term` — explicit user facts ("remember my name is San")
- `episodic` — important events, completed tasks, session highlights
- `system` — JARVIS configuration / self-knowledge facts

## MemoryRecord
`tier: str = "long_term"` added as default field. Backward compatible: old JSON records without `tier` load as `"long_term"`.

## MemoryStore API additions
- `remember(content, tier="long_term")` — tier parameter
- `search(query, tier=None)` — filter by tier
- `count(tier=None)` — count by tier
- `forget(identifier)` — remove by id, returns bool
- `clear(tier=None)` — remove all or by tier, returns count

## MemoryManager additions
- `remember_text(content)` → long_term
- `remember_episodic(content)` → episodic
- `remember_system(content)` → system
- `search_long_term/episodic/system(query)` — tier-scoped search
- `context_for(query, limit)` — long_term first, then episodic up to limit
- `summary()` — human-readable count by tier

## max_items
Bumped default from 100 to 500 in V1.

**Why:** Short-term context is in RemoteLLMBrain's rolling history. Persistent memory needs tiers for retrieval relevance. Backward compatibility required for existing data/memory.json.
