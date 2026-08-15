"""Cash milestones.

The interesting cases aren't "does it fire" — they're the ones where it must
*not* fire again, and the ones where a single award crosses several tiers.
"""

from rankbot import achievements, store
from tests.conftest import CHAT

ADMIN = 111
ALICE = 222


def codes(unlocked):
    return [a.code for a in unlocked]


def test_tiers_are_ordered_and_unique():
    thresholds = [a.threshold for a in achievements.TIERS]
    assert thresholds == sorted(thresholds)
    assert len(set(a.code for a in achievements.TIERS)) == len(achievements.TIERS)


def test_nothing_unlocks_below_the_first_tier(fresh_db):
    store.award(CHAT, ALICE, 999, ADMIN)
    assert achievements.check(CHAT, ALICE) == []


def test_crossing_a_threshold_unlocks_it(fresh_db):
    store.award(CHAT, ALICE, 1_000, ADMIN)
    assert codes(achievements.check(CHAT, ALICE)) == ["first_bag"]


def test_a_milestone_announces_exactly_once(fresh_db):
    store.award(CHAT, ALICE, 1_000, ADMIN)
    assert codes(achievements.check(CHAT, ALICE)) == ["first_bag"]
    # Same balance, and again after more cash below the next tier.
    assert achievements.check(CHAT, ALICE) == []
    store.award(CHAT, ALICE, 500, ADMIN)
    assert achievements.check(CHAT, ALICE) == []


def test_one_award_can_unlock_several_tiers(fresh_db):
    """An admin setting a new member to 300k has genuinely earned every tier
    below it; silently dropping the ones in between would be wrong."""
    store.set_balance(CHAT, ALICE, 300_000, ADMIN)
    unlocked = codes(achievements.check(CHAT, ALICE))
    assert unlocked == ["first_bag", "four_figures", "high_roller", "big_money",
                        "money_maker", "six_figures", "whale"]
    assert achievements.check(CHAT, ALICE) == []


def test_dropping_below_and_climbing_back_does_not_re_announce(fresh_db):
    store.award(CHAT, ALICE, 10_000, ADMIN)
    achievements.check(CHAT, ALICE)
    store.deduct(CHAT, ALICE, 9_500, ADMIN)
    assert achievements.check(CHAT, ALICE) == []
    store.award(CHAT, ALICE, 9_500, ADMIN)
    assert achievements.check(CHAT, ALICE) == []


def test_an_undone_award_does_not_re_announce_when_re_earned(fresh_db):
    store.award(CHAT, ALICE, 5_000, ADMIN)
    achievements.check(CHAT, ALICE)
    store.undo_last(CHAT, ADMIN)
    assert store.balance(CHAT, ALICE) == 0
    store.award(CHAT, ALICE, 5_000, ADMIN)
    assert achievements.check(CHAT, ALICE) == []


def test_achievements_survive_a_new_season(fresh_db):
    """Balances reset with the season; badges are for good."""
    store.award(CHAT, ALICE, 25_000, ADMIN)
    achievements.check(CHAT, ALICE)
    store.close_season(CHAT)
    assert store.balance(CHAT, ALICE) == 0
    assert len(achievements.held_by(CHAT, ALICE)) == 4
    assert achievements.check(CHAT, ALICE) == []


def test_achievements_are_per_chat(fresh_db):
    other = -100777
    store.ensure_chat(other)
    store.award(CHAT, ALICE, 1_000, ADMIN)
    achievements.check(CHAT, ALICE)
    store.award(other, ALICE, 1_000, ADMIN)
    assert codes(achievements.check(other, ALICE)) == ["first_bag"]


def test_held_by_is_in_tier_order(fresh_db):
    store.set_balance(CHAT, ALICE, 60_000, ADMIN)
    achievements.check(CHAT, ALICE)
    held = achievements.held_by(CHAT, ALICE)
    assert codes(held) == ["first_bag", "four_figures", "high_roller",
                           "big_money", "money_maker"]


def test_next_tier_points_at_the_climb(fresh_db):
    assert achievements.next_tier(0).code == "first_bag"
    assert achievements.next_tier(1_000).code == "four_figures"
    assert achievements.next_tier(999_999).code == "millionaire"
    assert achievements.next_tier(1_000_000) is None


def test_earned_at_boundaries():
    assert achievements.earned_at(999) == []
    assert codes(achievements.earned_at(1_000)) == ["first_bag"]
    assert len(achievements.earned_at(10_000_000)) == len(achievements.TIERS)


def test_recording_is_idempotent(fresh_db):
    """The primary key is what makes a double-award impossible even if two
    writes race."""
    store.award(CHAT, ALICE, 1_000, ADMIN)
    store.record_achievements(CHAT, ALICE, ["first_bag"], 1_000)
    store.record_achievements(CHAT, ALICE, ["first_bag"], 5_000)
    assert store.recorded_achievements(CHAT, ALICE) == {"first_bag"}
    assert len(store.achievement_log(CHAT, ALICE)) == 1


def test_the_log_records_what_they_held_at_the_time(fresh_db):
    store.award(CHAT, ALICE, 7_500, ADMIN)
    achievements.check(CHAT, ALICE)
    entries = store.achievement_log(CHAT, ALICE)
    assert [e["code"] for e in entries] == ["first_bag", "four_figures"]
    assert all(e["balance_at"] == 7_500 for e in entries)
