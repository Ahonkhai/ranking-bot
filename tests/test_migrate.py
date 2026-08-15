"""Importing the legacy data.json, upgrading an older schema, and the caches
that replaced the old unbounded dicts."""

import json
import sqlite3

from rankbot import caches, db, migrate, store
from tests.conftest import CHAT

V1_SCHEMA = """
CREATE TABLE chats(chat_id INTEGER PRIMARY KEY, title TEXT,
  current_season INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE seasons(chat_id INTEGER, season_id INTEGER, name TEXT,
  started_at TEXT, ended_at TEXT, PRIMARY KEY(chat_id, season_id));
CREATE TABLE members(chat_id INTEGER, user_id INTEGER,
  username TEXT COLLATE NOCASE, full_name TEXT, last_seen TEXT,
  PRIMARY KEY(chat_id, user_id));
CREATE TABLE ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
  season_id INTEGER, user_id INTEGER, delta INTEGER, reason TEXT,
  actor_id INTEGER, txn TEXT, created_at TEXT, voided_by INTEGER, voids INTEGER);
PRAGMA user_version=1;
"""

LEGACY = {
    "users": {
        "8919108828": {"name": "@xxxo714", "cash": 12200},
        "5176849097": {"name": "@Charan1326", "cash": 5000},
        "4444444444": {"name": "No Handle Person", "cash": 0},
    }
}


def write_legacy(tmp_path, payload=None):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(payload if payload is not None else LEGACY),
                    encoding="utf-8")
    return str(path)


def test_import_creates_one_opening_entry_per_member(fresh_db, tmp_path):
    path = write_legacy(tmp_path)
    result = migrate.import_into(CHAT, path)
    assert result["imported"] == 3

    board = store.standings(CHAT)
    assert [r["balance"] for r in board] == [12200, 5000, 0]
    assert board[0]["name"] == "@xxxo714"
    # A name that wasn't a handle is kept as a full name, not a fake handle.
    assert board[2]["name"] == "No Handle Person"


def test_import_is_refused_a_second_time(fresh_db, tmp_path):
    path = write_legacy(tmp_path)
    migrate.import_into(CHAT, path)
    again = migrate.import_into(CHAT, path)
    assert again["imported"] == 0
    assert "already has ledger entries" in again["reason"]
    assert len(store.standings(CHAT)) == 3


def test_dry_run_writes_nothing(fresh_db, tmp_path):
    path = write_legacy(tmp_path)
    result = migrate.import_into(CHAT, path, dry_run=True)
    assert result["imported"] == 3
    assert store.standings(CHAT) == []


def test_missing_or_broken_legacy_file_is_survivable(fresh_db, tmp_path):
    assert migrate.read_legacy(str(tmp_path / "nope.json")) == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert migrate.read_legacy(str(broken)) == {}


def test_malformed_records_are_skipped_not_fatal(fresh_db, tmp_path):
    path = write_legacy(tmp_path, {"users": {
        "123": {"name": "@good", "cash": 10},
        "abc": {"name": "@bad-id", "cash": 10},
        "456": {"name": "@bad-cash", "cash": "lots"},
    }})
    parsed = migrate.read_legacy(path)
    assert set(parsed) == {123}


def test_split_name():
    assert migrate.split_name("@Dave") == ("Dave", None)
    assert migrate.split_name("Dave Smith") == (None, "Dave Smith")
    assert migrate.split_name("") == (None, None)


# ── schema upgrade ───────────────────────────────────────────────────────

def test_a_v1_database_upgrades_in_place(tmp_path, monkeypatch):
    """An existing file predates members.joined_at; opening it must add the
    column and backfill it rather than losing the member."""
    path = tmp_path / "v1.db"
    raw = sqlite3.connect(str(path))
    raw.executescript(V1_SCHEMA)
    raw.executescript(
        "INSERT INTO chats VALUES(-1,'Old',1,'2026-01-12T10:00:00+00:00');"
        "INSERT INTO members VALUES(-1,7,'legacy','Legacy','2026-06-01T10:00:00+00:00');"
        "INSERT INTO ledger VALUES(1,-1,1,7,12200,'seed',99,NULL,"
        "  '2026-01-12T10:00:00+00:00',NULL,NULL);"
    )
    raw.commit()
    raw.close()

    db.close()
    monkeypatch.setattr("rankbot.config.DB_PATH", str(path))
    conn = db.connect(str(path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(members)")}
        assert "joined_at" in columns
        # Backfilled from the earliest ledger entry, not from today.
        assert store.joined_at(-1, 7).startswith("2026-01-12")
        assert store.balance(-1, 7) == 12200
    finally:
        db.close()


def test_upgrading_twice_is_harmless(tmp_path, monkeypatch):
    path = tmp_path / "twice.db"
    db.close()
    monkeypatch.setattr("rankbot.config.DB_PATH", str(path))
    for _ in range(2):
        conn = db.connect(str(path))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        db.close()


# ── caches ───────────────────────────────────────────────────────────────

def test_ttl_cache_evicts_the_least_recently_used():
    cache = caches.TTLCache(maxsize=3)
    for i in range(3):
        cache.set(i, i)
    cache.get(0)            # 0 becomes most recent, so 1 is next out
    cache.set(3, 3)
    assert len(cache) == 3
    assert cache.get(1) is None
    assert cache.get(0) == 0


def test_ttl_cache_expires():
    cache = caches.TTLCache(maxsize=10, ttl=-1)   # already expired
    cache.set("k", "v")
    assert cache.get("k") is None


def test_drop_prefix_only_clears_the_matching_chat():
    cache = caches.TTLCache(maxsize=10)
    cache.set((111, "a"), 1)
    cache.set((111, "b"), 2)
    cache.set((222, "a"), 3)
    assert cache.drop_prefix((111,)) == 2
    assert cache.get((222, "a")) == 3
