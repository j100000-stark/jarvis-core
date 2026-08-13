"""Tests for MemoryStore deduplication and persistence.

Tests are grouped into:
  1. Basic deduplication (upsert on identical content)
  2. Cross-session persistence (simulate restart by reloading from file)
  3. Update / delete / clear
  4. Edge cases
"""

import json
import tempfile
import unittest
from pathlib import Path

from jarvis.memory.store import MemoryRecord, MemoryStore


def _store(tmp: str) -> MemoryStore:
    return MemoryStore(Path(tmp) / "memory.json")


class TestDeduplication(unittest.TestCase):
    """Identical content must not create duplicate records."""

    def test_same_content_same_tier_no_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            r1 = s.remember("my name is Sandeep")
            r2 = s.remember("my name is Sandeep")
            self.assertEqual(r1.identifier, r2.identifier)
            self.assertEqual(s.count(), 1)

    def test_same_content_different_tier_both_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("my name is Sandeep", tier="long_term")
            s.remember("my name is Sandeep", tier="episodic")
            self.assertEqual(s.count(), 2)

    def test_case_insensitive_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("My name is Sandeep")
            s.remember("my name is sandeep")
            self.assertEqual(s.count(), 1)

    def test_whitespace_normalised_before_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("my   name  is  Sandeep")
            s.remember("my name is Sandeep")
            # Both normalise to the same cleaned string
            self.assertEqual(s.count(), 1)

    def test_upsert_refreshes_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            r1 = s.remember("the sky is blue")
            import time; time.sleep(0.01)
            r2 = s.remember("the sky is blue")
            self.assertGreaterEqual(r2.created_at, r1.created_at)

    def test_repeated_remember_does_not_grow_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            for _ in range(10):
                s.remember("always the same fact")
            self.assertEqual(s.count(), 1)

    def test_distinct_facts_all_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("fact one")
            s.remember("fact two")
            s.remember("fact three")
            self.assertEqual(s.count(), 3)


class TestPersistence(unittest.TestCase):
    """Facts must survive process restart (reload from disk)."""

    def test_fact_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            s1 = MemoryStore(path)
            s1.remember("my name is Sandeep")

            s2 = MemoryStore(path)
            records = s2.search("Sandeep")
            self.assertEqual(len(records), 1)
            self.assertIn("Sandeep", records[0].content)

    def test_duplicate_check_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            s1 = MemoryStore(path)
            r1 = s1.remember("persistent fact")

            # Reload and try to add the same fact
            s2 = MemoryStore(path)
            r2 = s2.remember("persistent fact")
            self.assertEqual(r1.identifier, r2.identifier)
            self.assertEqual(s2.count(), 1)

    def test_all_tiers_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            s1 = MemoryStore(path)
            s1.remember("long term fact", tier="long_term")
            s1.remember("episodic event", tier="episodic")
            s1.remember("system info", tier="system")

            s2 = MemoryStore(path)
            self.assertEqual(s2.count(tier="long_term"), 1)
            self.assertEqual(s2.count(tier="episodic"), 1)
            self.assertEqual(s2.count(tier="system"), 1)

    def test_json_file_valid_after_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            s = MemoryStore(path)
            s.remember("fact")
            s.remember("fact")  # upsert
            data = json.loads(path.read_text())
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)


class TestUpdateDeleteClear(unittest.TestCase):
    def test_forget_removes_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            r = s.remember("to be forgotten")
            self.assertTrue(s.forget(r.identifier))
            self.assertEqual(s.count(), 0)

    def test_forget_unknown_id_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            self.assertFalse(s.forget(9999))

    def test_clear_removes_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("a"); s.remember("b"); s.remember("c")
            removed = s.clear()
            self.assertEqual(removed, 3)
            self.assertEqual(s.count(), 0)

    def test_clear_by_tier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("lt", tier="long_term")
            s.remember("ep", tier="episodic")
            s.clear(tier="long_term")
            self.assertEqual(s.count(tier="long_term"), 0)
            self.assertEqual(s.count(tier="episodic"), 1)

    def test_update_does_not_create_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("original fact")
            s.remember("original fact")
            self.assertEqual(s.count(), 1)


class TestEdgeCases(unittest.TestCase):
    def test_empty_content_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            with self.assertRaises(ValueError):
                s.remember("")

    def test_whitespace_only_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            with self.assertRaises(ValueError):
                s.remember("   ")

    def test_max_items_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = MemoryStore(Path(tmp) / "m.json", max_items=3)
            for i in range(5):
                s.remember(f"unique fact {i}")
            self.assertLessEqual(s.count(), 3)

    def test_search_returns_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            s = _store(tmp)
            s.remember("alpha")
            s.remember("beta")
            results = s.search("")
            self.assertEqual(results[0].content, "beta")


if __name__ == "__main__":
    unittest.main()
