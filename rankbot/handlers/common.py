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


async def ensure_group(update: Update) -> bool:
    """Boards are per-chat, so the mutating commands only make sense in one."""
    if is_group(update):
        return True
    await reply(update, "That command only works inside a group.")
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
        store.ensure_chat(chat.id, chat.title)
        store.upsert_member(chat.id, user.id, user.username, user.full_name)
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


async def announce_achievements(update, chat_id: int, user_id: int, name: str):
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
    if top is None:
        return

    # Only the highest tier is announced. A big award earns everything beneath
    # it too and all of that is recorded, but listing seven lines buries the
    # one that means something — /achievements shows the full set.
    await reply(update, "\n".join([
        "🏆 <b>Achievement unlocked!</b>",
        "",
        f"<b>{esc(name)}</b>",
        f"{top.emoji} <b>{esc(top.name)}</b> — reached ${top.threshold:,}",
    ]))


def usage(example: str, reply_hint: str = "") -> str:
    out = f"Usage: <code>{esc(example)}</code>"
    if reply_hint:
        out += f"\nOr reply to their message and send <code>{esc(reply_hint)}</code>"
    return out
