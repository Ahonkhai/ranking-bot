"""Admin-only commands."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import caches, config, migrate, store
from ..identity import esc, find_amount, fmt, rank_emoji, resolve_target
from .common import (announce_achievements, board_of, ensure_group, reply,
                     require_admin, require_backend, touch_actor, usage)

log = logging.getLogger("rankbot.admin")


async def _prepare(update, args, example: str, reply_hint: str, need_amount: bool = True):
    """Shared front half of every admin mutation.

    Returns (chat_id, target, amount) or None when it has already replied with
    the reason it can't proceed.
    """
    if not await ensure_group(update):
        return None
    # Location first, then the existing authorization. Being an admin of the
    # public group must never confer the ability to edit scores.
    if not await require_backend(update):
        return None
    if not await require_admin(update):
        return None
    touch_actor(update)

    target = resolve_target(update)
    amount = find_amount(args or []) if need_amount else None

    if target.error:
        await reply(update, f"❌ {target.error}")
        return None
    if not target.ok or (need_amount and amount is None):
        await reply(update, usage(example, reply_hint))
        return None
    return board_of(update), target, amount


async def _confirm(update, context, chat_id: int, target, headline: str) -> None:
    """Report the result with the member's new position, then any milestone."""
    caches.invalidate_chat(chat_id)
    rank, total = store.rank_of(chat_id, target.user_id)
    tail = f"  —  {rank_emoji(rank)} rank {rank} of {total}" if rank else ""
    await reply(update, headline + tail)
    await announce_achievements(update, chat_id, target.user_id, target.name,
                                context=context)


async def cmd_addcash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prep = await _prepare(update, context.args, "/addcash 500 @username", "/addcash 500")
    if not prep:
        return
    chat_id, target, amount = prep
    if amount <= 0:
        await reply(update, "Amount must be a positive number.")
        return
    new_balance = store.award(chat_id, target.user_id, amount,
                              update.effective_user.id, "added")
    await _confirm(update, context, chat_id, target,
                   f"✅ Added <b>${fmt(amount)}</b> to <b>{esc(target.name)}</b>\n"
                   f"New total: <b>${fmt(new_balance)}</b>")


async def cmd_removecash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prep = await _prepare(update, context.args, "/removecash 500 @username", "/removecash 500")
    if not prep:
        return
    chat_id, target, amount = prep
    if amount <= 0:
        await reply(update, "Amount must be a positive number.")
        return
    removed, new_balance = store.deduct(chat_id, target.user_id, amount,
                                        update.effective_user.id)
    if removed == 0:
        await reply(update, f"<b>{esc(target.name)}</b> is already at $0.")
        return
    note = "" if removed == amount else f" (capped — they only had ${fmt(removed)})"
    await _confirm(update, context, chat_id, target,
                   f"✅ Removed <b>${fmt(removed)}</b> from <b>{esc(target.name)}</b>{note}\n"
                   f"New total: <b>${fmt(new_balance)}</b>")


async def cmd_setcash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prep = await _prepare(update, context.args, "/setcash 5000 @username", "/setcash 5000")
    if not prep:
        return
    chat_id, target, amount = prep
    if amount < 0:
        await reply(update, "Amount must be zero or more.")
        return
    delta, new_balance = store.set_balance(chat_id, target.user_id, amount,
                                           update.effective_user.id)
    change = f"{'+' if delta >= 0 else '−'}${fmt(abs(delta))}"
    await _confirm(update, context, chat_id, target,
                   f"✅ <b>{esc(target.name)}</b> set to <b>${fmt(new_balance)}</b> ({change})")


async def cmd_resetmember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prep = await _prepare(update, context.args, "/resetmember @username", "/resetmember",
                          need_amount=False)
    if not prep:
        return
    chat_id, target, _ = prep
    _delta, _new = store.set_balance(chat_id, target.user_id, 0, update.effective_user.id)
    caches.invalidate_chat(chat_id)
    await reply(update, f"✅ <b>{esc(target.name)}</b> has been reset to $0.")


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reverse the most recent entry. Nothing is deleted — the original row is
    flagged and an audit row records who reversed it."""
    if not await ensure_group(update):
        return
    if not await require_backend(update):
        return
    if not await require_admin(update):
        return
    touch_actor(update)
    chat_id = board_of(update)

    result = store.undo_last(chat_id, update.effective_user.id)
    if result is None:
        await reply(update, "There's nothing left to undo in this chat.")
        return

    caches.invalidate_chat(chat_id)
    name = store.member_name(chat_id, result["user_id"])
    actor = store.member_name(chat_id, result["actor_id"])
    sign = "+" if result["delta"] >= 0 else "−"
    extra = " (both sides of the transfer)" if result["rows"] > 1 else ""
    await reply(update, (
        f"↩️ Reversed <b>{sign}${fmt(abs(result['delta']))}</b> on "
        f"<b>{esc(name)}</b>{extra}\n"
        f"Originally by {esc(actor)}. They're now at <b>${fmt(result['new_balance'])}</b>."
    ))


async def cmd_newseason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group(update):
        return
    if not await require_backend(update):
        return
    if not await require_admin(update):
        return
    touch_actor(update)
    chat_id = board_of(update)

    final = store.standings(chat_id)[:10]
    old, new = store.close_season(chat_id, " ".join(context.args) if context.args else None)
    caches.invalidate_chat(chat_id)

    lines = [f"🏁 <b>Season {old} closed.</b> Season {new} starts now.", ""]
    if final:
        lines.append(f"<b>Final standings — season {old}</b>")
        for i, row in enumerate(final):
            lines.append(f"{rank_emoji(i + 1)} {esc(row['name'])} — ${fmt(row['balance'])}")
        lines.append("")
        lines.append("Every entry is kept — <code>/leaderboard alltime</code> still shows it all.")
    else:
        lines.append("Nothing was recorded in it.")
    await reply(update, "\n".join(lines))


async def cmd_resetboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Offers the reversible option first; the destructive one is still there."""
    if not await ensure_group(update):
        return
    if not await require_backend(update):
        return
    if not await require_admin(update):
        return
    touch_actor(update)
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏁 Start a new season (keeps history)",
                              callback_data=f"rb:season:{uid}")],
        [InlineKeyboardButton("🗑 Erase every entry permanently",
                              callback_data=f"rb:wipe:{uid}")],
        [InlineKeyboardButton("Cancel", callback_data=f"rb:cancel:{uid}")],
    ])
    await reply(update, (
        "How do you want to reset?\n\n"
        "<b>New season</b> zeroes the board but keeps every entry, so all-time "
        "views and history still work. This is almost always what you want.\n\n"
        "<b>Erase</b> deletes every ledger entry for this chat. It cannot be undone."
    ), reply_markup=keyboard)


async def cb_resetboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, action, owner = (query.data or "").split(":")
        owner = int(owner)
    except ValueError:
        await query.answer()
        return

    if not config.is_backend(update.effective_chat.id):
        await query.answer("Scores are managed in the admin group.", show_alert=True)
        return
    if update.effective_user.id != owner:
        await query.answer("That prompt belongs to another admin.", show_alert=True)
        return
    if update.effective_user.id not in await caches.admin_ids(update.effective_chat):
        await query.answer("Admins only.", show_alert=True)
        return

    await query.answer()
    chat_id = board_of(update)

    if action == "season":
        old, new = store.close_season(chat_id)
        caches.invalidate_chat(chat_id)
        await query.edit_message_text(
            f"🏁 Season {old} closed — season {new} starts now. History is intact.",
            parse_mode="HTML")
    elif action == "wipe":
        removed = store.hard_wipe(chat_id)
        caches.invalidate_chat(chat_id)
        await query.edit_message_text(
            f"🗑 Erased {removed:,} entries. The board is empty.", parse_mode="HTML")
    else:
        await query.edit_message_text("Reset cancelled.")


async def cmd_adoptlegacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-shot import of the old data.json into this chat."""
    if not await ensure_group(update):
        return
    if not await require_backend(update):
        return
    if not await require_admin(update):
        return
    touch_actor(update)
    chat_id = board_of(update)

    preview = migrate.read_legacy()
    if not preview:
        await reply(update, "No legacy <code>data.json</code> found next to the bot.")
        return

    result = migrate.import_into(chat_id)
    if result["imported"] == 0:
        await reply(update, f"Nothing imported — {esc(result['reason'])}.")
        return

    caches.invalidate_chat(chat_id)
    await reply(update, (
        f"📥 Imported <b>{result['imported']}</b> members from the old "
        f"<code>data.json</code> into this chat as opening entries.\n"
        f"Check <code>/leaderboard</code>, then keep the old file somewhere safe."
    ))

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Report this chat's id, for filling in BACKEND_/FRONTEND_GROUP_ID.

    Deliberately not gated on the backend group: you need it *before* the
    groups are configured, which is exactly when that guard would refuse.
    """
    chat = update.effective_chat
    board = config.board_for(chat.id)
    lines = [f"<b>{esc(chat.title or 'this chat')}</b>",
             f"<code>{chat.id}</code>"]
    if config.TWO_GROUP_MODE or config.SECOND_GROUP_MODE:
        if config.TWO_GROUP_MODE and chat.id == config.BACKEND_GROUP_ID:
            role = "admin group"
        elif config.TWO_GROUP_MODE and chat.id == config.FRONTEND_GROUP_ID:
            role = "public group"
        elif config.SECOND_GROUP_MODE and chat.id == config.SECOND_BACKEND_GROUP_ID:
            role = "second admin group"
        elif config.SECOND_GROUP_MODE and chat.id == config.SECOND_FRONTEND_GROUP_ID:
            role = "second public group"
        elif chat.id in config.EXTRA_GROUP_IDS:
            role = "standalone group (own board, not shared)"
        else:
            role = "not configured for this bot"
        lines.append("")
        lines.append(f"Role: {role}")
        lines.append(f"Board: <code>{board}</code>")
    else:
        lines.append("")
        lines.append("Two-group mode is off — this chat has its own board.")
    await reply(update, chr(10).join(lines))
