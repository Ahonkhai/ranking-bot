"""Passive observers — the bot learning who's in the room without being asked.

The old bot only learned a name when an admin targeted that person, so records
went stale the moment someone changed their handle and stayed stale. Watching
ordinary traffic fixes @handle resolution, gives every member a last_seen, and
registers the chat the first time anyone speaks.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from .. import caches, store

log = logging.getLogger("rankbot.passive")

GROUP_TYPES = ("group", "supergroup")


async def observe_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Index the sender of any group message. Never replies, never consumes."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None or user.is_bot:
        return
    if chat.type not in GROUP_TYPES:
        return
    try:
        store.ensure_chat(chat.id, chat.title)
        store.upsert_member(chat.id, user.id, user.username, user.full_name)
    except Exception:
        # An indexing failure must never take out message handling.
        log.exception("passive index failed for %s in %s", user.id, chat.id)


async def observe_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Index people the moment they join, before they've said anything."""
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or chat.type not in GROUP_TYPES:
        return
    for member in message.new_chat_members or []:
        if member.is_bot:
            continue
        try:
            store.ensure_chat(chat.id, chat.title)
            store.upsert_member(chat.id, member.id, member.username, member.full_name)
        except Exception:
            log.exception("failed to index joiner %s", member.id)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promotions and demotions invalidate the cached admin set immediately,
    so the five-minute TTL can never show a stale one in practice."""
    upd = update.chat_member
    if upd is None:
        return
    old_status = upd.old_chat_member.status
    new_status = upd.new_chat_member.status
    if old_status != new_status and {"administrator", "creator"} & {old_status, new_status}:
        caches.invalidate_admins(update.effective_chat.id)
        log.info("admin set changed in %s (%s -> %s)",
                 update.effective_chat.id, old_status, new_status)

    user = upd.new_chat_member.user
    if user and not user.is_bot and update.effective_chat.type in GROUP_TYPES:
        try:
            store.upsert_member(update.effective_chat.id, user.id, user.username, user.full_name)
        except Exception:
            log.exception("failed to index chat_member update")


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register the chat when the bot is added to it."""
    upd = update.my_chat_member
    chat = update.effective_chat
    if upd is None or chat is None or chat.type not in GROUP_TYPES:
        return
    if upd.new_chat_member.status in ("member", "administrator"):
        store.ensure_chat(chat.id, chat.title)
        caches.invalidate_admins(chat.id)
        log.info("added to chat %s (%s)", chat.id, chat.title)
