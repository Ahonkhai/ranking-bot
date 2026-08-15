"""Amount parsing, HTML escaping, and — the one that used to pay the wrong
person — how a command decides who it is aimed at."""

from datetime import datetime, timezone

from telegram import Chat, Message, MessageEntity, Update, User

from rankbot import identity, store
from tests.conftest import CHAT

CHAT_OBJ = Chat(id=CHAT, type=Chat.SUPERGROUP)


def make_user(uid, username=None, first="Test", last=None, is_bot=False):
    return User(id=uid, first_name=first, last_name=last, username=username, is_bot=is_bot)


def make_update(text, from_user, entities=(), reply_to=None):
    msg = Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=CHAT_OBJ,
        from_user=from_user,
        text=text,
        entities=list(entities),
        reply_to_message=reply_to,
    )
    return Update(update_id=1, message=msg)


# ── amounts ──────────────────────────────────────────────────────────────

def test_parse_amount_forms():
    assert identity.parse_amount("5000") == 5000
    assert identity.parse_amount("5,000") == 5000
    assert identity.parse_amount("5k") == 5000
    assert identity.parse_amount("2.5k") == 2500
    assert identity.parse_amount("1m") == 1_000_000
    assert identity.parse_amount("-250") == -250


def test_parse_amount_rejects_junk():
    for junk in ("", "abc", "@dave", "5kk", "1e9", "∞"):
        assert identity.parse_amount(junk) is None


def test_parse_amount_rejects_absurd_values():
    assert identity.parse_amount("999999999999999") is None


def test_find_amount_ignores_the_handle_and_is_positional():
    # `/setcash @dave 500` used to be rejected because only args[0] was read.
    assert identity.find_amount(["@dave", "500"]) == 500
    assert identity.find_amount(["500", "@dave"]) == 500
    assert identity.find_amount(["@dave"]) is None


# ── escaping ─────────────────────────────────────────────────────────────

def test_escaping_neutralises_names_that_used_to_break_sends():
    assert identity.esc("the_real_dave") == "the_real_dave"
    assert identity.esc("<b>hax</b>") == "&lt;b&gt;hax&lt;/b&gt;"
    assert identity.esc("a & b") == "a &amp; b"


def test_display_name_prefers_the_handle():
    assert identity.display_name(make_user(1, username="alice")) == "@alice"
    assert identity.display_name(make_user(2, first="Bob", last="Jones")) == "Bob Jones"
    assert identity.display_name(make_user(3, first="")) == "User3"


# ── targets ──────────────────────────────────────────────────────────────

def test_reply_wins_and_carries_a_real_user_id(fresh_db):
    author = make_user(555, username="dave")
    reply_to = Message(message_id=9, date=datetime.now(timezone.utc),
                       chat=CHAT_OBJ, from_user=author, text="hi")
    update = make_update("/addcash 500", make_user(111), reply_to=reply_to)

    target = identity.resolve_target(update)
    assert target.ok
    assert target.user_id == 555
    assert target.name == "@dave"


def test_text_mention_uses_the_embedded_user_object(fresh_db):
    mentioned = make_user(777, first="No", last="Handle")
    text = "/addcash 500 No Handle"
    entity = MessageEntity(type=MessageEntity.TEXT_MENTION, offset=13, length=9,
                           user=mentioned)
    target = identity.resolve_target(make_update(text, make_user(111), [entity]))
    assert target.user_id == 777
    assert target.name == "No Handle"


def test_plain_handle_resolves_through_the_member_index(fresh_db):
    store.upsert_member(CHAT, 888, "bob", "Bob")
    text = "/addcash 500 @bob"
    entity = MessageEntity(type=MessageEntity.MENTION, offset=13, length=4)
    target = identity.resolve_target(make_update(text, make_user(111), [entity]))
    assert target.user_id == 888


def test_handle_lookup_ignores_casing(fresh_db):
    """Telegram handles are case-insensitive, and the stored casing is the
    one the member actually uses."""
    store.upsert_member(CHAT, 999, "Charan1326", "Charan")
    text = "/addcash 500 @charan1326"
    entity = MessageEntity(type=MessageEntity.MENTION, offset=13, length=11)
    target = identity.resolve_target(make_update(text, make_user(111), [entity]))
    assert target.user_id == 999
    assert target.name == "@Charan1326"


def test_unknown_handle_refuses_rather_than_guessing(fresh_db):
    text = "/addcash 500 @ghost"
    entity = MessageEntity(type=MessageEntity.MENTION, offset=13, length=6)
    target = identity.resolve_target(make_update(text, make_user(111), [entity]))
    assert not target.ok
    assert target.error and "isn't indexed" in target.error


def test_a_recycled_handle_cannot_be_paid_from_a_stale_record(fresh_db):
    """The original failure: someone changes handle, a stranger claims it, and
    the old display string routes the payment to the wrong person."""
    store.upsert_member(CHAT, 1001, "olduser", "Original Owner")
    # They rename; the index is refreshed from live traffic.
    store.upsert_member(CHAT, 1001, "newuser", "Original Owner")
    # A different person claims the abandoned handle.
    store.upsert_member(CHAT, 2002, "olduser", "Someone Else")

    text = "/addcash 500 @olduser"
    entity = MessageEntity(type=MessageEntity.MENTION, offset=13, length=8)
    target = identity.resolve_target(make_update(text, make_user(111), [entity]))

    # Resolves to the account that actually holds the handle now, not to the
    # stale record for user 1001.
    assert target.user_id == 2002


def test_ambiguous_handle_refuses(fresh_db):
    # Two stale records claiming one handle: refuse rather than pick a winner.
    store.upsert_member(CHAT, 3001, "twin", "One")
    store.upsert_member(CHAT, 3002, "twin", "Two")
    text = "/addcash 500 @twin"
    entity = MessageEntity(type=MessageEntity.MENTION, offset=13, length=5)
    target = identity.resolve_target(make_update(text, make_user(111), [entity]))
    assert not target.ok
    assert "More than one" in target.error


def test_bots_are_not_targets(fresh_db):
    bot_user = make_user(4004, username="somebot", is_bot=True)
    reply_to = Message(message_id=9, date=datetime.now(timezone.utc),
                       chat=CHAT_OBJ, from_user=bot_user, text="beep")
    target = identity.resolve_target(make_update("/addcash 500", make_user(111),
                                                 reply_to=reply_to))
    assert not target.ok
    assert "bot" in target.error.lower()


def test_no_target_named_returns_empty_not_an_error(fresh_db):
    target = identity.resolve_target(make_update("/addcash 500", make_user(111)))
    assert not target.ok
    assert target.error is None
