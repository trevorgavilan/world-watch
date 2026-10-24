import sqlite3
import unittest
from dataclasses import replace

from tests.helpers import NOW, sample_item, temp_dir
from worldwatch.store import SCHEMA_VERSION, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.path = temp_dir() / "ww.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()

    def test_wal_and_schema_version(self):
        mode = self.store.db.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode, "wal")
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_save_and_read_back_every_field(self):
        item = sample_item(1, lat=19.4, lon=-99.1, country="MX", severity="M5.0")
        self.assertEqual(self.store.save_items([item]), 1)
        rows = self.store.items_between("test-src", "2026-10-23T00:00:00Z", "2026-10-24T00:00:00Z")
        self.assertEqual(len(rows), 1)
        got = rows[0]
        for field in ("id", "channel", "source", "happened_at", "fetched_at", "title", "url", "summary",
                      "lat", "lon", "country", "severity", "licence", "basis", "lang", "raw"):
            self.assertEqual(got[field], getattr(item, field), field)

    def test_resave_updates_content_but_keeps_first_fetch_time(self):
        first = sample_item(1)
        self.store.save_items([first])
        later = replace(sample_item(1, title="Revised"), fetched_at="2026-10-24T05:00:00Z")
        self.store.save_items([later])
        rows = self.store.items_between("test-src", "2026-10-23T00:00:00Z", "2026-10-24T00:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Revised")
        self.assertEqual(rows[0]["fetched_at"], first.fetched_at)
        self.assertEqual(rows[0]["updated_at"], "2026-10-24T05:00:00Z")

    def test_save_is_all_or_nothing(self):
        good = sample_item(1)
        broken = replace(sample_item(2), title=None)  # violates NOT NULL
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_items([good, broken])
        self.assertEqual(self.store.count_items(), 0)

    def test_source_state_round_trip(self):
        self.assertIsNone(self.store.source_state("usgs-quakes"))
        self.store.record_run("usgs-quakes", NOW, NOW, ok=True, n_items=3, error=None,
                              next_due="2026-10-24T00:05:00Z", fail_count=0)
        state = self.store.source_state("usgs-quakes")
        self.assertEqual(state["next_due"], "2026-10-24T00:05:00Z")
        self.assertEqual(state["fail_count"], 0)
        self.assertEqual(state["last_ok_at"], "2026-10-23T23:50:00Z")
        self.store.record_run("usgs-quakes", NOW, NOW, ok=False, n_items=0, error="boom",
                              next_due="2026-10-24T00:10:00Z", fail_count=1)
        state = self.store.source_state("usgs-quakes")
        self.assertEqual(state["last_ok_at"], "2026-10-23T23:50:00Z")  # a failure keeps the last success
        self.assertEqual(state["last_error"], "boom")
        self.assertEqual(len(self.store.runs_since("2026-10-23T00:00:00Z")), 2)

    def test_reopen_keeps_data(self):
        self.store.save_items([sample_item(1)])
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.count_items(), 1)


if __name__ == "__main__":
    unittest.main()
