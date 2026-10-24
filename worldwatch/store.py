"""One SQLite file in WAL mode. Times are ISO 8601 UTC strings, so they sort as text.

items         every Item; re-seeing one updates its content, keeps its first fetch time
source_state  per source: when it is next due, how many failures in a row, last success
runs          one row per fetch attempt — the evidence that it ran unattended
"""

from __future__ import annotations

import sqlite3
from dataclasses import astuple, fields
from datetime import datetime
from pathlib import Path

from .item import Item, iso_utc

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,
    source      TEXT NOT NULL,
    happened_at TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    summary     TEXT NOT NULL,
    lat         REAL,
    lon         REAL,
    country     TEXT,
    severity    TEXT,
    licence     TEXT NOT NULL,
    basis       TEXT NOT NULL CHECK (basis IN ('reported', 'inferred')),
    lang        TEXT,
    raw         TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_source_time ON items (source, happened_at);
CREATE TABLE IF NOT EXISTS source_state (
    source      TEXT PRIMARY KEY,
    next_due    TEXT NOT NULL,
    fail_count  INTEGER NOT NULL,
    last_ok_at  TEXT,
    last_error  TEXT,
    last_count  INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    n_items     INTEGER NOT NULL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS runs_started ON runs (started_at);
"""

ITEM_COLUMNS = [f.name for f in fields(Item)]
_UPDATABLE = [c for c in ITEM_COLUMNS if c not in ("id", "fetched_at")]
_INSERT_ITEM = (
    f"INSERT INTO items ({', '.join(ITEM_COLUMNS)}, updated_at) "
    f"VALUES ({', '.join('?' for _ in ITEM_COLUMNS)}, ?) "
    f"ON CONFLICT(id) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in _UPDATABLE)
    + ", updated_at = excluded.fetched_at"
)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {version} is newer than this code ({SCHEMA_VERSION})")
        with self.db:
            self.db.executescript(SCHEMA)
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self.db.close()

    def save_items(self, items: list[Item]) -> int:
        """All or nothing: one transaction, so a crash mid-save leaves the last good state."""
        with self.db:
            self.db.executemany(_INSERT_ITEM, [(*astuple(i), i.fetched_at) for i in items])
        return len(items)

    def count_items(self, source: str | None = None) -> int:
        if source:
            return self.db.execute("SELECT COUNT(*) FROM items WHERE source = ?", (source,)).fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def items_between(self, source: str, start: str, end: str, *, limit: int = 1000,
                      order: str = "happened_at DESC") -> list[sqlite3.Row]:
        if order not in ("happened_at DESC", "happened_at ASC"):
            raise ValueError("unsupported order")
        return self.db.execute(
            f"SELECT * FROM items WHERE source = ? AND happened_at >= ? AND happened_at < ? "
            f"ORDER BY {order}, id LIMIT ?",
            (source, start, end, limit),
        ).fetchall()

    def source_state(self, source: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM source_state WHERE source = ?", (source,)).fetchone()

    def all_source_states(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM source_state ORDER BY source").fetchall()

    def record_run(self, source: str, started: datetime, finished: datetime, *, ok: bool,
                   n_items: int, error: str | None, next_due: str, fail_count: int) -> None:
        finished_iso = iso_utc(finished)
        with self.db:
            self.db.execute(
                "INSERT INTO runs (source, started_at, finished_at, ok, n_items, error) VALUES (?, ?, ?, ?, ?, ?)",
                (source, iso_utc(started), finished_iso, int(ok), n_items, error),
            )
            self.db.execute(
                "INSERT INTO source_state (source, next_due, fail_count, last_ok_at, last_error, last_count) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source) DO UPDATE SET next_due = excluded.next_due, "
                "fail_count = excluded.fail_count, "
                "last_ok_at = COALESCE(excluded.last_ok_at, source_state.last_ok_at), "
                "last_error = excluded.last_error, "
                "last_count = COALESCE(excluded.last_count, source_state.last_count)",
                (source, next_due, fail_count, iso_utc(started) if ok else None, error, n_items if ok else None),
            )

    def defer(self, source: str, next_due: str) -> None:
        """Push a source's next turn back without counting a failure or a run."""
        with self.db:
            self.db.execute(
                "INSERT INTO source_state (source, next_due, fail_count) VALUES (?, ?, 0) "
                "ON CONFLICT(source) DO UPDATE SET next_due = excluded.next_due",
                (source, next_due),
            )

    def runs_since(self, start: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM runs WHERE started_at >= ? ORDER BY started_at, id", (start,)
        ).fetchall()
