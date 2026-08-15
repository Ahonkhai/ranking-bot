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

# Storage. DATA_FILE is only read once, by the migration.
DB_PATH   = os.getenv("DB_PATH", "data.db")
DATA_FILE = os.getenv("DATA_FILE", "data.json")

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

# Cache lifetimes, seconds.
ADMIN_TTL  = _int("ADMIN_TTL", 300)
AVATAR_TTL = _int("AVATAR_TTL", 3600)

# Bounded cache sizes, entries.
AVATAR_RAW_MAX  = _int("AVATAR_RAW_MAX", 512)
AVATAR_DISC_MAX = _int("AVATAR_DISC_MAX", 512)
BOARD_CACHE_MAX = _int("BOARD_CACHE_MAX", 256)

# Concurrent PIL renders. Cheap now that gradients are memoized, but still
# bounded so a burst can't pin every core.
RENDER_CONCURRENCY = _int("RENDER_CONCURRENCY", 3)

# Per-user, per-command cooldown for the expensive read commands.
COOLDOWN_SECONDS = _float("COOLDOWN_SECONDS", 4.0)

# Member-to-member /give transfers.
ALLOW_TRANSFERS = _bool("ALLOW_TRANSFERS", True)

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
