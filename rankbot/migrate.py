"""One-shot import of the legacy data.json into a chat's ledger.

The old format had no chat_id, so the target chat has to be named explicitly —
either on the command line or by an admin running /adoptlegacy in the group
that the scores actually belong to.

    python -m rankbot.migrate --chat -1001234567890
    python -m rankbot.migrate --chat -1001234567890 --dry-run
"""

import argparse
import json
import logging
import os

from . import config, db, store

log = logging.getLogger("rankbot.migrate")


def read_legacy(path: str | None = None) -> dict[int, dict]:
    """Parse data.json into {user_id: {"name":…, "cash":…}}. Empty when absent."""
    path = path or config.DATA_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.error("could not read %s: %s", path, e)
        return {}

    out = {}
    for uid, rec in (raw.get("users") or {}).items():
        try:
            out[int(uid)] = {"name": rec.get("name") or f"User{uid}",
                             "cash": int(rec.get("cash") or 0)}
        except (TypeError, ValueError):
            log.warning("skipping malformed legacy record %r", uid)
    return out


def split_name(name: str) -> tuple[str | None, str | None]:
    """Legacy stored one display string. '@handle' was a username; anything
    else was a full name."""
    name = (name or "").strip()
    if name.startswith("@") and len(name) > 1:
        return name[1:], None
    return None, (name or None)


def chat_has_ledger(chat_id: int) -> bool:
    row = db.get().execute(
        "SELECT 1 FROM ledger WHERE chat_id=? LIMIT 1", (chat_id,)
    ).fetchone()
    return row is not None


def import_into(chat_id: int, path: str | None = None, dry_run: bool = False) -> dict:
    """Import legacy scores as one opening ledger entry per member."""
    legacy = read_legacy(path)
    if not legacy:
        return {"imported": 0, "skipped": 0, "reason": "no legacy data found"}

    store.ensure_chat(chat_id)
    if chat_has_ledger(chat_id):
        return {"imported": 0, "skipped": len(legacy),
                "reason": "this chat already has ledger entries"}
    if dry_run:
        return {"imported": len(legacy), "skipped": 0, "reason": "dry run",
                "preview": legacy}

    season = store.current_season(chat_id)
    ts = store.now_iso()
    with db.write() as c:
        for uid, rec in legacy.items():
            username, full_name = split_name(rec["name"])
            c.execute(
                "INSERT OR REPLACE INTO members(chat_id,user_id,username,full_name,last_seen)"
                " VALUES (?,?,?,?,?)",
                (chat_id, uid, username, full_name, ts),
            )
            c.execute(
                "INSERT INTO ledger(chat_id,season_id,user_id,delta,reason,actor_id,txn,created_at)"
                " VALUES (?,?,?,?,?,?,NULL,?)",
                (chat_id, season, uid, rec["cash"], "imported from data.json", 0, ts),
            )
    log.info("imported %d legacy members into chat %s", len(legacy), chat_id)
    return {"imported": len(legacy), "skipped": 0, "reason": "ok"}


def pending_notice() -> str | None:
    """Startup hint: legacy file present but nothing imported anywhere yet."""
    if not read_legacy():
        return None
    row = db.get().execute("SELECT 1 FROM ledger LIMIT 1").fetchone()
    if row is not None:
        return None
    return (
        f"{config.DATA_FILE} holds legacy scores that have not been imported. "
        "Run /adoptlegacy as an admin in the group they belong to, or "
        "`python -m rankbot.migrate --chat <chat_id>`."
    )


def main() -> None:
    from .logging_setup import setup
    setup()
    ap = argparse.ArgumentParser(description="Import legacy data.json into the ledger")
    ap.add_argument("--chat", type=int, required=True, help="target chat id")
    ap.add_argument("--file", default=None, help="path to data.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db.connect()
    result = import_into(args.chat, args.file, args.dry_run)
    print(f"{result['reason']}: imported={result['imported']} skipped={result['skipped']}")
    for uid, rec in (result.get("preview") or {}).items():
        print(f"  {uid:>12}  {rec['name']:<24} {rec['cash']:>12,}")


if __name__ == "__main__":
    main()
