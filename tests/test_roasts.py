"""Replies for members who aren't on the board.

The distinction that matters is between "no ledger entry at all" and "ranked
with a balance of $0" — the second is a real member and must still get a card.
"""

import random

from rankbot import cards, roasts, store
from tests.conftest import CHAT

ADMIN = 111
ALICE = 222


def test_self_responses_come_from_the_pool():
    for _ in range(50):
        assert roasts.get_unranked_self_response() in roasts.SELF_RESPONSES


def test_self_responses_are_second_person():
    """`/rank` on yourself must not read as though it's about someone else."""
    for line in roasts.SELF_RESPONSES:
        assert "{name}" not in line


def test_other_responses_carry_the_name():
    for _ in range(50):
        line = roasts.get_unranked_user_response("@dave")
        assert line.startswith("@dave ")
        assert any(line == t.format(name="@dave") for t in roasts.OTHER_RESPONSES)


def test_the_name_is_not_hardcoded():
    assert "@dave" not in "".join(roasts.OTHER_RESPONSES)
    assert roasts.get_unranked_user_response("Ada Lovelace").startswith("Ada Lovelace ")


def test_selection_is_random_not_a_fixed_answer():
    random.seed(1)
    seen = {roasts.get_unranked_self_response() for _ in range(200)}
    assert len(seen) > 1
    seen = {roasts.get_unranked_user_response("@x") for _ in range(200)}
    assert len(seen) > 1


def test_every_response_is_short_and_unadorned():
    """The joke is the whole point: no emoji, no explanation."""
    for line in roasts.SELF_RESPONSES + roasts.OTHER_RESPONSES:
        assert len(line) < 45
        assert line.isascii()          # rules out emoji
        assert "." not in line


# ── what counts as unranked ──────────────────────────────────────────────

def test_a_member_with_no_entry_has_no_card(fresh_db):
    assert cards.build(CHAT, ALICE, "@alice") is None


def test_a_member_sitting_on_zero_is_still_ranked(fresh_db):
    """They have a ledger entry, so they get a card rather than a roast."""
    store.award(CHAT, ALICE, 0, ADMIN, "seed")
    card = cards.build(CHAT, ALICE, "@alice")
    assert card is not None
    assert card.cash == 0


def test_a_member_deducted_back_to_zero_is_still_ranked(fresh_db):
    store.award(CHAT, ALICE, 500, ADMIN)
    store.deduct(CHAT, ALICE, 500, ADMIN)
    assert store.balance(CHAT, ALICE) == 0
    assert cards.build(CHAT, ALICE, "@alice") is not None


def test_an_undone_award_leaves_the_member_on_the_board(fresh_db):
    """Undo voids the award but writes a zero-delta audit row, and that row is
    enough to keep them ranked at $0. They stay a participant rather than
    vanishing, which is the same answer as being deducted back to zero."""
    store.award(CHAT, ALICE, 500, ADMIN)
    store.undo_last(CHAT, ADMIN)
    card = cards.build(CHAT, ALICE, "@alice")
    assert card is not None
    assert card.cash == 0


def test_a_new_season_makes_everyone_unranked_until_they_score(fresh_db):
    store.award(CHAT, ALICE, 500, ADMIN)
    store.close_season(CHAT)
    assert cards.build(CHAT, ALICE, "@alice") is None
