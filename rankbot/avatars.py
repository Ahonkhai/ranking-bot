"""Fetching profile photos from Telegram.

Two things changed from the original: the smallest adequate PhotoSize is
requested instead of the largest available (a full-resolution portrait was
being downloaded to draw a 50-pixel circle), and the cache is bounded.
"""

import asyncio
import logging

from . import caches

log = logging.getLogger("rankbot.avatars")

# Largest diameter anything is drawn at — the rank card avatar at 2× supersample.
MAX_RENDER_DIAMETER = 108 * 2


def _pick_size(sizes, want: int):
    """Smallest PhotoSize at or above `want`, else the largest available."""
    usable = [p for p in sizes if p.width >= want]
    return min(usable, key=lambda p: p.width) if usable else max(sizes, key=lambda p: p.width)


async def fetch_avatar_bytes(bot, uid: int, want: int = MAX_RENDER_DIAMETER) -> bytes | None:
    """Profile photo bytes, or None for no photo / privacy restrictions / errors."""
    cached = caches.AVATAR_RAW.get(uid, default=...)
    if cached is not ...:
        return cached

    raw = None
    try:
        photos = await bot.get_user_profile_photos(uid, limit=1)
        if photos.total_count and photos.photos and photos.photos[0]:
            chosen = _pick_size(photos.photos[0], want)
            handle = await bot.get_file(chosen.file_id)
            raw = bytes(await handle.download_as_bytearray())
    except Exception as e:
        log.debug("avatar fetch failed for %s: %s", uid, e)
        raw = None

    caches.AVATAR_RAW.set(uid, raw)
    return raw


async def fetch_many(bot, uids) -> dict[int, bytes | None]:
    """Avatars for a page of the leaderboard, concurrently."""
    uids = list(uids)
    if not uids:
        return {}
    results = await asyncio.gather(
        *(fetch_avatar_bytes(bot, uid) for uid in uids),
        return_exceptions=True,
    )
    return {
        uid: (None if isinstance(r, BaseException) else r)
        for uid, r in zip(uids, results)
    }
