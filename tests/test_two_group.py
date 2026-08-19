"""Two-group mode: an admin group and a public one over one set of scores.

The property under test throughout is that the *group* decides what you may
do, and never what the data says.
"""

import asyncio
import sqlite3

import pytest

from rankbot import config, db, store
from rankbot.handlers import common

BACKEND = -1001111111111
FRONTEND = -1002222222222
STRANGER = -1009999999999
ADMIN = 111
DAVID = 222


@pytest.fixture()
def two_groups(monkeypatch):
    monkeypatch.setattr(config, "BACKEND_GROUP_ID", BACKEND)
    monkeypatch.setattr(config, "FRONTEND_GROUP_ID", FRONTEND)
    monkeypatch.setattr(config, "TWO_GROUP_MODE", True)
    yield


# ── routing ──────────────────────────────────────────────────────────────

def test_both_groups_resolve_to_one_board(two_groups):
    assert config.board_for(BACKEND) == BACKEND
    assert config.board_for(FRONTEND) == BACKEND


def test_an_unconfigured_chat_keeps_its_own_board(two_groups):
    assert config.board_for(STRANGER) == STRANGER


def test_without_configuration_nothing_changes(monkeypatch):
    """A single-group deployment must behave exactly as before."""
    monkeypatch.setattr(config, "TWO_GROUP_MODE", False)
    assert config.board_for(BACKEND) == BACKEND
    assert config.board_for(FRONTEND) == FRONTEND
    assert config.is_backend(FRONTEND) is True      # no restriction to apply
    assert config.is_known_chat(STRANGER) is True


def test_only_the_backend_may_change_scores(two_groups):
    assert config.is_backend(BACKEND) is True
    assert config.is_backend(FRONTEND) is False
    assert config.is_backend(STRANGER) is False


def test_unconfigured_groups_are_not_recognised(two_groups):
    assert config.is_known_chat(BACKEND) is True
    assert config.is_known_chat(FRONTEND) is True
    assert config.is_known_chat(STRANGER) is False


def test_invalidating_one_group_clears_the_other(two_groups):
    """An admin edit in the backend must not leave the public group showing a
    cached image of the old scores."""
    assert set(config.chats_for_board(BACKEND)) == {BACKEND, FRONTEND}


# ── one source of truth ──────────────────────────────────────────────────

def test_a_backend_edit_is_visible_from_the_frontend(fresh_db, two_groups):
    """The scenario from the brief: set in the admin group, read in public."""
    store.ensure_chat(config.board_for(BACKEND))
    store.award(config.board_for(BACKEND), DAVID, 500, ADMIN)
    assert store.balance(config.board_for(FRONTEND), DAVID) == 500

    store.set_balance(config.board_for(BACKEND), DAVID, 1_000, ADMIN)
    assert store.balance(config.board_for(FRONTEND), DAVID) == 1_000


def test_ranking_is_global_not_per_group(fresh_db, two_groups):
    board = config.board_for(BACKEND)
    store.ensure_chat(board)
    for uid, amount in ((1, 100_000), (2, 50_000), (3, 25_000)):
        store.award(board, uid, amount, ADMIN)

    from_frontend = store.standings(config.board_for(FRONTEND))
    assert [r["user_id"] for r in from_frontend] == [1, 2, 3]
    assert [r["rank"] for r in from_frontend] == [1, 2, 3]
    assert store.rank_of(config.board_for(FRONTEND), 2)[0] == 2


def test_achievements_are_shared_across_the_groups(fresh_db, two_groups):
    from rankbot import achievements
    board = config.board_for(BACKEND)
    store.ensure_chat(board)
    store.award(board, DAVID, 900, ADMIN)
    assert achievements.check(board, DAVID) == []

    store.award(board, DAVID, 100, ADMIN)          # crosses $1,000
    unlocked = [a.code for a in achievements.check(board, DAVID)]
    assert "first_bag" in unlocked
    # And the public group sees the same badge.
    held = [a.code for a in achievements.held_by(config.board_for(FRONTEND), DAVID)]
    assert "first_bag" in held


def test_a_member_is_one_record_across_both_groups(fresh_db, two_groups):
    """Identified by user id, so the same person in either group is one row."""
    store.upsert_member(config.board_for(BACKEND), DAVID, "david", "David")
    store.upsert_member(config.board_for(FRONTEND), DAVID, "david", "David")
    rows = db.get().execute(
        "SELECT COUNT(*) AS n FROM members WHERE user_id=?", (DAVID,)).fetchone()
    assert rows["n"] == 1


def test_joined_at_is_not_reset_by_appearing_in_the_other_group(fresh_db, two_groups):
    store.upsert_member(config.board_for(BACKEND), DAVID, "david", "David")
    first = store.get_member(config.board_for(BACKEND), DAVID)["joined_at"]
    store.upsert_member(config.board_for(FRONTEND), DAVID, "david", "David Renamed")
    assert store.get_member(config.board_for(BACKEND), DAVID)["joined_at"] == first


# ── guards ───────────────────────────────────────────────────────────────

class FakeChat:
    def __init__(self, chat_id, chat_type="supergroup"):
        self.id = chat_id
        self.type = chat_type
        self.title = "T"


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return None


class FakeUpdate:
    def __init__(self, chat_id, chat_type="supergroup"):
        self.effective_chat = FakeChat(chat_id, chat_type)
        self.effective_message = FakeMessage()
        self.effective_user = None


def test_require_backend_rejects_the_public_group(two_groups):
    upd = FakeUpdate(FRONTEND)
    assert asyncio.run(common.require_backend(upd)) is False
    assert "admin group" in upd.effective_message.sent[0]


def test_require_backend_allows_the_admin_group(two_groups):
    upd = FakeUpdate(BACKEND)
    assert asyncio.run(common.require_backend(upd)) is True
    assert upd.effective_message.sent == []


def test_an_unconfigured_group_is_turned_away(two_groups):
    upd = FakeUpdate(STRANGER)
    assert asyncio.run(common.ensure_group(upd)) is False
    assert "isn't configured" in upd.effective_message.sent[0]


def test_configured_groups_pass_the_gate(two_groups):
    for chat_id in (BACKEND, FRONTEND):
        upd = FakeUpdate(chat_id)
        assert asyncio.run(common.ensure_group(upd)) is True


def test_private_chats_are_still_refused(two_groups):
    upd = FakeUpdate(BACKEND, chat_type="private")
    assert asyncio.run(common.ensure_group(upd)) is False


# ── merging an existing split ────────────────────────────────────────────

def test_switching_the_mode_on_merges_the_two_boards(tmp_path, monkeypatch):
    """Two-group mode can be enabled after the bot has already run in both
    chats; their scores have to become one board, not stay two."""
    path = tmp_path / "split.db"
    db.close()
    monkeypatch.setattr(config, "TWO_GROUP_MODE", False)
    monkeypatch.setattr(config, "DB_PATH", str(path))
    conn = db.connect(str(path))
    store.ensure_chat(BACKEND)
    store.ensure_chat(FRONTEND)
    store.upsert_member(BACKEND, DAVID, "david", "David")
    store.upsert_member(FRONTEND, DAVID, "david", "David")
    store.award(BACKEND, DAVID, 500, ADMIN)
    store.award(FRONTEND, DAVID, 300, ADMIN)
    store.record_achievements(FRONTEND, DAVID, ["first_bag"], 300)
    db.close()

    monkeypatch.setattr(config, "BACKEND_GROUP_ID", BACKEND)
    monkeypatch.setattr(config, "FRONTEND_GROUP_ID", FRONTEND)
    monkeypatch.setattr(config, "TWO_GROUP_MODE", True)
    conn = db.connect(str(path))
    try:
        # Both histories now live on one board.
        assert store.balance(BACKEND, DAVID) == 800
        assert conn.execute("SELECT COUNT(*) AS n FROM ledger WHERE chat_id=?",
                            (FRONTEND,)).fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM members WHERE user_id=?",
                            (DAVID,)).fetchone()["n"] == 1
        assert "first_bag" in store.recorded_achievements(BACKEND, DAVID)
    finally:
        db.close()


def test_the_merge_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "again.db"
    db.close()
    monkeypatch.setattr(config, "BACKEND_GROUP_ID", BACKEND)
    monkeypatch.setattr(config, "FRONTEND_GROUP_ID", FRONTEND)
    monkeypatch.setattr(config, "TWO_GROUP_MODE", True)
    monkeypatch.setattr(config, "DB_PATH", str(path))
    for _ in range(2):
        conn = db.connect(str(path))
        store.ensure_chat(BACKEND)
        store.award(BACKEND, DAVID, 100, ADMIN)
        db.close()
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM ledger WHERE chat_id=?",
                            (FRONTEND,)).fetchone()[0] == 0
        assert conn.execute("SELECT SUM(delta) FROM ledger WHERE chat_id=?",
                            (BACKEND,)).fetchone()[0] == 200
    finally:
        conn.close()


# ── the index is shared too ──────────────────────────────────────────────

def test_speaking_in_either_group_indexes_you_on_the_shared_board(fresh_db, two_groups):
    """Members only ever chat in the public group, but admins target them from
    the admin group — so the index has to be shared, not per chat."""
    import asyncio
    from datetime import datetime, timezone
    from telegram import Chat, Message, Update, User
    from rankbot.handlers import passive

    public = Chat(id=FRONTEND, type=Chat.SUPERGROUP, title="Public")
    dave = User(id=555, first_name="Dave", username="daveh", is_bot=False)
    msg = Message(message_id=1, date=datetime.now(timezone.utc), chat=public,
                  from_user=dave, text="hey everyone")
    asyncio.run(passive.observe_message(Update(update_id=1, message=msg), None))

    # Indexed against the shared board, not the chat it was said in.
    assert store.get_member(config.board_for(BACKEND), 555) is not None
    # And therefore findable by handle from the admin group.
    found = store.find_by_username(config.board_for(BACKEND), "daveh")
    assert [r["user_id"] for r in found] == [555]


# ── a third, unrelated group ────────────────────────────────────────────

EXTRA = -1003333333333


@pytest.fixture()
def two_groups_plus_extra(monkeypatch, two_groups):
    monkeypatch.setattr(config, "EXTRA_GROUP_IDS", (EXTRA,))
    yield


def test_extra_group_keeps_its_own_board(two_groups_plus_extra):
    assert config.board_for(EXTRA) == EXTRA
    assert config.board_for(EXTRA) != config.board_for(BACKEND)


def test_extra_group_is_recognised(two_groups_plus_extra):
    assert config.is_known_chat(EXTRA) is True
    # A group not listed anywhere still isn't.
    assert config.is_known_chat(STRANGER) is False


def test_extra_group_may_change_its_own_scores(two_groups_plus_extra):
    assert config.is_backend(EXTRA) is True


def test_extra_group_is_not_pulled_into_shared_invalidation(two_groups_plus_extra):
    assert config.chats_for_board(EXTRA) == (EXTRA,)
    assert EXTRA not in config.chats_for_board(BACKEND)


def test_extra_group_passes_the_gate_and_can_write(two_groups_plus_extra):
    upd = FakeUpdate(EXTRA)
    assert asyncio.run(common.ensure_group(upd)) is True
    assert asyncio.run(common.require_backend(upd)) is True


def test_extra_group_scores_stay_separate_from_the_shared_board(fresh_db, two_groups_plus_extra):
    store.ensure_chat(config.board_for(BACKEND))
    store.award(config.board_for(BACKEND), DAVID, 500, ADMIN)

    store.ensure_chat(config.board_for(EXTRA))
    store.award(config.board_for(EXTRA), DAVID, 50, ADMIN)

    assert store.balance(config.board_for(BACKEND), DAVID) == 500
    assert store.balance(config.board_for(EXTRA), DAVID) == 50


def test_a_stranger_group_cannot_pollute_the_shared_index(fresh_db, two_groups):
    import asyncio
    from datetime import datetime, timezone
    from telegram import Chat, Message, Update, User
    from rankbot.handlers import passive

    other = Chat(id=STRANGER, type=Chat.SUPERGROUP, title="Someone else's")
    intruder = User(id=666, first_name="Nope", username="nope", is_bot=False)
    msg = Message(message_id=1, date=datetime.now(timezone.utc), chat=other,
                  from_user=intruder, text="hello")
    asyncio.run(passive.observe_message(Update(update_id=1, message=msg), None))

    assert store.get_member(config.board_for(BACKEND), 666) is None
