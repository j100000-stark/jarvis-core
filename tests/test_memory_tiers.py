"""Tests for the tiered MemoryStore / MemoryManager (V1 upgrade)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis.memory import MemoryManager, MemoryRecord, MemoryStore


class TestMemoryStoreTiers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "memory.json"
        self.store = MemoryStore(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ── basic tier write/read ────────────────────────────────────────────

    def test_default_tier_is_long_term(self) -> None:
        record = self.store.remember("default fact")
        self.assertEqual(record.tier, "long_term")

    def test_explicit_long_term_tier(self) -> None:
        record = self.store.remember("explicit lt", tier="long_term")
        self.assertEqual(record.tier, "long_term")

    def test_episodic_tier(self) -> None:
        record = self.store.remember("task completed", tier="episodic")
        self.assertEqual(record.tier, "episodic")

    def test_system_tier(self) -> None:
        record = self.store.remember("name=JARVIS", tier="system")
        self.assertEqual(record.tier, "system")

    # ── search by tier ───────────────────────────────────────────────────

    def test_search_all_tiers(self) -> None:
        self.store.remember("lt fact", tier="long_term")
        self.store.remember("ep event", tier="episodic")
        self.store.remember("sys config", tier="system")
        results = self.store.search()
        self.assertEqual(len(results), 3)

    def test_search_filters_long_term(self) -> None:
        self.store.remember("lt fact", tier="long_term")
        self.store.remember("ep event", tier="episodic")
        results = self.store.search(tier="long_term")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "lt fact")

    def test_search_filters_episodic(self) -> None:
        self.store.remember("lt fact", tier="long_term")
        self.store.remember("ep event", tier="episodic")
        results = self.store.search(tier="episodic")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "ep event")

    def test_search_filters_system(self) -> None:
        self.store.remember("sys config", tier="system")
        self.store.remember("lt fact", tier="long_term")
        results = self.store.search(tier="system")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "sys config")

    def test_search_with_query_and_tier(self) -> None:
        self.store.remember("python is great", tier="long_term")
        self.store.remember("python event", tier="episodic")
        self.store.remember("java event", tier="episodic")
        results = self.store.search("python", tier="episodic")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "python event")

    # ── count by tier ────────────────────────────────────────────────────

    def test_count_total(self) -> None:
        self.store.remember("a", tier="long_term")
        self.store.remember("b", tier="episodic")
        self.store.remember("c", tier="system")
        self.assertEqual(self.store.count(), 3)

    def test_count_by_tier(self) -> None:
        self.store.remember("a", tier="long_term")
        self.store.remember("b", tier="episodic")
        self.store.remember("c", tier="episodic")
        self.assertEqual(self.store.count(tier="long_term"), 1)
        self.assertEqual(self.store.count(tier="episodic"), 2)
        self.assertEqual(self.store.count(tier="system"), 0)

    # ── forget ───────────────────────────────────────────────────────────

    def test_forget_specific_id(self) -> None:
        r1 = self.store.remember("keep this")
        r2 = self.store.remember("remove this")
        removed = self.store.forget(r2.identifier)
        self.assertTrue(removed)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.search()[0].content, "keep this")

    def test_forget_nonexistent_id(self) -> None:
        self.store.remember("fact")
        removed = self.store.forget(999)
        self.assertFalse(removed)
        self.assertEqual(self.store.count(), 1)

    def test_forget_persists_to_disk(self) -> None:
        r = self.store.remember("to remove")
        self.store.forget(r.identifier)
        reloaded = MemoryStore(self.path)
        self.assertEqual(reloaded.count(), 0)

    # ── clear ────────────────────────────────────────────────────────────

    def test_clear_all(self) -> None:
        self.store.remember("a")
        self.store.remember("b")
        count = self.store.clear()
        self.assertEqual(count, 2)
        self.assertEqual(self.store.count(), 0)

    def test_clear_by_tier(self) -> None:
        self.store.remember("lt", tier="long_term")
        self.store.remember("ep", tier="episodic")
        count = self.store.clear(tier="episodic")
        self.assertEqual(count, 1)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.count(tier="long_term"), 1)

    # ── persistence / backwards compatibility ────────────────────────────

    def test_tier_persists_to_disk(self) -> None:
        self.store.remember("persistent fact", tier="episodic")
        reloaded = MemoryStore(self.path)
        self.assertEqual(reloaded.count(tier="episodic"), 1)
        self.assertEqual(reloaded.search(tier="episodic")[0].content, "persistent fact")

    def test_old_records_without_tier_load_as_long_term(self) -> None:
        """Backward compatibility: records written without a tier field default to long_term."""
        legacy = [{"identifier": 1, "content": "old fact", "created_at": "2024-01-01T00:00:00+00:00"}]
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        store = MemoryStore(self.path)
        self.assertEqual(store.count(), 1)
        self.assertEqual(store.search()[0].tier, "long_term")

    def test_tier_in_serialised_json(self) -> None:
        self.store.remember("fact", tier="episodic")
        raw = json.loads(self.path.read_text())
        self.assertEqual(raw[0]["tier"], "episodic")


class TestMemoryManagerTiers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "memory.json"
        self.manager = MemoryManager(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_remember_text_uses_long_term(self) -> None:
        r = self.manager.remember_text("my name is San")
        self.assertEqual(r.tier, "long_term")

    def test_remember_episodic(self) -> None:
        r = self.manager.remember_episodic("completed goal: network check")
        self.assertEqual(r.tier, "episodic")

    def test_remember_system(self) -> None:
        r = self.manager.remember_system("llm_provider=openai")
        self.assertEqual(r.tier, "system")

    def test_search_long_term(self) -> None:
        self.manager.remember_text("fact one")
        self.manager.remember_episodic("event one")
        results = self.manager.search_long_term()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "fact one")

    def test_search_episodic(self) -> None:
        self.manager.remember_text("fact one")
        self.manager.remember_episodic("event one")
        results = self.manager.search_episodic()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "event one")

    def test_search_system(self) -> None:
        self.manager.remember_system("setting=value")
        results = self.manager.search_system()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "setting=value")

    def test_context_for_prioritises_long_term(self) -> None:
        self.manager.remember_text("lt: name is San")
        self.manager.remember_episodic("ep: task done")
        ctx = self.manager.context_for("name")
        # long_term match should appear first
        self.assertTrue(any("lt: name is San" in c for c in ctx))

    def test_context_for_falls_back_to_episodic(self) -> None:
        self.manager.remember_episodic("ep: important event")
        ctx = self.manager.context_for("event", limit=8)
        self.assertIn("ep: important event", ctx)

    def test_context_for_respects_limit(self) -> None:
        for i in range(10):
            self.manager.remember_text(f"fact {i}")
        ctx = self.manager.context_for("", limit=5)
        self.assertLessEqual(len(ctx), 5)

    def test_summary(self) -> None:
        self.manager.remember_text("a")
        self.manager.remember_episodic("b")
        self.manager.remember_system("c")
        summary = self.manager.summary()
        self.assertIn("long-term", summary)
        self.assertIn("episodic", summary)
        self.assertIn("system", summary)
        self.assertIn("3 total", summary)

    # ── remember / recall tool interaction ──────────────────────────────

    def test_remember_then_recall_same_session(self) -> None:
        self.manager.remember("my name is San")
        results = self.manager.search("name")
        self.assertEqual(len(results), 1)
        self.assertIn("San", results[0].content)

    def test_recall_empty_returns_all(self) -> None:
        self.manager.remember_text("fact 1")
        self.manager.remember_text("fact 2")
        results = self.manager.search("")
        self.assertEqual(len(results), 2)

    def test_recall_nonexistent_returns_empty(self) -> None:
        results = self.manager.search("totally unknown query xyz")
        self.assertEqual(results, [])

    def test_forget_works_through_manager(self) -> None:
        r = self.manager.remember_text("to forget")
        removed = self.manager.forget(r.identifier)
        self.assertTrue(removed)
        self.assertEqual(self.manager.count(), 0)


if __name__ == "__main__":
    unittest.main()
