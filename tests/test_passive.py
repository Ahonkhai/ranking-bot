"""Passive member indexing.

The point of this module is that an ordinary message — no command, no mention —
is enough to make someone resolvable by @handle later.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from telegram import Chat, Message, Update, User

from rankbot import store
from rankbot.handlers import passive
from tests.conftest import CHAT

GROUP = Chat(id=CHAT, type=Chat.SUPERGROUP, title="Test Group")


def make_user(uid, username=None, first="Test", last=None, is_bot=False):
    return User(id=uid, first_name=first, last_name=last, username=username,
                is_bot=is_bot)


def plain_message(user, text="just chatting", chat=GROUP):
    msg = Message(message_id=1, date=datetime.now(timezone.utc), chat=chat,
                  from_user=user, text=text)
    return Update(update_id=1, message=msg)


def observe(update):
    asyncio.run(passive.observe_message(update, None))


def test_an_ordinary_message_indexes_the_sender(fresh_db):
    observe(plain_message(make_user(555, username="daveh", first="Dave")))
    row = store.get_member(CHAT, 555)
    assert row is not None
    assert row["username"] == "daveh"
    assert row["full_name"] == "Dave"


def test_an_indexed_member_is_resolvable_by_handle(fresh_db):
    observe(plain_message(make_user(555, username="daveh")))
    assert [r["user_id"] for r in store.find_by_username(CHAT, "daveh")] == [555]
    # Handles are case-insensitive.
    assert [r["user_id"] for r in store.find_by_username(CHAT, "DaveH")] == [555]


def test_a_rename_updates_the_index(fresh_db):
    observe(plain_message(make_user(555, username="oldhandle")))
    observe(plain_message(make_user(555, username="newhandle")))
    assert store.find_by_username(CHAT, "oldhandle") == []
    assert [r["user_id"] for r in store.find_by_username(CHAT, "newhandle")] == [555]


def test_a_member_without_a_handle_is_still_indexed(fresh_db):
    observe(plain_message(make_user(556, first="Ada", last="Lovelace")))
    row = store.get_member(CHAT, 556)
    assert row["username"] is None
    assert row["full_name"] == "Ada Lovelace"


def test_bots_are_not_indexed(fresh_db):
    observe(plain_message(make_user(557, username="somebot", is_bot=True)))
    assert store.get_member(CHAT, 557) is None


def test_private_chats_are_ignored(fresh_db):
    private = Chat(id=999, type=Chat.PRIVATE)
    observe(plain_message(make_user(558, username="dm"), chat=private))
    assert store.get_member(999, 558) is None


def test_the_chat_is_registered_on_first_sight(fresh_db):
    other = Chat(id=-4242, type=Chat.SUPERGROUP, title="Brand New")
    observe(plain_message(make_user(559, username="x"), chat=other))
    assert store.current_season(-4242) == 1


def test_last_seen_is_not_rewritten_on_every_message(fresh_db):
    """The observer runs on every message in the group, so the common case has
    to be a read — otherwise a busy chat is a write per message."""
    user = make_user(555, username="daveh")
    observe(plain_message(user))
    first = store.get_member(CHAT, 555)["last_seen"]
    observe(plain_message(user))
    assert store.get_member(CHAT, 555)["last_seen"] == first


def test_a_stale_last_seen_is_refreshed(fresh_db):
    user = make_user(555, username="daveh")
    observe(plain_message(user))
    stale = (datetime.now(timezone.utc)
             - timedelta(seconds=store.SEEN_REFRESH_SECONDS + 60)).isoformat()
    with store.db.write() as c:
        c.execute("UPDATE members SET last_seen=? WHERE chat_id=? AND user_id=?",
                  (stale, CHAT, 555))
    observe(plain_message(user))
    assert store.get_member(CHAT, 555)["last_seen"] != stale


def test_indexing_failure_never_breaks_message_handling(fresh_db, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("database is on fire")
    monkeypatch.setattr(store, "upsert_member", boom)
    observe(plain_message(make_user(555, username="daveh")))   # must not raise


def test_joiners_are_indexed_before_they_speak(fresh_db):
    joiner = make_user(560, username="fresh", first="Fresh")
    msg = Message(message_id=2, date=datetime.now(timezone.utc), chat=GROUP,
                  from_user=make_user(1, username="inviter"),
                  new_chat_members=[joiner])
    asyncio.run(passive.observe_new_members(Update(update_id=2, message=msg), None))
    assert store.get_member(CHAT, 560) is not None
