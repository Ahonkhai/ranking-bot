"""All environment-driven settings in one place."""

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def _under(path: str, directory: str) -> bool:
    root = os.path.abspath(directory)
    target = os.path.abspath(path)
    return target == root or target.startswith(root + os.sep)


def resolve_storage(db_path: str, legacy: str, mount: str | None,
                    exists=os.path.exists) -> tuple[str, str]:
    """Put the database on the persistent mount, wherever it was attached.

    Railway injects RAILWAY_VOLUME_MOUNT_PATH when a volume exists, and the
    mount path is chosen in the dashboard — so a DB_PATH baked into the
    Dockerfile can easily point somewhere else entirely. Anything outside the
    mount is on the container filesystem and is wiped on every redeploy, which
    silently empties the board.

    The legacy file is only redirected when there is actually one on the
    volume: it is read-only input, and someone who points DATA_FILE at a copy
    shipped inside the image means it.
    """
    if not mount:
        return db_path, legacy
    if not _under(db_path, mount):
        db_path = os.path.join(mount, "rankbot.db")
    if not _under(legacy, mount):
        candidate = os.path.join(mount, "data.json")
        if exists(candidate):
            legacy = candidate
    return db_path, legacy


# Railway sets these when a volume is attached to the service.
VOLUME_MOUNT = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
ON_RAILWAY = bool(os.getenv("RAILWAY_PROJECT_ID")
                  or os.getenv("RAILWAY_ENVIRONMENT_NAME")
                  or os.getenv("RAILWAY_SERVICE_ID"))

# Storage. DATA_FILE is only read once, by the migration.
DB_PATH, DATA_FILE = resolve_storage(
    os.getenv("DB_PATH", "data.db"),
    os.getenv("DATA_FILE", "data.json"),
    VOLUME_MOUNT,
)

# ── two-group mode ───────────────────────────────────────────────────────
# One private community split across an admin group and a public one. Both
# read and write a single set of scores; the group only decides what you are
# allowed to do, never what the data says.
#
# Leave these unset and the bot behaves exactly as before: one independent
# board per chat.

def _group_id(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


BACKEND_GROUP_ID = _group_id("BACKEND_GROUP_ID")
FRONTEND_GROUP_ID = _group_id("FRONTEND_GROUP_ID")
TWO_GROUP_MODE = BACKEND_GROUP_ID is not None and FRONTEND_GROUP_ID is not None

# Announce unlocks in the public group rather than wherever the admin typed.
ANNOUNCE_IN_FRONTEND = _bool("ANNOUNCE_IN_FRONTEND", True)


def board_for(chat_id: int) -> int:
    """The board a chat reads and writes.

    Both configured groups resolve to the backend id, which is what makes the
    two of them one shared leaderboard rather than two that look alike. Any
    other chat keeps its own board, so nothing changes for a single-group
    deployment.
    """
    if TWO_GROUP_MODE and chat_id in (BACKEND_GROUP_ID, FRONTEND_GROUP_ID):
        return BACKEND_GROUP_ID
    return chat_id


def chats_for_board(board_id: int) -> tuple[int, ...]:
    """Every chat that displays this board — both groups share cached images,
    so invalidating one has to invalidate the other."""
    if TWO_GROUP_MODE and board_id == BACKEND_GROUP_ID:
        return (BACKEND_GROUP_ID, FRONTEND_GROUP_ID)
    return (board_id,)


def is_backend(chat_id: int) -> bool:
    """Score-changing commands are only accepted here."""
    return not TWO_GROUP_MODE or chat_id == BACKEND_GROUP_ID


def is_known_chat(chat_id: int) -> bool:
    return not TWO_GROUP_MODE or chat_id in (BACKEND_GROUP_ID, FRONTEND_GROUP_ID)


CURRENCY = os.getenv("CURRENCY", "💰")
# Symbol printed before amounts on the rendered cards and boards.
CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "$")

# How many rows fit on one rendered leaderboard page.
PAGE_SIZE = _int("PAGE_SIZE", 15)

# ── XP and levels ────────────────────────────────────────────────────────
# Cumulative XP to reach level L is XP_LINEAR*(L-1) + XP_QUADRATIC*(L-1)^2.
# Defaults put roughly $33k of lifetime earnings at level 22.
XP_LINEAR    = _int("XP_LINEAR", 500)
XP_QUADRATIC = _int("XP_QUADRATIC", 50)
# 1 = the XP bar shows lifetime XP against the next level's total requirement.
# 0 = it shows progress within the current level, so it empties on level-up.
XP_BAR_CUMULATIVE = _bool("XP_BAR_CUMULATIVE", False)

# How far back "rank change" looks. Derived from the ledger, so this is a real
# historical rank rather than a snapshot that can drift out of sync.
RANK_CHANGE_WINDOW_HOURS = _int("RANK_CHANGE_WINDOW_HOURS", 24)

# Consecutive days at #1 required for the Champion achievement.
CHAMPION_DAYS = _int("CHAMPION_DAYS", 7)

# Cache lifetimes, seconds.
ADMIN_TTL  = _int("ADMIN_TTL", 300)
AVATAR_TTL = _int("AVATAR_TTL", 3600)
# Backoff after a failed avatar download, so one blip does not look like
# "this member has no photo" for the whole AVATAR_TTL.
AVATAR_RETRY_SECONDS = _int("AVATAR_RETRY_SECONDS", 90)

# Bounded cache sizes, entries.
AVATAR_RAW_MAX  = _int("AVATAR_RAW_MAX", 512)
AVATAR_DISC_MAX = _int("AVATAR_DISC_MAX", 512)
BOARD_CACHE_MAX = _int("BOARD_CACHE_MAX", 256)

# Concurrent PIL renders. Cheap now that gradients are memoized, but still
# bounded so a burst can't pin every core.
RENDER_CONCURRENCY = _int("RENDER_CONCURRENCY", 3)

# Per-user, per-command cooldown for the expensive read commands.
COOLDOWN_SECONDS = _float("COOLDOWN_SECONDS", 4.0)

# Weekly inactivity decay, percent of balance. 0 disables it entirely, which
# is the default: silently taking points from people is opt-in behaviour.
DECAY_PERCENT     = _float("DECAY_PERCENT", 0.0)
DECAY_IDLE_DAYS   = _int("DECAY_IDLE_DAYS", 14)

# Backups: periodic sqlite snapshots, plus optional off-box copy.
BACKUP_INTERVAL_HOURS = _int("BACKUP_INTERVAL_HOURS", 6)
BACKUP_KEEP           = _int("BACKUP_KEEP", 24)
BACKUP_CHANNEL_ID     = os.getenv("BACKUP_CHANNEL_ID")  # send snapshots here

# Ops.
LOG_LEVEL      = os.getenv("LOG_LEVEL", "INFO")
SENTRY_DSN     = os.getenv("SENTRY_DSN")
INSTANCE_PORT  = _int("INSTANCE_PORT", 47653)
ALLOW_MULTIPLE_INSTANCES = _bool("ALLOW_MULTIPLE_INSTANCES", False)

# Commands sent while the bot was down are replayed by default now that they
# mutate durable state. Set to 1 to go back to discarding them.
DROP_PENDING_UPDATES = _bool("DROP_PENDING_UPDATES", False)
