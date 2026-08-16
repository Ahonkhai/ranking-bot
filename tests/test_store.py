"""Ledger arithmetic: the property that matters is that a balance is always
the sum of its entries, whatever sequence of operations produced it."""

import random

from rankbot import store
from tests.conftest import CHAT

ADMIN = 111
ALICE = 222
BOB = 333


def test_award_accumulates(fresh_db):
    store.award(CHAT, ALICE, 500, ADMIN, "first")
    store.award(CHAT, ALICE, 250, ADMIN, "second")
    assert store.balance(CHAT, ALICE) == 750


def test_set_balance_is_stored_as_a_difference(fresh_db):
    store.award(CHAT, ALICE, 1000, ADMIN)
    delta, new = store.set_balance(CHAT, ALICE, 400, ADMIN)
    assert (delta, new) == (-600, 400)
    assert store.balance(CHAT, ALICE) == 400
    # The original entry is still there; nothing was overwritten.
    assert len(store.history(CHAT, ALICE)) == 2


def test_deduct_floors_at_zero(fresh_db):
    store.award(CHAT, ALICE, 300, ADMIN)
    removed, new = store.deduct(CHAT, ALICE, 1000, ADMIN)
    assert removed == 300
    assert new == 0
    assert store.balance(CHAT, ALICE) == 0


def test_deduct_on_empty_member_is_a_no_op(fresh_db):
    removed, new = store.deduct(CHAT, ALICE, 500, ADMIN)
    assert (removed, new) == (0, 0)


def test_boards_are_isolated_per_chat(fresh_db):
    other = -1009999999999
    store.ensure_chat(other, "Other Group")
    store.award(CHAT, ALICE, 500, ADMIN)
    store.award(other, ALICE, 40, ADMIN)
    assert store.balance(CHAT, ALICE) == 500
    assert store.balance(other, ALICE) == 40
    assert [r["user_id"] for r in store.standings(other)] == [ALICE]
    assert store.rank_of(other, BOB) == (None, 1)


def test_standings_order_and_rank(fresh_db):
    store.award(CHAT, ALICE, 100, ADMIN)
    store.award(CHAT, BOB, 900, ADMIN)
    board = store.standings(CHAT)
    assert [r["user_id"] for r in board] == [BOB, ALICE]
    assert store.rank_of(CHAT, ALICE) == (2, 2)
    assert store.rank_of(CHAT, BOB) == (1, 2)


def test_undo_reverses_the_last_entry(fresh_db):
    store.award(CHAT, ALICE, 500, ADMIN)
    store.award(CHAT, ALICE, 5_000_000, ADMIN)   # the fat-finger
    assert store.balance(CHAT, ALICE) == 5_000_500

    result = store.undo_last(CHAT, ADMIN)
    assert result["delta"] == 5_000_000
    assert store.balance(CHAT, ALICE) == 500


def test_undo_walks_backwards(fresh_db):
    store.award(CHAT, ALICE, 100, ADMIN)
    store.award(CHAT, ALICE, 200, ADMIN)
    store.undo_last(CHAT, ADMIN)
    store.undo_last(CHAT, ADMIN)
    assert store.balance(CHAT, ALICE) == 0
    assert store.undo_last(CHAT, ADMIN) is None


def test_undo_keeps_the_voided_row_visible_in_history(fresh_db):
    store.award(CHAT, ALICE, 700, ADMIN)
    store.undo_last(CHAT, ADMIN)
    entries = store.history(CHAT, ALICE)
    assert len(entries) == 1
    assert entries[0]["voided"] is True


def test_new_season_zeroes_the_board_but_keeps_history(fresh_db):
    store.award(CHAT, ALICE, 800, ADMIN)
    old, new = store.close_season(CHAT)
    assert (old, new) == (1, 2)
    assert store.balance(CHAT, ALICE) == 0
    assert store.standings(CHAT) == []
    assert store.standings(CHAT, "alltime")[0]["balance"] == 800


def test_peak_balance_remembers_the_high_water_mark(fresh_db):
    store.award(CHAT, ALICE, 1000, ADMIN)
    store.deduct(CHAT, ALICE, 700, ADMIN)
    assert store.balance(CHAT, ALICE) == 300
    assert store.peak_balance(CHAT, ALICE) == 1000


def test_hard_wipe_clears_only_this_chat(fresh_db):
    other = -100888
    store.ensure_chat(other)
    store.award(CHAT, ALICE, 10, ADMIN)
    store.award(other, ALICE, 20, ADMIN)
    store.hard_wipe(CHAT)
    assert store.standings(CHAT) == []
    assert store.balance(other, ALICE) == 20


def test_balance_always_equals_the_sum_of_its_entries(fresh_db):
    """Property test over a random operation sequence."""
    rng = random.Random(20260814)
    expected = 0
    for _ in range(200):
        op = rng.choice(["award", "deduct", "set", "undo"])
        if op == "award":
            amount = rng.randint(1, 5000)
            store.award(CHAT, ALICE, amount, ADMIN)
            expected += amount
        elif op == "deduct":
            amount = rng.randint(1, 5000)
            removed, _ = store.deduct(CHAT, ALICE, amount, ADMIN)
            expected -= removed
        elif op == "set":
            target = rng.randint(0, 10000)
            store.set_balance(CHAT, ALICE, target, ADMIN)
            expected = target
        else:
            result = store.undo_last(CHAT, ADMIN)
            if result is not None:
                expected -= result["delta"]
        assert store.balance(CHAT, ALICE) == expected
        assert expected >= 0
