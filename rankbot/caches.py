"""Bounded caches for the three things that used to cost an API call or a
full re-render on every command: admin lists, avatars, and rendered boards.
"""

import logging
import threading
import time
from collections import OrderedDict

from . import config

log = logging.getLogger("rankbot.caches")


class TTLCache:
    """Small LRU with a time bound. Bounded on purpose — the old avatar cache
    was a plain dict that was refreshed but never evicted, so it grew for the
    lifetime of the process.

    Locked because the avatar caches are read from the render worker threads
    as well as the event loop.
    """

    def __init__(self, maxsize: int, ttl: float | None = None):
        self.maxsize = maxsize
        self.ttl = ttl
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            entry = self._d.get(key)
            if entry is None:
                return default
            ts, value = entry
            if self.ttl is not None and time.time() - ts > self.ttl:
                self._d.pop(key, None)
                return default
            self._d.move_to_end(key)
            return value

    def set(self, key, value) -> None:
        with self._lock:
            self._d[key] = (time.time(), value)
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def pop(self, key) -> None:
        with self._lock:
            self._d.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def drop_prefix(self, prefix) -> int:
        """Invalidate every key whose leading elements match `prefix`."""
        n = len(prefix)
        with self._lock:
            doomed = [k for k in self._d if isinstance(k, tuple) and k[:n] == prefix]
            for k in doomed:
                self._d.pop(k, None)
        return len(doomed)

    def __len__(self) -> int:
        return len(self._d)


# chat_id -> set of admin user ids
ADMINS = TTLCache(maxsize=512, ttl=config.ADMIN_TTL)

# user_id -> raw profile photo bytes (or None when they have none / it's private)
AVATAR_RAW = TTLCache(maxsize=config.AVATAR_RAW_MAX, ttl=config.AVATAR_TTL)

# (user_id, diameter) -> processed circular RGBA avatar
AVATAR_DISC = TTLCache(maxsize=config.AVATAR_DISC_MAX, ttl=config.AVATAR_TTL)

# user_id -> True, for avatars whose download just failed. Separate from
# AVATAR_RAW so a transient error expires in seconds rather than being
# mistaken for "this member has no photo" for the full hour.
AVATAR_MISS = TTLCache(maxsize=config.AVATAR_RAW_MAX,
                       ttl=config.AVATAR_RETRY_SECONDS)

# board fingerprint -> Telegram file_id, so an unchanged board is re-sent
# rather than re-rendered and re-uploaded
BOARD_FILE_IDS = TTLCache(maxsize=config.BOARD_CACHE_MAX, ttl=6 * 3600)


def invalidate_chat(chat_id: int) -> None:
    """Call after any ledger write: the board picture may have changed."""
    BOARD_FILE_IDS.drop_prefix((chat_id,))


def invalidate_admins(chat_id: int) -> None:
    ADMINS.pop(chat_id)
    BOARD_FILE_IDS.drop_prefix((chat_id,))  # crowns are drawn from the admin set


async def admin_ids(chat, force: bool = False) -> set[int]:
    """Admin user ids for a chat, cached.

    Refreshed on a TTL and invalidated immediately by the ChatMemberHandler,
    so it can't be meaningfully stale.
    """
    cached = None if force else ADMINS.get(chat.id)
    if cached is not None:
        return cached
    try:
        admins = await chat.get_administrators()
        ids = {a.user.id for a in admins}
    except Exception as e:  # private chat, missing rights, transient API error
        log.debug("admin lookup failed for %s: %s", chat.id, e)
        ids = set()
    ADMINS.set(chat.id, ids)
    return ids
