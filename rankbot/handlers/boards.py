"""Building and sending a page of the leaderboard.

Shared by the /leaderboard command and the pagination buttons, and the one
place that decides whether a render is needed at all: an unchanged board is
re-sent by file_id, which costs no render, no PNG encode and no upload.
"""

import logging
import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from .. import avatars, caches, config, store
from ..identity import esc, fmt
from ..render import make_leaderboard_image
from .common import fingerprint, render

log = logging.getLogger("rankbot.boards")

# Movement arrows only make sense for cumulative scopes; a 7-day window
# compared against "24 hours ago" would be comparing two different windows.
MOVEMENT_SCOPES = ("season", "alltime")


def _pages(total: int) -> int:
    return max(1, math.ceil(total / config.PAGE_SIZE))


def keyboard(scope: str, page: int, pages: int) -> InlineKeyboardMarkup | None:
    if pages <= 1:
        return None
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("◀ Prev", callback_data=f"lb:{scope}:{page - 1}"))
    row.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="lb:noop"))
    if page < pages:
        row.append(InlineKeyboardButton("Next ▶", callback_data=f"lb:{scope}:{page + 1}"))

    scopes = [("season", "Season"), ("week", "Week"), ("month", "Month"), ("alltime", "All time")]
    switch = [
        InlineKeyboardButton(("• " if s == scope else "") + label, callback_data=f"lb:{s}:1")
        for s, label in scopes if s != scope
    ]
    return InlineKeyboardMarkup([row, switch])


async def build_page(bot, chat, scope: str, page: int, viewer_id: int | None):
    """Assemble everything one board page needs.

    Returns (fingerprint_key, page_rows, render_kwargs, caption, pages).
    """
    # Data comes from the shared board; the cache key stays per chat because
    # the admin crowns drawn on it differ between the two groups.
    board_id = config.board_for(chat.id)
    store.ensure_chat(board_id, chat.title)
    board = store.standings(board_id, scope)
    total = len(board)
    pages = _pages(total)
    page = max(1, min(page, pages))

    start = (page - 1) * config.PAGE_SIZE
    # The rank travels with the row from standings(), which applies competition
    # ranking, so tied members show the same number here and on their card.
    rows = [
        {"rank": r["rank"], "user_id": r["user_id"], "name": r["name"],
         "balance": r["balance"]}
        for r in board[start:start + config.PAGE_SIZE]
    ]

    admin_set = await caches.admin_ids(chat)

    movement = {}
    if scope in MOVEMENT_SCOPES and rows:
        previous = store.ranks_as_of(
            board_id, scope, store.ago_iso(hours=config.RANK_CHANGE_WINDOW_HOURS))
        if previous:
            for r in rows:
                was = previous.get(r["user_id"])
                if was:
                    delta = was - r["rank"]      # positive means climbed
                    if delta:
                        movement[r["user_id"]] = delta

    # "You are here", only when the viewer isn't already on this page.
    you = None
    if viewer_id is not None and not any(r["user_id"] == viewer_id for r in rows):
        for i, r in enumerate(board):
            if r["user_id"] == viewer_id:
                note = ""
                if i > 0:
                    ahead = board[i - 1]
                    gap = ahead["balance"] - r["balance"]
                    if gap > 0:
                        note = f"{fmt(gap)} BEHIND {ahead['name'][:16]}"
                you = {"rank": r["rank"], "name": r["name"],
                       "balance": r["balance"], "note": note}
                break

    key = (
        chat.id,
        fingerprint(scope, page, total, rows, sorted(admin_set & {r["user_id"] for r in rows}),
                    movement, you, store.current_season(board_id),
                    store.now_iso()[:10]),
    )

    kwargs = {
        "admin_ids": admin_set,
        "page": page,
        "pages": pages,
        "total": total,
        "scope_label": store.SCOPE_LABELS.get(scope, scope.upper()),
        "season": store.current_season(board_id) if scope == "season" else None,
        "movement": movement,
        "you": you,
    }
    caption = (f"🏆 <b>Leaderboard</b> — {total} member{'s' if total != 1 else ''}"
               f" · {esc(store.SCOPE_LABELS.get(scope, scope))}")
    return key, rows, kwargs, caption, pages, page


async def photo_for(bot, chat, key, rows, kwargs):
    """A file_id when this exact board has been sent before, else fresh bytes.

    Returns (photo, from_cache, worth_caching). A board drawn while somebody's
    avatar download was failing is *not* worth caching: the fingerprint doesn't
    know an avatar is missing, so caching it would freeze the initials into
    this board for hours after the problem cleared.
    """
    cached = caches.BOARD_FILE_IDS.get(key)
    if cached:
        return cached, True, False
    uids = [r["user_id"] for r in rows]
    kwargs = dict(kwargs, avatars=await avatars.fetch_many(bot, uids))
    buf = await render(make_leaderboard_image, rows, **kwargs)
    return buf, False, not avatars.pending_retry(uids)


def remember(key, message) -> None:
    if message and message.photo:
        caches.BOARD_FILE_IDS.set(key, message.photo[-1].file_id)


async def send_board(update, context, scope: str = "season", page: int = 1):
    chat = update.effective_chat
    viewer = update.effective_user.id if update.effective_user else None
    key, rows, kwargs, caption, pages, page = await build_page(
        context.bot, chat, scope, page, viewer)

    if not rows:
        await update.effective_message.reply_text(
            "The leaderboard is empty. Admins can add someone with "
            "<code>/addcash 500</code> as a reply to their message.",
            parse_mode="HTML")
        return

    photo, _from_cache, worth_caching = await photo_for(
        context.bot, chat, key, rows, kwargs)
    msg = await update.effective_message.reply_photo(
        photo=photo, caption=caption, parse_mode="HTML",
        reply_markup=keyboard(scope, page, pages))
    if worth_caching:
        remember(key, msg)


async def edit_board(update, context, scope: str, page: int):
    query = update.callback_query
    chat = update.effective_chat
    viewer = update.effective_user.id if update.effective_user else None
    key, rows, kwargs, caption, pages, page = await build_page(
        context.bot, chat, scope, page, viewer)

    if not rows:
        await query.answer("Nothing on this board yet.", show_alert=True)
        return

    photo, _from_cache, worth_caching = await photo_for(
        context.bot, chat, key, rows, kwargs)
    msg = await query.edit_message_media(
        media=InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
        reply_markup=keyboard(scope, page, pages))
    if worth_caching and hasattr(msg, "photo"):
        remember(key, msg)
