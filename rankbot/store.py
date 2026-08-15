"""Ledger operations.

A member's balance is never stored — it is SUM(delta) over their non-voided
ledger rows. Nothing overwrites anything, so a bad write cannot destroy a
previous one, and undo / history / seasons are queries rather than features.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from . import db

log = logging.getLogger("rankbot.store")

SCOPES = ("season", "week", "month", "alltime")
SCOPE_LABELS = {
    "season":  "THIS SEASON",
    "week":    "LAST 7 DAYS",
    "month":   "LAST 30 DAYS",
    "alltime": "ALL TIME",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ago_iso(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def display_from_parts(username: str | None, full_name: str | None, user_id: int) -> str:
    """The one place a member's on-screen name is decided."""
    if username:
        return f"@{username}"
    if full_name:
        return full_name
    return f"User{user_id}"


def row_name(row) -> str:
    return display_from_parts(row["username"], row["full_name"], row["user_id"])


# ── chats & seasons ──────────────────────────────────────────────────────

def ensure_chat(chat_id: int, title: str | None = None) -> int:
    """Register the chat if new; return its current season id."""
    conn = db.get()
    row = conn.execute("SELECT current_season FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
    if row:
        if title:
            conn.execute("UPDATE chats SET title=? WHERE chat_id=?", (title, chat_id))
        return row["current_season"]
    ts = now_iso()
    with db.write() as c:
        c.execute(
            "INSERT OR IGNORE INTO chats(chat_id, title, current_season, created_at) VALUES (?,?,1,?)",
            (chat_id, title, ts),
        )
        c.execute(
            "INSERT OR IGNORE INTO seasons(chat_id, season_id, name, started_at) VALUES (?,1,?,?)",
            (chat_id, "Season 1", ts),
        )
    return 1


def current_season(chat_id: int) -> int:
    row = db.get().execute("SELECT current_season FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
    return row["current_season"] if row else ensure_chat(chat_id)


def close_season(chat_id: int, name: str | None = None) -> tuple[int, int]:
    """End the current season and open the next. History is kept."""
    old = current_season(chat_id)
    new = old + 1
    ts = now_iso()
    with db.write() as c:
        c.execute("UPDATE seasons SET ended_at=? WHERE chat_id=? AND season_id=?", (ts, chat_id, old))
        c.execute("UPDATE chats SET current_season=? WHERE chat_id=?", (new, chat_id))
        c.execute(
            "INSERT OR IGNORE INTO seasons(chat_id, season_id, name, started_at) VALUES (?,?,?,?)",
            (chat_id, new, name or f"Season {new}", ts),
        )
    return old, new


def hard_wipe(chat_id: int) -> int:
    """Delete every ledger row for this chat. Members and seasons survive."""
    with db.write() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM ledger WHERE chat_id=?", (chat_id,)).fetchone()["n"]
        c.execute("DELETE FROM ledger WHERE chat_id=?", (chat_id,))
    return n


# ── members ──────────────────────────────────────────────────────────────

# How stale last_seen may get before an ordinary message bothers to refresh it.
# Without this the passive observer would write to disk on every single message
# in the group.
SEEN_REFRESH_SECONDS = 600


def upsert_member(chat_id: int, user_id: int, username: str | None,
                  full_name: str | None) -> None:
    """Record or refresh what we know about a member.

    Called from the passive observer on every group message, so the common case
    has to be cheap: read first, and write only when a name actually changed or
    last_seen has gone stale.
    """
    # Kept in its original casing — the column collates NOCASE, so lookups
    # still match regardless of how it was typed.
    uname = (username or "").lstrip("@") or None
    conn = db.get()
    row = conn.execute(
        "SELECT username, full_name, last_seen FROM members WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    ).fetchone()
    ts = now_iso()

    if row is None:
        with db.write() as c:
            c.execute(
                "INSERT OR REPLACE INTO members"
                "(chat_id,user_id,username,full_name,last_seen,joined_at)"
                " VALUES (?,?,?,?,?,?)",
                (chat_id, user_id, uname, full_name, ts, ts),
            )
        return

    # Never blank out a name we know with one we weren't given.
    uname = uname or row["username"]
    full_name = full_name or row["full_name"]
    changed = (row["username"] != uname) or (row["full_name"] != full_name)

    stale = True
    if row["last_seen"]:
        try:
            seen = datetime.fromisoformat(row["last_seen"])
            stale = (datetime.now(timezone.utc) - seen).total_seconds() > SEEN_REFRESH_SECONDS
        except ValueError:
            stale = True

    if not changed and not stale:
        return

    with db.write() as c:
        c.execute(
            "UPDATE members SET username=?, full_name=?, last_seen=? WHERE chat_id=? AND user_id=?",
            (uname, full_name, ts, chat_id, user_id),
        )


def get_member(chat_id: int, user_id: int):
    return db.get().execute(
        "SELECT * FROM members WHERE chat_id=? AND user_id=?", (chat_id, user_id)
    ).fetchone()


def find_by_username(chat_id: int, username: str) -> list:
    """Every member in this chat holding that handle. Plural by design — the
    caller must refuse to act when this is ambiguous.

    The comparison is case-insensitive via the column's NOCASE collation.
    """
    uname = username.lstrip("@")
    return db.get().execute(
        "SELECT * FROM members WHERE chat_id=? AND username=?", (chat_id, uname)
    ).fetchall()


def member_name(chat_id: int, user_id: int) -> str:
    row = get_member(chat_id, user_id)
    if row is None:
        return f"User{user_id}"
    return display_from_parts(row["username"], row["full_name"], user_id)


def idle_members(chat_id: int, days: int) -> list[int]:
    cutoff = ago_iso(days=days)
    rows = db.get().execute(
        "SELECT user_id FROM members WHERE chat_id=? AND (last_seen IS NULL OR last_seen < ?)",
        (chat_id, cutoff),
    ).fetchall()
    return [r["user_id"] for r in rows]


# ── scope handling ───────────────────────────────────────────────────────

def _scope_clause(chat_id: int, scope: str) -> tuple[str, list]:
    if scope == "season":
        return "l.chat_id=? AND l.season_id=?", [chat_id, current_season(chat_id)]
    if scope == "week":
        return "l.chat_id=? AND l.created_at>=?", [chat_id, ago_iso(days=7)]
    if scope == "month":
        return "l.chat_id=? AND l.created_at>=?", [chat_id, ago_iso(days=30)]
    if scope == "alltime":
        return "l.chat_id=?", [chat_id]
    raise ValueError(f"unknown scope {scope!r}")


# ── reads ────────────────────────────────────────────────────────────────

def balance(chat_id: int, user_id: int, scope: str = "season") -> int:
    where, params = _scope_clause(chat_id, scope)
    row = db.get().execute(
        f"SELECT COALESCE(SUM(l.delta),0) AS bal FROM ledger l"
        f" WHERE {where} AND l.user_id=? AND l.voided_by IS NULL",
        (*params, user_id),
    ).fetchone()
    return int(row["bal"])


def standings(chat_id: int, scope: str = "season") -> list[dict]:
    """Every member with ledger activity in scope, best first.

    Ranks are standard competition ranking: equal balances share a rank and
    the next distinct balance skips the ones consumed (1, 2, 2, 4). The
    user_id tiebreak in ORDER BY only fixes the display order, so the listing
    is stable between calls.
    """
    where, params = _scope_clause(chat_id, scope)
    rows = db.get().execute(
        f"SELECT l.user_id AS user_id, COALESCE(SUM(l.delta),0) AS balance,"
        f"       m.username AS username, m.full_name AS full_name"
        f" FROM ledger l"
        f" LEFT JOIN members m ON m.chat_id=l.chat_id AND m.user_id=l.user_id"
        f" WHERE {where} AND l.voided_by IS NULL"
        f" GROUP BY l.user_id"
        f" ORDER BY balance DESC, l.user_id ASC",
        params,
    ).fetchall()

    out, rank, previous = [], 0, None
    for i, r in enumerate(rows):
        balance = int(r["balance"])
        if balance != previous:
            rank, previous = i + 1, balance
        out.append({
            "rank": rank,
            "user_id": r["user_id"],
            "balance": balance,
            "name": display_from_parts(r["username"], r["full_name"], r["user_id"]),
        })
    return out


def ranks_as_of(chat_id: int, scope: str, cutoff_iso: str) -> dict[int, int]:
    """Rank per member using only rows written before `cutoff_iso`.

    Feeds the ▲/▼ movement indicators. Only meaningful for cumulative scopes;
    the callers restrict it to season / alltime.
    """
    where, params = _scope_clause(chat_id, scope)
    rows = db.get().execute(
        f"SELECT l.user_id AS user_id, COALESCE(SUM(l.delta),0) AS balance"
        f" FROM ledger l"
        f" WHERE {where} AND l.voided_by IS NULL AND l.created_at < ?"
        f" GROUP BY l.user_id"
        f" ORDER BY balance DESC, l.user_id ASC",
        (*params, cutoff_iso),
    ).fetchall()

    out, rank, previous = {}, 0, None
    for i, r in enumerate(rows):
        balance = int(r["balance"])
        if balance != previous:
            rank, previous = i + 1, balance
        out[r["user_id"]] = rank
    return out


def rank_of(chat_id: int, user_id: int, scope: str = "season") -> tuple[int | None, int]:
    board = standings(chat_id, scope)
    for row in board:
        if row["user_id"] == user_id:
            return row["rank"], len(board)
    return None, len(board)


def lifetime_xp(chat_id: int, user_id: int) -> int:
    """Everything this member has ever been awarded, across all seasons.

    Only positive entries count, so XP never goes backwards when cash is
    deducted or a season resets — which is what makes it usable as a level.
    """
    row = db.get().execute(
        "SELECT COALESCE(SUM(delta),0) AS xp FROM ledger"
        " WHERE chat_id=? AND user_id=? AND delta>0 AND voided_by IS NULL",
        (chat_id, user_id),
    ).fetchone()
    return int(row["xp"])


def joined_at(chat_id: int, user_id: int) -> str | None:
    """Earliest date we can evidence for this member: their first ledger
    entry, else when they were first indexed."""
    row = db.get().execute(
        "SELECT MIN(created_at) AS first FROM ledger WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    ).fetchone()
    first = row["first"] if row else None
    if first:
        return first
    member = get_member(chat_id, user_id)
    if member is None:
        return None
    return member["joined_at"] or member["last_seen"]


def history(chat_id: int, user_id: int, limit: int = 10) -> list[dict]:
    rows = db.get().execute(
        "SELECT l.*, m.username AS a_username, m.full_name AS a_full_name"
        " FROM ledger l"
        " LEFT JOIN members m ON m.chat_id=l.chat_id AND m.user_id=l.actor_id"
        " WHERE l.chat_id=? AND l.user_id=? AND l.voids IS NULL"
        " ORDER BY l.id DESC LIMIT ?",
        (chat_id, user_id, limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "delta": r["delta"],
            "reason": r["reason"],
            "created_at": r["created_at"],
            "voided": r["voided_by"] is not None,
            "actor": display_from_parts(r["a_username"], r["a_full_name"], r["actor_id"]),
        }
        for r in rows
    ]


def held_rank_since(chat_id: int, user_id: int, days: int, rank: int = 1) -> bool:
    """True when the member was at `rank` or better at every daily checkpoint
    across the window, and still is.

    Sampled from the ledger rather than tracked in a column: the ledger can
    already reconstruct any past standing, so a "holding" streak needs no
    extra state that could drift out of step with the scores. A board younger
    than the window correctly fails — you can't have held it for a week.
    """
    if days <= 0:
        return rank_of(chat_id, user_id)[0] == rank

    for day in range(days, -1, -1):
        at = ranks_as_of(chat_id, "season", ago_iso(days=day)).get(user_id)
        if at is None or at > rank:
            return False
    return True


def recorded_achievements(chat_id: int, user_id: int) -> set[str]:
    rows = db.get().execute(
        "SELECT code FROM achievements WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    ).fetchall()
    return {r["code"] for r in rows}


def record_achievements(chat_id: int, user_id: int, codes, balance: int) -> None:
    """INSERT OR IGNORE against the primary key, so a race between two
    concurrent awards can't announce the same milestone twice."""
    ts = now_iso()
    with db.write() as c:
        c.executemany(
            "INSERT OR IGNORE INTO achievements"
            "(chat_id,user_id,code,unlocked_at,balance_at) VALUES (?,?,?,?,?)",
            [(chat_id, user_id, code, ts, balance) for code in codes],
        )


def achievement_log(chat_id: int, user_id: int) -> list[dict]:
    rows = db.get().execute(
        "SELECT code, unlocked_at, balance_at FROM achievements"
        " WHERE chat_id=? AND user_id=? ORDER BY balance_at, unlocked_at",
        (chat_id, user_id),
    ).fetchall()
    return [dict(r) for r in rows]


def window_delta(chat_id: int, user_id: int, days: int = 7) -> int:
    """Net change over the last `days`, for the rank card's 7-day chip."""
    row = db.get().execute(
        "SELECT COALESCE(SUM(delta),0) AS d FROM ledger"
        " WHERE chat_id=? AND user_id=? AND voided_by IS NULL AND created_at>=?",
        (chat_id, user_id, ago_iso(days=days)),
    ).fetchone()
    return int(row["d"])


def peak_balance(chat_id: int, user_id: int) -> int:
    """Highest balance held at any point this season.

    A running SUM() OVER the member's entries — cheap, and only possible
    because the ledger keeps every step rather than just the final number.
    """
    season = current_season(chat_id)
    row = db.get().execute(
        "SELECT MAX(running) AS peak FROM ("
        "  SELECT SUM(delta) OVER (ORDER BY id) AS running FROM ledger"
        "  WHERE chat_id=? AND season_id=? AND user_id=? AND voided_by IS NULL"
        ")",
        (chat_id, season, user_id),
    ).fetchone()
    return int(row["peak"] or 0)


def chat_stats(chat_id: int) -> dict:
    conn = db.get()
    season = current_season(chat_id)
    row = conn.execute(
        "SELECT COUNT(DISTINCT user_id) AS members, COUNT(*) AS entries,"
        "       COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) AS awarded"
        " FROM ledger WHERE chat_id=? AND season_id=? AND voided_by IS NULL",
        (chat_id, season),
    ).fetchone()
    week = conn.execute(
        "SELECT COUNT(*) AS entries FROM ledger WHERE chat_id=? AND created_at>=? AND voided_by IS NULL",
        (chat_id, ago_iso(days=7)),
    ).fetchone()
    return {
        "season": season,
        "members": row["members"],
        "entries": row["entries"],
        "awarded": int(row["awarded"]),
        "entries_week": week["entries"],
    }


# ── writes ───────────────────────────────────────────────────────────────

def _insert(conn, chat_id, season, user_id, delta, actor_id, reason, txn, voids=None) -> int:
    cur = conn.execute(
        "INSERT INTO ledger(chat_id,season_id,user_id,delta,reason,actor_id,txn,created_at,voids)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (chat_id, season, user_id, delta, reason, actor_id, txn, now_iso(), voids),
    )
    return cur.lastrowid


def award(chat_id: int, user_id: int, delta: int, actor_id: int, reason: str = "") -> int:
    """Append a signed adjustment. Returns the new season balance."""
    season = current_season(chat_id)
    with db.write() as c:
        _insert(c, chat_id, season, user_id, delta, actor_id, reason, None)
    return balance(chat_id, user_id)


def set_balance(chat_id: int, user_id: int, target: int, actor_id: int) -> tuple[int, int]:
    """Set to an exact number by appending the difference.

    Read and write happen inside one IMMEDIATE transaction so two admins
    setting at once can't both compute their delta from the same stale total.
    """
    season = current_season(chat_id)
    with db.write() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(delta),0) AS bal FROM ledger"
            " WHERE chat_id=? AND season_id=? AND user_id=? AND voided_by IS NULL",
            (chat_id, season, user_id),
        ).fetchone()
        cur_bal = int(row["bal"])
        delta = target - cur_bal
        _insert(c, chat_id, season, user_id, delta, actor_id, f"set to {target}", None)
    return delta, target


def deduct(chat_id: int, user_id: int, amount: int, actor_id: int) -> tuple[int, int]:
    """Remove up to `amount`, flooring the balance at zero.
    Returns (actually_removed, new_balance)."""
    season = current_season(chat_id)
    with db.write() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(delta),0) AS bal FROM ledger"
            " WHERE chat_id=? AND season_id=? AND user_id=? AND voided_by IS NULL",
            (chat_id, season, user_id),
        ).fetchone()
        cur_bal = int(row["bal"])
        removed = min(amount, max(cur_bal, 0))
        if removed:
            _insert(c, chat_id, season, user_id, -removed, actor_id, "removed", None)
        return removed, cur_bal - removed


class TransferError(Exception):
    pass


def transfer(chat_id: int, from_id: int, to_id: int, amount: int) -> tuple[int, int]:
    """Move points between members as one two-row transaction.
    Returns (sender_balance, recipient_balance)."""
    if from_id == to_id:
        raise TransferError("You can't send to yourself.")
    if amount <= 0:
        raise TransferError("Amount must be a positive number.")
    season = current_season(chat_id)
    txn = uuid.uuid4().hex
    with db.write() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(delta),0) AS bal FROM ledger"
            " WHERE chat_id=? AND season_id=? AND user_id=? AND voided_by IS NULL",
            (chat_id, season, from_id),
        ).fetchone()
        if int(row["bal"]) < amount:
            raise TransferError(f"You only have {int(row['bal']):,} to send.")
        _insert(c, chat_id, season, from_id, -amount, from_id, f"sent to {to_id}", txn)
        _insert(c, chat_id, season, to_id, amount, from_id, f"received from {from_id}", txn)
    return balance(chat_id, from_id), balance(chat_id, to_id)


def undo_last(chat_id: int, actor_id: int) -> dict | None:
    """Void the most recent entry (or transfer pair) in this chat.

    Nothing is deleted: the original rows get a voided_by stamp and a zero-delta
    audit row records who reversed what.
    """
    conn = db.get()
    target = conn.execute(
        "SELECT * FROM ledger WHERE chat_id=? AND voided_by IS NULL AND voids IS NULL"
        " ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    if target is None:
        return None

    if target["txn"]:
        group = conn.execute(
            "SELECT * FROM ledger WHERE chat_id=? AND txn=? AND voided_by IS NULL",
            (chat_id, target["txn"]),
        ).fetchall()
    else:
        group = [target]

    ids = [r["id"] for r in group]
    with db.write() as c:
        audit = _insert(
            c, chat_id, target["season_id"], target["user_id"], 0, actor_id,
            f"undo #{target['id']}", target["txn"], voids=target["id"],
        )
        c.executemany(
            "UPDATE ledger SET voided_by=? WHERE id=?",
            [(audit, i) for i in ids],
        )
    return {
        "id": target["id"],
        "user_id": target["user_id"],
        "delta": target["delta"],
        "reason": target["reason"],
        "actor_id": target["actor_id"],
        "rows": len(ids),
        "new_balance": balance(chat_id, target["user_id"]),
    }
