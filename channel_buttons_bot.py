"""Channel Buttons Bot.

A separate, small bot: forward an old channel post to it and it attaches a
fixed set of inline buttons to that post in place. Works on posts the bot
never sent itself — channel posts are attributed to the channel, so an admin
bot with "Edit messages" rights can edit any of them via
`editMessageReplyMarkup`.

Setup:
  1. Create a bot via @BotFather (a separate one from any other bot you run).
  2. Add it to the channel as admin, with "Edit messages" enabled.
  3. Set the env vars below and run:

       BUTTON_BOT_TOKEN=... ALLOWED_USER_IDS=... CHANNEL_BUTTONS="..." \\
           python channel_buttons_bot.py

  4. In a private chat with the bot, forward the old channel post you want
     to add buttons to. It edits that exact message and confirms.

Env vars:
  BUTTON_BOT_TOKEN   Bot token from @BotFather.
  ALLOWED_USER_IDS   Comma-separated Telegram user IDs allowed to trigger
                      edits. Anyone else's forwards are silently ignored.
  CHANNEL_BUTTONS    The button layout to apply. Rows are separated by
                      newlines, buttons within a row by " ; ", and each
                      button's label/URL by " -> ". Example:

                        🔗 Join our chat -> https://t.me/joinchat/xxx
                        ⭐ Rate us -> https://example.com/rate ; 📣 Share -> https://example.com/share

                      (first line is one button on its own row, second line
                      is two buttons side by side on the next row)
"""

from __future__ import annotations

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MessageOriginChannel, Update
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("channel_buttons_bot")


def parse_buttons(spec: str) -> InlineKeyboardMarkup:
    """Parse CHANNEL_BUTTONS syntax into an InlineKeyboardMarkup."""
    rows: list[list[InlineKeyboardButton]] = []
    for line in spec.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        row: list[InlineKeyboardButton] = []
        for chunk in line.split(";"):
            label, sep, url = chunk.strip().partition("->")
            label, url = label.strip(), url.strip()
            if not sep or not label or not url:
                raise ValueError(f"Malformed button spec: {chunk!r}")
            row.append(InlineKeyboardButton(label, url=url))
        rows.append(row)
    if not rows:
        raise ValueError("CHANNEL_BUTTONS is empty")
    return InlineKeyboardMarkup(rows)


def parse_allowed_ids(raw: str) -> set[int]:
    ids = {int(x) for x in raw.split(",") if x.strip()}
    if not ids:
        raise ValueError("ALLOWED_USER_IDS is empty")
    return ids


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    allowed: set[int] = context.bot_data["allowed_user_ids"]
    if user.id not in allowed:
        logger.info("Ignoring forward from unauthorized user %s", user.id)
        return

    origin = message.forward_origin
    if not isinstance(origin, MessageOriginChannel):
        await message.reply_text("Forward a post from a channel, not this.")
        return

    buttons: InlineKeyboardMarkup = context.bot_data["buttons"]
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=origin.chat.id,
            message_id=origin.message_id,
            reply_markup=buttons,
        )
    except TelegramError as exc:
        logger.warning("Failed to edit %s/%s: %s", origin.chat.id, origin.message_id, exc)
        await message.reply_text(f"Couldn't edit that post: {exc.message}")
        return

    await message.reply_text(f"Buttons added to the post in {origin.chat.title or origin.chat.id}.")


def build_app() -> Application:
    token = os.environ["BUTTON_BOT_TOKEN"]
    allowed = parse_allowed_ids(os.environ["ALLOWED_USER_IDS"])
    buttons = parse_buttons(os.environ["CHANNEL_BUTTONS"])

    app = Application.builder().token(token).build()
    app.bot_data["allowed_user_ids"] = allowed
    app.bot_data["buttons"] = buttons
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forward))
    return app


def run() -> None:
    app = build_app()
    logger.info(
        "Channel buttons bot starting, %d allowed user(s).",
        len(app.bot_data["allowed_user_ids"]),
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run()
