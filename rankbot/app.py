"""Application wiring: handlers, the command menu, scheduled jobs, startup."""

import datetime as dt
import logging
import socket

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, Update
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler,
                          ChatMemberHandler, CommandHandler, MessageHandler, filters)

from . import config, db, jobs, migrate
from .handlers import admin, common, passive, public

log = logging.getLogger("rankbot.app")

_INSTANCE_SOCK: socket.socket | None = None

PUBLIC_COMMANDS = [
    BotCommand("leaderboard", "The ranked board"),
    BotCommand("myrank", "Your rank card"),
    BotCommand("rank", "Someone else's rank card"),
    BotCommand("top3", "Quick top three"),
    BotCommand("history", "Recent entries and who made them"),
    BotCommand("stats", "Season summary"),
    BotCommand("achievements", "Milestones you have unlocked"),
    BotCommand("help", "What this bot does"),
]

TRANSFER_COMMAND = BotCommand("give", "Send some of your own points")

ADMIN_COMMANDS = [
    BotCommand("addcash", "Add to a member"),
    BotCommand("removecash", "Deduct from a member"),
    BotCommand("setcash", "Set an exact amount"),
    BotCommand("resetmember", "Zero a member out"),
    BotCommand("undo", "Reverse the last entry"),
    BotCommand("newseason", "Close this season, start the next"),
    BotCommand("resetboard", "Season reset or permanent wipe"),
]


def acquire_single_instance_lock(port: int | None = None) -> bool:
    """Bind a loopback port as a lock.

    Still worth keeping after the move to SQLite: two pollers on one token is a
    Telegram-side problem (they fight over getUpdates), not a storage one.
    """
    global _INSTANCE_SOCK
    if config.ALLOW_MULTIPLE_INSTANCES:
        return True
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port or config.INSTANCE_PORT))
        sock.listen(1)
    except OSError:
        sock.close()
        return False
    _INSTANCE_SOCK = sock
    return True


async def _post_init(app: Application) -> None:
    """Publish the command menus so Telegram's UI can offer them.

    Admin commands are scoped to group chats only, so members aren't shown
    commands they can't run.
    """
    public_set = list(PUBLIC_COMMANDS)
    if config.ALLOW_TRANSFERS:
        public_set.insert(4, TRANSFER_COMMAND)
    try:
        await app.bot.set_my_commands(public_set, scope=BotCommandScopeAllPrivateChats())
        await app.bot.set_my_commands(public_set + ADMIN_COMMANDS,
                                      scope=BotCommandScopeAllGroupChats())
        log.info("command menu published")
    except Exception:
        log.exception("could not publish the command menu")

    # Privacy mode silently starves the member index: with it on, Telegram
    # only delivers commands, replies to the bot and mentions, so ordinary
    # chatter never reaches observe_message and @handle lookups keep failing
    # for people who have obviously been talking.
    try:
        me = await app.bot.get_me()
        if not me.can_read_all_group_messages:
            log.warning(
                "Privacy mode is ON for @%s — Telegram will only deliver "
                "commands, replies and mentions, so members cannot be indexed "
                "from ordinary messages. Fix it either way: promote the bot to "
                "group admin (admins receive everything), or @BotFather "
                "/setprivacy -> Disable, then remove and re-add the bot to the "
                "group — the setting only applies on re-join.",
                me.username)
        else:
            log.info("privacy mode is off; member indexing is active")
    except Exception:
        log.exception("could not check privacy mode")

    notice = migrate.pending_notice()
    if notice:
        log.warning(notice)


def register(app: Application) -> None:
    # Public
    app.add_handler(CommandHandler(["start", "help"], public.cmd_start))
    app.add_handler(CommandHandler("leaderboard", public.cmd_leaderboard))
    app.add_handler(CommandHandler(["lb", "board"], public.cmd_leaderboard))
    app.add_handler(CommandHandler("myrank", public.cmd_myrank))
    app.add_handler(CommandHandler("rank", public.cmd_rank))
    app.add_handler(CommandHandler("top3", public.cmd_top3))
    app.add_handler(CommandHandler("history", public.cmd_history))
    app.add_handler(CommandHandler("stats", public.cmd_stats))
    app.add_handler(CommandHandler("achievements", public.cmd_achievements))
    if config.ALLOW_TRANSFERS:
        app.add_handler(CommandHandler("give", public.cmd_give))

    # Admin
    app.add_handler(CommandHandler("addcash", admin.cmd_addcash))
    app.add_handler(CommandHandler("removecash", admin.cmd_removecash))
    app.add_handler(CommandHandler("setcash", admin.cmd_setcash))
    app.add_handler(CommandHandler("resetmember", admin.cmd_resetmember))
    app.add_handler(CommandHandler("undo", admin.cmd_undo))
    app.add_handler(CommandHandler("newseason", admin.cmd_newseason))
    app.add_handler(CommandHandler("resetboard", admin.cmd_resetboard))
    app.add_handler(CommandHandler("adoptlegacy", admin.cmd_adoptlegacy))
    app.add_handler(CommandHandler("chatid", admin.cmd_chatid))

    # Callbacks
    app.add_handler(CallbackQueryHandler(public.cb_leaderboard, pattern=r"^lb:"))
    app.add_handler(CallbackQueryHandler(admin.cb_resetboard, pattern=r"^rb:"))
    app.add_handler(CallbackQueryHandler(public.cb_achievements, pattern=r"^ach:"))

    # Membership
    app.add_handler(ChatMemberHandler(passive.on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(passive.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Passive observers run in a later group so they never consume an update
    # that a command handler above should have seen.
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS,
                                   passive.observe_new_members), group=1)
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL,
        passive.observe_message), group=1)

    app.add_error_handler(common.on_error)


def schedule(app: Application) -> None:
    queue = app.job_queue
    if queue is None:
        log.warning("JobQueue unavailable — install python-telegram-bot[job-queue] "
                    "for scheduled backups, digests and decay")
        return
    hours = max(1, config.BACKUP_INTERVAL_HOURS)
    queue.run_repeating(jobs.backup_job, interval=hours * 3600, first=120,
                        name="backup")
    queue.run_daily(jobs.digest_job, time=dt.time(hour=9, minute=0), name="digest")
    # Champion is earned by still being #1 after N days; no write would
    # ever trigger that, so it needs a clock.
    queue.run_daily(jobs.achievements_job, time=dt.time(hour=12, minute=0),
                    name="achievements")
    if config.DECAY_PERCENT > 0:
        queue.run_daily(jobs.decay_job, time=dt.time(hour=4, minute=0), name="decay")
        log.info("decay enabled: %.2f%% after %d idle days",
                 config.DECAY_PERCENT, config.DECAY_IDLE_DAYS)


def build() -> Application:
    builder = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .post_init(_post_init)
    )

    # Lets Telegram's own flood limits queue our sends instead of dropping them.
    try:
        from telegram.ext import AIORateLimiter
        builder = builder.rate_limiter(AIORateLimiter())
    except (ImportError, RuntimeError):
        log.warning("rate limiter unavailable — install "
                    "python-telegram-bot[rate-limiter] to enable it")

    app = builder.build()
    register(app)
    schedule(app)
    return app


def run() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN environment variable is not set")
    if not acquire_single_instance_lock():
        raise SystemExit(
            "Another instance of this bot is already running on this machine.\n"
            "Close it first — two pollers fight over getUpdates.")

    db.connect()
    app = build()
    log.info("bot starting")
    app.run_polling(
        drop_pending_updates=config.DROP_PENDING_UPDATES,
        allowed_updates=Update.ALL_TYPES,   # needed for chat_member updates
    )
