"""Fetching profile photos from Telegram.

Two things changed from the original: the smallest adequate PhotoSize is
requested instead of the largest available (a full-resolution portrait was
being downloaded to draw a 50-pixel circle), and the cache is bounded.
"""

import asyncio
import logging

from . import caches, config

log = logging.getLogger("rankbot.avatars")

# Largest diameter anything is drawn at — the rank card avatar at 2× supersample.
MAX_RENDER_DIAMETER = 108 * 2


def _pick_size(sizes, want: int):
    """Smallest PhotoSize at or above `want`, else the largest available."""
    usable = [p for p in sizes if p.width >= want]
    return min(usable, key=lambda p: p.width) if usable else max(sizes, key=lambda p: p.width)


async def fetch_avatar_bytes(bot, uid: int, want: int = MAX_RENDER_DIAMETER) -> bytes | None:
    """Profile photo bytes, or None for no photo / privacy restrictions / errors.

    A failed download and a member who genuinely has no photo are cached very
    differently. Treating both as "no photo" for the full hour meant one
    network blip left somebody showing initials long after the problem passed.
    """
    cached = caches.AVATAR_RAW.get(uid, default=...)
    if cached is not ...:
        return cached
    if caches.AVATAR_MISS.get(uid):
        return None                      # backing off from a recent failure

    try:
        photos = await bot.get_user_profile_photos(uid, limit=1)
        raw = None
        if photos.total_count and photos.photos and photos.photos[0]:
            chosen = _pick_size(photos.photos[0], want)
            handle = await bot.get_file(chosen.file_id)
            raw = bytes(await handle.download_as_bytearray())
    except Exception as e:
        # Short backoff, not an hour-long "they have no photo".
        log.info("avatar fetch failed for %s (%s: %s) — retrying in %ss",
                 uid, type(e).__name__, e, config.AVATAR_RETRY_SECONDS)
        caches.AVATAR_MISS.set(uid, True)
        return None

    caches.AVATAR_RAW.set(uid, raw)      # None here means "confirmed no photo"
    return raw


def pending_retry(uids) -> bool:
    """True when any of these avatars failed recently and is due a retry.

    Callers use this to avoid caching a rendered image that is missing photos
    it should have had — otherwise one blip is frozen into the board for hours.
    """
    return any(caches.AVATAR_MISS.get(uid) for uid in uids)


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
