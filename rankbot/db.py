"""SQLite connection and schema.

WAL mode gives us safe concurrent readers and real transactions, which is what
the old mtime-stamp / temp-file / rolling-backup apparatus was approximating.
"""

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager

from . import config

log = logging.getLogger("rankbot.db")

SCHEMA_VERSION = 2

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  chat_id        INTEGER PRIMARY KEY,
  title          TEXT,
  current_season INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS seasons (
  chat_id    INTEGER NOT NULL,
  season_id  INTEGER NOT NULL,
  name       TEXT,
  started_at TEXT    NOT NULL,
  ended_at   TEXT,
  PRIMARY KEY (chat_id, season_id)
);

-- username is stored with its original casing for display, but compares and
-- indexes case-insensitively: Telegram handles are case-insensitive, so
-- @Charan1326 and @charan1326 must resolve to the same member.
CREATE TABLE IF NOT EXISTS members (
  chat_id   INTEGER NOT NULL,
  user_id   INTEGER NOT NULL,
  username  TEXT COLLATE NOCASE,
  full_name TEXT,
  last_seen TEXT,
  joined_at TEXT,
  PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_members_username ON members(chat_id, username);

-- Append-only. `delta` is signed; a "set to N" is stored as the difference
-- from the current balance, so history is never rewritten. Undo flags rows
-- via voided_by instead of deleting them.
CREATE TABLE IF NOT EXISTS ledger (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id    INTEGER NOT NULL,
  season_id  INTEGER NOT NULL,
  user_id    INTEGER NOT NULL,
  delta      INTEGER NOT NULL,
  reason     TEXT,
  actor_id   INTEGER NOT NULL,
  txn        TEXT,
  created_at TEXT    NOT NULL,
  voided_by  INTEGER,
  voids      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_ledger_board ON ledger(chat_id, season_id, user_id);
CREATE INDEX IF NOT EXISTS ix_ledger_time  ON ledger(chat_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ledger_txn   ON ledger(chat_id, txn);
"""


def storage_warning() -> str | None:
    """Flag storage that won't survive a redeploy, before anyone loses a board."""
    if config.VOLUME_MOUNT:
        return None
    if config.ON_RAILWAY:
        return (
            f"No Railway Volume is attached, so {config.DB_PATH} lives in the "
            "container filesystem and EVERY REDEPLOY STARTS FROM AN EMPTY "
            "BOARD. Fix: service -> Settings -> Volumes -> attach one (any "
            "mount path). The bot puts its database there automatically on the "
            "next boot."
        )
    return None


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open (once) and return the shared connection."""
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        target = path or config.DB_PATH
        directory = os.path.dirname(os.path.abspath(target))
        os.makedirs(directory, exist_ok=True)
        existed = os.path.exists(target)
        conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        was = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.executescript(SCHEMA)
        _upgrade(conn, was)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        _conn = conn

        where = (f"persistent volume {config.VOLUME_MOUNT}" if config.VOLUME_MOUNT
                 else "local filesystem")
        log.info("database ready at %s (schema v%d, %s, %s)",
                 target, SCHEMA_VERSION, where,
                 "existing" if existed else "newly created")
        warning = storage_warning()
        if warning:
            log.warning(warning)
        elif not existed and config.VOLUME_MOUNT:
            log.info("no database on the volume yet — starting a fresh board")
        return conn


def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _upgrade(conn: sqlite3.Connection, from_version: int) -> None:
    """Bring an existing file up to SCHEMA_VERSION.

    CREATE TABLE IF NOT EXISTS above leaves older tables alone, so columns
    added after v1 have to be applied here.
    """
    if from_version >= SCHEMA_VERSION:
        return

    if "joined_at" not in _columns(conn, "members"):
        log.info("migrating schema: adding members.joined_at")
        conn.execute("ALTER TABLE members ADD COLUMN joined_at TEXT")

    # Backfill from the earliest thing we know about each member: their first
    # ledger entry, else whenever we last saw them.
    conn.execute(
        "UPDATE members SET joined_at = COALESCE("
        "  (SELECT MIN(l.created_at) FROM ledger l"
        "    WHERE l.chat_id = members.chat_id AND l.user_id = members.user_id),"
        "  last_seen)"
        " WHERE joined_at IS NULL"
    )


def get() -> sqlite3.Connection:
    return _conn if _conn is not None else connect()


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


@contextmanager
def write():
    """A write transaction. BEGIN IMMEDIATE takes the lock up front so a
    read-then-write (balance -> delta) can't interleave with another writer."""
    conn = get()
    with _lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
