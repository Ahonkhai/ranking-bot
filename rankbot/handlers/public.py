"""Commands any member can run."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .. import achievements, avatars, caches, cards, config, store
from ..identity import (esc, fmt, display_name, rank_emoji, resolve_target,
                        find_amount)
from ..render import make_rank_card, make_top3_image
from . import boards
from .common import (announce_achievements, cooled_down, ensure_group,
                     fingerprint, reply, render, touch_actor, usage)

log = logging.getLogger("rankbot.public")

HELP = """👋 <b>Ranking Bot</b>

<b>Everyone</b>
/leaderboard — the ranked board (paged, with week / month / all-time views)
/myrank — your rank card
/rank @user — someone else's card
/top3 — quick text shoutout
/history — your last entries, and who awarded them
/stats — season summary
{transfers}
<b>Admins</b>
/addcash 500 @user — add to a member
/removecash 500 @user — deduct (floors at 0)
/setcash 5000 @user — set an exact amount
/resetmember @user — zero someone out
/undo — reverse the last entry in this chat
/newseason — close this season and start the next, keeping history
/resetboard — season reset, or a permanent wipe

Amounts accept <code>5k</code>, <code>2.5k</code> and <code>1m</code>. Every command also
works as a reply to the member's message, which is the most reliable way to
name someone — handles change, replies don't.
"""


def help_text() -> str:
    transfers = ("/give 500 @user — send some of your own points\n"
                 if config.ALLOW_TRANSFERS else "")
    return HELP.format(transfers=transfers)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    touch_actor(update)
    await reply(update, help_text())


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group(update):
        return
    touch_actor(update)

    scope = "season"
    page = 1
    for arg in context.args or []:
        low = arg.lower()
        if low in store.SCOPES:
            scope = low
        elif low in ("all", "alltime", "all-time"):
            scope = "alltime"
        elif low.isdigit():
            page = int(low)

    wait = cooled_down(update, "leaderboard")
    if wait:
        await reply(update, f"Easy — try again in {wait:.0f}s.")
        return

    await boards.send_board(update, context, scope, page)


async def cb_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    if data == "lb:noop":
        await query.answer()
        return
    try:
        _, scope, page = data.split(":")
        page = int(page)
    except ValueError:
        await query.answer()
        return
    if scope not in store.SCOPES:
        await query.answer()
        return
    await query.answer()
    await boards.edit_board(update, context, scope, page)


NOT_FOUND = "❌ I couldn't find that member in the ranking data."


async def _send_card(update, context, user_id: int, name: str, header: str):
    """Build and send one rank card. The image is the response — the caption
    stays to a single line."""
    chat = update.effective_chat
    chat_id = chat.id

    admin_set = await caches.admin_ids(chat)
    card = cards.build(chat_id, user_id, name, header=header,
                       is_admin=user_id in admin_set)
    if card is None:
        await reply(update, NOT_FOUND)
        return

    avatar = await avatars.fetch_avatar_bytes(context.bot, user_id)
    try:
        buf = await render(make_rank_card, card, avatar)
    except Exception:
        # Never leak a traceback into the group.
        log.exception("rank card render failed for %s in %s", user_id, chat_id)
        await reply(update, "❌ I couldn't draw that card just now. Try again in a moment.")
        return

    await update.effective_message.reply_photo(
        photo=buf,
        caption=(f"<b>{esc(card.name)}</b> — {rank_emoji(card.rank)} "
                 f"Rank {card.rank} of {card.total}"),
        parse_mode="HTML",
    )


async def cmd_myrank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group(update):
        return
    touch_actor(update)
    wait = cooled_down(update, "myrank")
    if wait:
        await reply(update, f"Easy — try again in {wait:.0f}s.")
        return
    user = update.effective_user
    await _send_card(update, context, user.id, display_name(user), "MY RANK")


async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply to a member with /rank, or name them: /rank @username."""
    if not await ensure_group(update):
        return
    touch_actor(update)
    target = resolve_target(update)
    if target.error:
        await reply(update, f"❌ {target.error}")
        return
    if not target.ok:
        await reply(update, "Reply to a member's message or use "
                            "<code>/rank @username</code>")
        return
    wait = cooled_down(update, "rank")
    if wait:
        await reply(update, f"Easy — try again in {wait:.0f}s.")
        return
    await _send_card(update, context, target.user_id, target.name, "MEMBER RANK")


async def cmd_top3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A podium image: second left, first raised in the centre, third right."""
    if not await ensure_group(update):
        return
    touch_actor(update)
    chat = update.effective_chat
    board = store.standings(chat.id)[:3]
    if not board:
        await reply(update, "No one is on the board yet.")
        return

    wait = cooled_down(update, "top3")
    if wait:
        await reply(update, f"Easy — try again in {wait:.0f}s.")
        return

    rows = [{"rank": r["rank"], "user_id": r["user_id"], "name": r["name"],
             "balance": r["balance"]} for r in board]

    # Same file_id reuse as the board: an unchanged podium costs one API call.
    key = (chat.id, fingerprint("top3", rows, store.current_season(chat.id),
                                store.now_iso()[:10]))
    photo = caches.BOARD_FILE_IDS.get(key)
    cached = photo is not None
    if not cached:
        pics = await avatars.fetch_many(context.bot, [r["user_id"] for r in rows])
        photo = await render(make_top3_image, rows, pics)

    # The drawn "VIEW ALL" pill is backed by a real button rather than being
    # decoration — it swaps this message for the full leaderboard.
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIEW ALL", callback_data="lb:season:1")]])

    msg = await update.effective_message.reply_photo(
        photo=photo, caption="🏆 <b>Top 3</b>", parse_mode="HTML",
        reply_markup=keyboard)
    if not cached and msg and msg.photo:
        caches.BOARD_FILE_IDS.set(key, msg.photo[-1].file_id)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Who awarded what, and when. The thing that settles arguments."""
    if not await ensure_group(update):
        return
    touch_actor(update)
    chat_id = update.effective_chat.id

    target = resolve_target(update)
    if target.error:
        await reply(update, f"❌ {target.error}")
        return
    if target.ok:
        user_id, name = target.user_id, target.name
    else:
        user = update.effective_user
        user_id, name = user.id, display_name(user)

    entries = store.history(chat_id, user_id, limit=12)
    if not entries:
        await reply(update, f"No entries recorded for <b>{esc(name)}</b> yet.")
        return

    lines = [f"📜 <b>{esc(name)}</b> — last {len(entries)} entries", ""]
    for e in entries:
        sign = "+" if e["delta"] >= 0 else "−"
        when = e["created_at"][:10]
        body = f"{sign}${fmt(abs(e['delta']))}"
        if e["voided"]:
            body = f"<s>{body}</s> (undone)"
        lines.append(f"<code>{when}</code>  {body} — by {esc(e['actor'])}")
    lines.append("")
    lines.append(f"Balance: <b>${fmt(store.balance(chat_id, user_id))}</b>")
    await reply(update, "\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group(update):
        return
    touch_actor(update)
    s = store.chat_stats(update.effective_chat.id)
    await reply(update, "\n".join([
        f"📊 <b>Season {s['season']}</b>", "",
        f"Members ranked: <b>{s['members']}</b>",
        f"Entries recorded: <b>{fmt(s['entries'])}</b>",
        f"Awarded this season: <b>${fmt(s['awarded'])}</b>",
        f"Entries in the last 7 days: <b>{fmt(s['entries_week'])}</b>",
    ]))


async def cmd_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Member-to-member transfer, recorded as one two-row transaction."""
    if not config.ALLOW_TRANSFERS:
        await reply(update, "Transfers are switched off in this bot's settings.")
        return
    if not await ensure_group(update):
        return
    touch_actor(update)

    chat_id = update.effective_chat.id
    sender = update.effective_user
    target = resolve_target(update)
    amount = find_amount(context.args or [])

    if target.error:
        await reply(update, f"❌ {target.error}")
        return
    if not target.ok or amount is None:
        await reply(update, usage("/give 500 @username", "/give 500"))
        return
    if amount <= 0:
        await reply(update, "Amount must be a positive number.")
        return

    try:
        mine, theirs = store.transfer(chat_id, sender.id, target.user_id, amount)
    except store.TransferError as e:
        await reply(update, f"❌ {esc(e)}")
        return

    caches.invalidate_chat(chat_id)
    await reply(update, (
        f"💸 <b>{esc(display_name(sender))}</b> sent <b>${fmt(amount)}</b> to "
        f"<b>{esc(target.name)}</b>\n"
        f"You: ${fmt(mine)}  ·  Them: ${fmt(theirs)}"
    ))
    # A transfer can push the recipient over a milestone.
    await announce_achievements(update, chat_id, target.user_id, target.name)


async def cmd_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Milestones a member has unlocked, and what they're climbing towards."""
    if not await ensure_group(update):
        return
    touch_actor(update)
    chat_id = update.effective_chat.id

    target = resolve_target(update)
    if target.error:
        await reply(update, f"❌ {target.error}")
        return
    if target.ok:
        user_id, name = target.user_id, target.name
    else:
        user = update.effective_user
        user_id, name = user.id, display_name(user)

    held = achievements.held_by(chat_id, user_id)
    balance = store.balance(chat_id, user_id)

    lines = [f"🏆 <b>{esc(name)}</b> — {len(held)}/{len(achievements.TIERS)} unlocked", ""]
    if held:
        lines.extend(f"{a.emoji} <b>{esc(a.name)}</b> — ${fmt(a.threshold)}" for a in held)
    else:
        lines.append("<i>Nothing unlocked yet.</i>")

    upcoming = achievements.next_tier(balance)
    if upcoming:
        lines.append("")
        lines.append(f"Next: {upcoming.emoji} <b>{esc(upcoming.name)}</b> — "
                     f"${fmt(upcoming.threshold - balance)} to go")
    await reply(update, "\n".join(lines))
