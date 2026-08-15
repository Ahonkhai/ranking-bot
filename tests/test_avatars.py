"""Profile photo fetching.

The failure mode here is quiet: a photo doesn't load, the member silently gets
an initials disc, and — before these fixes — stayed that way for an hour or
six even after the problem cleared.
"""

import asyncio

import pytest

from rankbot import avatars, caches, config


class FakePhotoSize:
    def __init__(self, width, file_id="f"):
        self.width = width
        self.file_id = file_id


class FakePhotos:
    def __init__(self, sizes):
        self.photos = [sizes] if sizes else []
        self.total_count = 1 if sizes else 0


class FakeFile:
    def __init__(self, data=b"imagebytes"):
        self._data = data

    async def download_as_bytearray(self):
        return bytearray(self._data)


class FakeBot:
    """Counts calls, so a test can prove a retry did or didn't happen."""

    def __init__(self, sizes=(200, 400), fail=False, data=b"imagebytes"):
        self.sizes = sizes
        self.fail = fail
        self.data = data
        self.profile_calls = 0

    async def get_user_profile_photos(self, uid, limit=1):
        self.profile_calls += 1
        if self.fail:
            raise RuntimeError("telegram is having a moment")
        return FakePhotos([FakePhotoSize(w) for w in self.sizes])

    async def get_file(self, file_id):
        return FakeFile(self.data)


@pytest.fixture(autouse=True)
def clear_caches():
    caches.AVATAR_RAW.clear()
    caches.AVATAR_MISS.clear()
    caches.AVATAR_DISC.clear()
    yield
    caches.AVATAR_RAW.clear()
    caches.AVATAR_MISS.clear()


def fetch(bot, uid=1):
    return asyncio.run(avatars.fetch_avatar_bytes(bot, uid))


def test_a_photo_is_downloaded_and_cached():
    bot = FakeBot()
    assert fetch(bot) == b"imagebytes"
    assert fetch(bot) == b"imagebytes"
    assert bot.profile_calls == 1          # second call served from cache


def test_the_smallest_adequate_size_is_chosen():
    sizes = [FakePhotoSize(w) for w in (60, 240, 640)]
    assert avatars._pick_size(sizes, 216).width == 240


def test_the_largest_is_used_when_nothing_is_big_enough():
    sizes = [FakePhotoSize(w) for w in (60, 120)]
    assert avatars._pick_size(sizes, 216).width == 120


def test_no_photo_is_cached_as_no_photo():
    bot = FakeBot(sizes=())
    assert fetch(bot) is None
    assert fetch(bot) is None
    assert bot.profile_calls == 1          # settled; don't keep asking
    assert not avatars.pending_retry([1])  # and it isn't a failure


def test_a_failure_is_not_mistaken_for_having_no_photo():
    """The bug: one network blip used to cache None for the full AVATAR_TTL,
    so a member showed initials for an hour after the problem passed."""
    bot = FakeBot(fail=True)
    assert fetch(bot) is None
    assert avatars.pending_retry([1])
    # Nothing durable was written, so the next window retries.
    assert caches.AVATAR_RAW.get(1, default=...) is ...


def test_a_failure_backs_off_rather_than_hammering():
    bot = FakeBot(fail=True)
    fetch(bot)
    fetch(bot)
    fetch(bot)
    assert bot.profile_calls == 1          # backing off within the window


def test_a_recovered_avatar_loads_after_the_backoff_expires(monkeypatch):
    failing = FakeBot(fail=True)
    assert fetch(failing) is None

    caches.AVATAR_MISS.clear()             # stands in for the TTL expiring
    healthy = FakeBot()
    assert fetch(healthy) == b"imagebytes"
    assert not avatars.pending_retry([1])


def test_pending_retry_is_per_member():
    bot = FakeBot(fail=True)
    fetch(bot, uid=7)
    assert avatars.pending_retry([7])
    assert not avatars.pending_retry([8])
    assert avatars.pending_retry([8, 7])   # any of them


def test_fetch_many_returns_one_entry_per_member():
    bot = FakeBot()
    got = asyncio.run(avatars.fetch_many(bot, [1, 2, 3]))
    assert set(got) == {1, 2, 3}
    assert all(v == b"imagebytes" for v in got.values())


def test_fetch_many_survives_a_failing_member():
    bot = FakeBot(fail=True)
    got = asyncio.run(avatars.fetch_many(bot, [1, 2]))
    assert got == {1: None, 2: None}


def test_fetch_many_of_nothing():
    assert asyncio.run(avatars.fetch_many(FakeBot(), [])) == {}


def test_the_backoff_is_shorter_than_the_photo_cache():
    """A failure must expire long before a confirmed 'no photo' does, or the
    retry never gets a chance."""
    assert config.AVATAR_RETRY_SECONDS < config.AVATAR_TTL
