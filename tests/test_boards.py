"""Board assembly: page maths, true global ranks, movement, and the
'you are here' strip for members who fall off the visible page."""

import asyncio

import pytest

from rankbot import caches, config, store
from rankbot.handlers import boards
from tests.conftest import CHAT

ADMIN = 111


class StubChat:
    """Enough of a Chat for build_page: an id, a title and an admin list."""

    def __init__(self, admins=()):
        self.id = CHAT
        self.title = "Test Group"
        self.type = "supergroup"
        self._admins = list(admins)

    async def get_administrators(self):
        class Member:
            def __init__(self, uid):
                self.user = type("U", (), {"id": uid})()
        return [Member(uid) for uid in self._admins]


@pytest.fixture()
def seeded(fresh_db):
    """40 members, descending balances, so uid 2000 is rank 1."""
    caches.ADMINS.clear()
    caches.BOARD_FILE_IDS.clear()
    for i in range(40):
        uid = 2000 + i
        store.upsert_member(CHAT, uid, f"member{i:02d}", None)
        store.award(CHAT, uid, 10_000 - i * 100, ADMIN, "seed")
    return CHAT


def build(chat, scope="season", page=1, viewer=None):
    return asyncio.run(boards.build_page(None, chat, scope, page, viewer))


def test_first_page_carries_true_ranks(seeded):
    _key, rows, kwargs, _cap, pages, page = build(StubChat())
    assert (page, pages) == (1, 3)
    assert len(rows) == config.PAGE_SIZE
    assert rows[0]["rank"] == 1
    assert rows[-1]["rank"] == 15
    assert kwargs["total"] == 40


def test_later_page_continues_the_numbering(seeded):
    _key, rows, _kwargs, _cap, _pages, page = build(StubChat(), page=3)
    assert page == 3
    assert rows[0]["rank"] == 31
    assert rows[-1]["rank"] == 40      # last page is short
    assert len(rows) == 10


def test_page_beyond_the_end_clamps(seeded):
    _key, rows, _kwargs, _cap, _pages, page = build(StubChat(), page=99)
    assert page == 3
    assert rows[0]["rank"] == 31


def test_you_strip_appears_only_when_off_page(seeded):
    on_page = build(StubChat(), viewer=2000)[2]["you"]
    assert on_page is None

    off_page = build(StubChat(), viewer=2035)[2]["you"]
    assert off_page["rank"] == 36
    assert "BEHIND" in off_page["note"]


def test_you_strip_is_absent_for_a_non_member(seeded):
    assert build(StubChat(), viewer=999999)[2]["you"] is None


def test_leader_off_page_gets_no_behind_note(seeded):
    """Rank 1 has nobody ahead, so there's no gap to report."""
    _k, _r, kwargs, _c, _p, _pg = build(StubChat(), page=2, viewer=2000)
    assert kwargs["you"]["rank"] == 1
    assert kwargs["you"]["note"] == ""


def test_fingerprint_changes_when_the_board_does(seeded):
    first = build(StubChat())[0]
    assert build(StubChat())[0] == first          # identical inputs, same key
    store.award(CHAT, 2039, 50_000, ADMIN)        # last place vaults to first
    assert build(StubChat())[0] != first


def test_fingerprint_changes_when_the_admin_set_does(seeded):
    plain = build(StubChat())[0]
    caches.ADMINS.clear()
    crowned = build(StubChat(admins=[2000]))[0]
    assert plain != crowned


def test_movement_is_only_computed_for_cumulative_scopes(seeded):
    assert build(StubChat(), scope="week")[2]["movement"] == {}
    assert build(StubChat(), scope="season")[2]["movement"] == {}  # all seeded now


def test_keyboard_only_appears_when_paging_is_possible():
    assert boards.keyboard("season", 1, 1) is None
    kb = boards.keyboard("season", 2, 3)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "◀ Prev" in labels and "Next ▶" in labels and "2/3" in labels


def test_empty_board_yields_no_rows(fresh_db):
    caches.ADMINS.clear()
    _key, rows, kwargs, _cap, pages, _page = build(StubChat())
    assert rows == []
    assert kwargs["total"] == 0
    assert pages == 1
