"""Scheduled work: backups, the optional decay sweep, and a liveness digest."""

import html
import logging
import os
import sqlite3
from datetime import datetime

from . import achievements, caches, config, db, store

log = logging.getLogger("rankbot.jobs")


def backup_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)) or ".", "backups")


def snapshot() -> str | None:
    """Consistent copy of the live database via sqlite's own backup API.

    Safe to run while the bot is writing, unlike copying the file.
    """
    bdir = backup_dir()
    try:
        os.makedirs(bdir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(bdir, f"rankbot-{stamp}.db")
        dest = sqlite3.connect(path)
        try:
            db.get().backup(dest)
        finally:
            dest.close()

        snaps = sorted(f for f in os.listdir(bdir)
                       if f.startswith("rankbot-") and f.endswith(".db"))
        for old in snaps[:-config.BACKUP_KEEP]:
            try:
                os.remove(os.path.join(bdir, old))
            except OSError:
                pass
        return path
    except Exception:
        log.exception("backup failed")
        return None


async def backup_job(context) -> None:
    path = snapshot()
    if not path:
        return
    log.info("backup written: %s", path)

    # An off-box copy is the only kind that survives losing the machine.
    if not config.BACKUP_CHANNEL_ID:
        return
    try:
        size = os.path.getsize(path)
        if size > 45 * 1024 * 1024:
            log.warning("backup too large to send (%d bytes)", size)
            return
        with open(path, "rb") as f:
            await context.bot.send_document(
                chat_id=config.BACKUP_CHANNEL_ID,
                document=f,
                filename=os.path.basename(path),
                caption=f"Ranking bot backup — {size / 1024:.0f} KB",
            )
    except Exception:
        log.exception("could not ship backup off-box")


async def decay_job(context) -> None:
    """Bleed a percentage from members who've gone quiet. Off by default:
    silently taking points from people is opt-in behaviour."""
    if config.DECAY_PERCENT <= 0:
        return
    rows = db.get().execute("SELECT chat_id FROM chats").fetchall()
    for row in rows:
        chat_id = row["chat_id"]
        idle = set(store.idle_members(chat_id, config.DECAY_IDLE_DAYS))
        if not idle:
            continue
        touched = 0
        for entry in store.standings(chat_id):
            if entry["user_id"] not in idle or entry["balance"] <= 0:
                continue
            cut = int(entry["balance"] * config.DECAY_PERCENT / 100)
            if cut <= 0:
                continue
            store.award(chat_id, entry["user_id"], -cut, 0,
                        f"inactive {config.DECAY_IDLE_DAYS}d decay")
            touched += 1
        if touched:
            caches.invalidate_chat(chat_id)
            log.info("decay applied to %d members in %s", touched, chat_id)


async def achievements_job(context) -> None:
    """Daily sweep for milestones that come true with time rather than with a
    write — Champion is earned by *still* being #1 after N days, so nothing in
    the command path would ever notice it."""
    rows = db.get().execute("SELECT chat_id FROM chats").fetchall()
    for row in rows:
        chat_id = row["chat_id"]
        try:
            unlocked = achievements.check_board(chat_id)
        except Exception:
            log.exception("achievement sweep failed for %s", chat_id)
            continue
        if not unlocked:
            continue

        caches.invalidate_chat(chat_id)
        lines = ["🏆 <b>Achievement unlocked!</b>", ""]
        for user_id, earned in unlocked:
            best = achievements.headline(earned)
            if best is None:
                continue
            who = store.member_name(chat_id, user_id)
            lines.append(f"<b>{html.escape(who)}</b> — {best.emoji} "
                         f"{html.escape(best.name)} · {html.escape(best.requirement)}")
        if len(lines) <= 2:
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text="\n".join(lines),
                                           parse_mode="HTML")
        except Exception:
            log.exception("could not announce achievements in %s", chat_id)


async def digest_job(context) -> None:
    """A short daily note to the admin channel. Doubles as a liveness probe —
    the day it doesn't arrive, something is wrong."""
    if not config.BACKUP_CHANNEL_ID:
        return
    try:
        chats = db.get().execute("SELECT chat_id, title FROM chats").fetchall()
        lines = ["📊 <b>Ranking bot — daily digest</b>", ""]
        for row in chats:
            s = store.chat_stats(row["chat_id"])
            title = row["title"] or row["chat_id"]
            lines.append(f"<b>{title}</b> — season {s['season']}, "
                         f"{s['members']} ranked, {s['entries_week']} entries this week")
        if len(lines) == 2:
            lines.append("No chats registered yet.")
        await context.bot.send_message(
            chat_id=config.BACKUP_CHANNEL_ID, text="\n".join(lines), parse_mode="HTML")
    except Exception:
        log.exception("digest failed")
