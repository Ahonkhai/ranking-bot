"""Guards, cooldowns, render dispatch and the error handler."""

import asyncio
import functools
import hashlib
import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError

from .. import achievements, caches, config, store
from ..identity import esc

log = logging.getLogger("rankbot.handlers")

GROUP_TYPES = ("group", "supergroup")

# Bounded so a busy chat can't grow it without limit.
_COOLDOWNS = caches.TTLCache(maxsize=4096, ttl=600)

_RENDER_SEM = asyncio.Semaphore(config.RENDER_CONCURRENCY)


async def render(fn, *args, **kwargs):
    """Run a PIL render off the event loop, bounded by RENDER_CONCURRENCY."""
    async with _RENDER_SEM:
        return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))


async def reply(update: Update, text: str, **kwargs):
    """Every outgoing message goes through here, always in HTML mode.

    Legacy Markdown made Telegram reject the entire send for any member whose
    name contained * _ [ — the message simply never arrived.
    """
    kwargs.setdefault("parse_mode", ParseMode.HTML)
    message = update.effective_message
    if message is None:
        return None
    return await message.reply_text(text, **kwargs)


def is_group(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type in GROUP_TYPES


def board_of(update: Update) -> int:
    """The board this chat reads and writes.

    In two-group mode both configured groups resolve to the same id, which is
    what makes them one shared leaderboard instead of two that look alike.
    """
    return config.board_for(update.effective_chat.id)


async def ensure_group(update: Update) -> bool:
    """Commands only make sense inside a group, and — when the bot is
    configured for a specific pair of them — only inside those."""
    if not is_group(update):
        await reply(update, "That command only works inside a group.")
        return False
    if not config.is_known_chat(update.effective_chat.id):
        await reply(update, "This bot isn't configured for this group.")
        return False
    return True


async def require_backend(update: Update) -> bool:
    """Score-changing commands are accepted in the admin group only.

    Checked *before* the existing admin authorization, not instead of it: being
    an admin of the public group must never confer the ability to edit scores.
    """
    if config.is_backend(update.effective_chat.id):
        return True
    await reply(update, "Scores are managed in the admin group, not here.")
    return False


async def is_admin(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return False
    if chat.type == "private":
        return False
    return user.id in await caches.admin_ids(chat)


async def require_admin(update: Update) -> bool:
    if await is_admin(update):
        return True
    await reply(update, "❌ Admins only.")
    return False


def cooled_down(update: Update, key: str, seconds: float | None = None) -> float:
    """Seconds remaining on this user's cooldown for `key`; 0 when clear."""
    seconds = config.COOLDOWN_SECONDS if seconds is None else seconds
    if seconds <= 0:
        return 0.0
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return 0.0
    ck = (chat.id, user.id, key)
    last = _COOLDOWNS.get(ck)
    now = time.time()
    if last is not None and now - last < seconds:
        return seconds - (now - last)
    _COOLDOWNS.set(ck, now)
    return 0.0


def fingerprint(*parts) -> str:
    """Stable short hash of everything that changes the rendered picture."""
    h = hashlib.blake2b(digest_size=12)
    for p in parts:
        h.update(repr(p).encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()


def touch_actor(update: Update) -> None:
    """Index whoever ran the command — free member data on every interaction."""
    chat, user = update.effective_chat, update.effective_user
    if chat is None or user is None or user.is_bot or chat.type not in GROUP_TYPES:
        return
    try:
        board = config.board_for(chat.id)
        store.ensure_chat(board, chat.title)
        store.upsert_member(board, user.id, user.username, user.full_name)
    except Exception:
        log.exception("failed to index actor %s in %s", user.id, chat.id)


async def on_error(update, context) -> None:
    """Log, and tell the person who ran the command.

    Silence used to be indistinguishable from the bot being offline.
    """
    err = context.error
    log.error("handler failed: %r", err, exc_info=err)

    if not isinstance(update, Update):
        return
    if isinstance(err, (Forbidden,)):
        return  # kicked or blocked; nothing useful to say

    text = "Something went wrong running that. It's been logged."
    if isinstance(err, BadRequest) and "message is not modified" in str(err).lower():
        return
    if isinstance(err, TelegramError) and "timed out" in str(err).lower():
        text = "Telegram timed out on that one. Try again in a moment."

    try:
        if update.callback_query:
            await update.callback_query.answer(text, show_alert=False)
        elif update.effective_message:
            await update.effective_message.reply_text(text)
    except Exception:
        log.debug("could not deliver the error notice", exc_info=True)


async def _say(update, context, text: str):
    """Put an announcement where the community will see it.

    Admin edits happen in the backend group, but the unlock is news for the
    public one — so it goes there when a frontend group is configured, and
    stays put otherwise.
    """
    target = config.FRONTEND_GROUP_ID
    if (config.TWO_GROUP_MODE and config.ANNOUNCE_IN_FRONTEND
            and target is not None and context is not None
            and update.effective_chat.id != target):
        try:
            await context.bot.send_message(chat_id=target, text=text, parse_mode="HTML")
            return
        except Exception:
            log.exception("could not announce in the frontend group %s", target)
    await reply(update, text)


async def announce_achievements(update, chat_id: int, user_id: int, name: str,
                                context=None):
    """Celebrate any milestone this member has just reached.

    Sent as its own message rather than appended to the confirmation, so the
    unlock reads as an event in the chat instead of a footnote.
    """
    try:
        unlocked = achievements.check(chat_id, user_id)
    except Exception:
        log.exception("achievement check failed for %s in %s", user_id, chat_id)
        return
    top = achievements.headline(unlocked)
    if top is not None:
        # Only the highest tier is announced. A big award earns everything
        # beneath it too and all of that is recorded, but listing seven lines
        # buries the one that means something — /achievements has the full set.
        await _say(update, context, "\n".join([
            "🏆 <b>ACHIEVEMENT UNLOCKED</b>",
            "",
            f"<b>{esc(top.name)}</b>  ·  {top.rarity.label}",
            f"{esc(name)} — {esc(top.description)}",
        ]))

    # A rank can improve without that member's balance moving — someone above
    # them was reset, or overtaken by a third party — so the rest of the board
    # is still swept and awarded. Silently, though: when a board grows past a
    # tier's size requirement every member in it qualifies at the same moment,
    # and announcing that is a wall of identical lines rather than news. The
    # badges show up in /achievements.
    try:
        achievements.check_board(chat_id, skip=user_id)
    except Exception:
        log.exception("board achievement sweep failed for %s", chat_id)


def usage(example: str, reply_hint: str = "") -> str:
    out = f"Usage: <code>{esc(example)}</code>"
    if reply_hint:
        out += f"\nOr reply to their message and send <code>{esc(reply_hint)}</code>"
    return out
