"""Who is being targeted, and how names reach the screen safely.

Two rules drive this module:

1. Identity comes from a Telegram user id, never from a display string.
   Handles are mutable and recyclable, so matching on a stored "@name" can
   credit whoever holds that handle today rather than the person meant.
2. Every name that reaches a message is HTML-escaped. Names legitimately
   contain <, & and the Markdown metacharacters that used to make Telegram
   reject the whole send.
"""

import html
import re
from dataclasses import dataclass

from telegram import MessageEntity, Update

from . import store

MAX_AMOUNT = 1_000_000_000_000  # a trillion; beyond this it's a typo


def esc(text) -> str:
    """Escape for ParseMode.HTML."""
    return html.escape(str(text if text is not None else ""), quote=False)


def fmt(n: int) -> str:
    return f"{n:,}"


def display_name(tg_user) -> str:
    """On-screen name for a live Telegram user object."""
    return store.display_from_parts(
        tg_user.username, tg_user.full_name, tg_user.id
    )


def rank_emoji(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")


# ── amounts ──────────────────────────────────────────────────────────────

# A comma is always a thousands separator here, never a decimal point: these
# are whole point amounts, so reading "5,000" as five is the only wrong answer
# available.
_AMOUNT_RE = re.compile(r"^([+-]?)(\d+(?:\.\d+)?)\s*([kmb]?)$", re.IGNORECASE)
_SUFFIX = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_amount(token: str) -> int | None:
    """'5000', '5,000', '5k', '2.5k', '1m' -> int. None if not a number."""
    t = token.strip().replace(",", "").replace("_", "")
    if not t:
        return None
    m = _AMOUNT_RE.match(t)
    if not m:
        return None
    sign, digits, suffix = m.groups()
    try:
        value = float(digits) * _SUFFIX[suffix.lower()]
    except (ValueError, KeyError):
        return None
    value = int(round(value))
    if sign == "-":
        value = -value
    if abs(value) > MAX_AMOUNT:
        return None
    return value


def find_amount(args: list[str]) -> int | None:
    """First numeric token anywhere in the args.

    Positional, not indexed: an admin replying to someone and typing
    `/setcash @dave 500` names a person they can already see, and that used to
    be rejected as bad input because only args[0] was examined.
    """
    for a in args:
        if a.startswith("@"):
            continue
        value = parse_amount(a)
        if value is not None:
            return value
    return None


# ── targets ──────────────────────────────────────────────────────────────

@dataclass
class Target:
    user_id: int | None = None
    name: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.user_id is not None and self.error is None


def _from_tg_user(chat_id: int, tg_user) -> Target:
    if tg_user.is_bot:
        return Target(error="That's a bot — bots don't hold a rank.")
    name = display_name(tg_user)
    # Seeing a live user object is the best name data we ever get; keep it.
    store.upsert_member(chat_id, tg_user.id, tg_user.username, tg_user.full_name)
    return Target(user_id=tg_user.id, name=name)


def resolve_target(update: Update) -> Target:
    """Identify the member a command is aimed at.

    Order of trust: the replied-to author, then a text_mention entity (which
    carries a real user object), then a plain @handle looked up in this chat's
    member index.
    """
    message = update.effective_message
    chat_id = update.effective_chat.id

    if message.reply_to_message and message.reply_to_message.from_user:
        return _from_tg_user(chat_id, message.reply_to_message.from_user)

    entities = message.parse_entities(
        [MessageEntity.TEXT_MENTION, MessageEntity.MENTION]
    )

    # A text_mention embeds the user object, so it needs no lookup at all.
    for entity, _text in entities.items():
        if entity.type == MessageEntity.TEXT_MENTION and entity.user:
            return _from_tg_user(chat_id, entity.user)

    for entity, text in entities.items():
        if entity.type != MessageEntity.MENTION:
            continue
        handle = text.lstrip("@")
        matches = store.find_by_username(chat_id, handle)
        if len(matches) == 1:
            row = matches[0]
            return Target(user_id=row["user_id"], name=store.row_name(row))
        if len(matches) > 1:
            return Target(error=(
                f"More than one member here is recorded as @{esc(handle)}. "
                "Reply to their message instead so there's no doubt."
            ))
        return Target(error=(
            f"@{esc(handle)} isn't indexed in this group yet. Handles change, so "
            "the safe way is to reply to one of their messages and run the "
            "command again — or have them post once so I can index them."
        ))

    return Target()  # nothing named at all; caller shows usage


def resolve_command(update, args) -> tuple[Target, int | None]:
    """Convenience for the admin commands: target plus amount in one call."""
    return resolve_target(update), find_amount(args)
