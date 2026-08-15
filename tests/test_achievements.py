"""Milestones: cash, rank, and holding the top spot.

The interesting cases aren't "does it fire" — they're the ones where it must
*not* fire again, the ones where one award crosses several tiers, and the ones
where a board is too small for a rank to mean anything.
"""

from rankbot import achievements, config, store
from tests.conftest import CHAT

ADMIN = 111
ALICE = 222
BOB = 333


def codes(unlocked):
    return [a.code for a in unlocked]


def cash_codes(unlocked):
    return [a.code for a in unlocked if a.kind == achievements.CASH]


def crowd(n, base=1000):
    """A board of n members, ALICE excluded, so ranks are meaningful."""
    for i in range(n):
        store.award(CHAT, 9000 + i, base + i, ADMIN, "crowd")


# ── shape ────────────────────────────────────────────────────────────────

def test_codes_are_unique_and_cash_tiers_ordered():
    assert len(set(a.code for a in achievements.TIERS)) == len(achievements.TIERS)
    values = [a.value for a in achievements.CASH_TIERS]
    assert values == sorted(values)


def test_rank_tiers_get_harder():
    values = [a.value for a in achievements.RANK_TIERS]
    assert values == sorted(values, reverse=True)


# ── cash ─────────────────────────────────────────────────────────────────

def test_nothing_unlocks_below_the_first_tier(fresh_db):
    store.award(CHAT, ALICE, 999, ADMIN)
    assert cash_codes(achievements.check(CHAT, ALICE)) == []


def test_crossing_a_threshold_unlocks_it(fresh_db):
    store.award(CHAT, ALICE, 1_000, ADMIN)
    assert cash_codes(achievements.check(CHAT, ALICE)) == ["first_bag"]


def test_a_milestone_announces_exactly_once(fresh_db):
    store.award(CHAT, ALICE, 1_000, ADMIN)
    achievements.check(CHAT, ALICE)
    assert achievements.check(CHAT, ALICE) == []
    store.award(CHAT, ALICE, 500, ADMIN)
    assert achievements.check(CHAT, ALICE) == []


def test_one_award_can_unlock_several_tiers(fresh_db):
    store.set_balance(CHAT, ALICE, 300_000, ADMIN)
    assert cash_codes(achievements.check(CHAT, ALICE)) == [
        "first_bag", "four_figures", "high_roller", "big_money",
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
    store.award(CHAT, ALICE, 5_000, ADMIN)
    assert achievements.check(CHAT, ALICE) == []


def test_achievements_survive_a_new_season(fresh_db):
    store.award(CHAT, ALICE, 25_000, ADMIN)
    achievements.check(CHAT, ALICE)
    store.close_season(CHAT)
    assert store.balance(CHAT, ALICE) == 0
    assert len(achievements.held_by(CHAT, ALICE)) >= 4
    assert achievements.check(CHAT, ALICE) == []


def test_achievements_are_per_chat(fresh_db):
    other = -100777
    store.ensure_chat(other)
    store.award(CHAT, ALICE, 1_000, ADMIN)
    achievements.check(CHAT, ALICE)
    store.award(other, ALICE, 1_000, ADMIN)
    assert cash_codes(achievements.check(other, ALICE)) == ["first_bag"]


def test_earned_at_boundaries():
    assert achievements.earned_at(999) == []
    assert codes(achievements.earned_at(1_000)) == ["first_bag"]
    assert len(achievements.earned_at(10_000_000)) == len(achievements.CASH_TIERS)


# ── rank ─────────────────────────────────────────────────────────────────

def test_a_lone_member_earns_no_rank_achievement(fresh_db):
    """Being #1 of one is not an achievement."""
    store.award(CHAT, ALICE, 5_000, ADMIN)
    assert [a.code for a in achievements.check(CHAT, ALICE)
            if a.kind == achievements.RANK] == []


def test_a_small_board_cannot_award_top_ten(fresh_db):
    """Otherwise every member of a four-person chat instantly gets Top 10."""
    store.award(CHAT, ALICE, 9_999, ADMIN)
    crowd(3)
    earned = [a.code for a in achievements.check(CHAT, ALICE)
              if a.kind == achievements.RANK]
    assert earned == ["podium", "challenger", "number_one"]
    assert "top_10" not in earned and "top_5" not in earned


def test_a_big_board_awards_the_whole_rank_ladder(fresh_db):
    crowd(12)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    earned = [a.code for a in achievements.check(CHAT, ALICE)
              if a.kind == achievements.RANK]
    assert earned == ["top_10", "top_5", "podium", "challenger", "number_one"]


def test_mid_board_earns_only_what_it_reached(fresh_db):
    crowd(12)                       # balances 1000..1011
    store.award(CHAT, ALICE, 1_006, ADMIN)   # lands mid-table
    rank, total = store.rank_of(CHAT, ALICE)
    assert total == 13
    earned = [a.code for a in achievements.check(CHAT, ALICE)
              if a.kind == achievements.RANK]
    assert earned == ["top_10"] if rank <= 10 else earned == []


def test_a_rank_achievement_survives_being_overtaken(fresh_db):
    crowd(12)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    achievements.check(CHAT, ALICE)
    held_before = codes(achievements.held_by(CHAT, ALICE))

    store.award(CHAT, BOB, 900_000, ADMIN)          # ALICE drops to #2
    assert store.rank_of(CHAT, ALICE)[0] == 2
    assert achievements.check(CHAT, ALICE) == []     # nothing new, nothing lost
    assert codes(achievements.held_by(CHAT, ALICE)) == held_before


def test_climbing_by_someone_elses_reset_is_caught_by_the_sweep(fresh_db):
    """A rank can improve without the member's own balance moving, so checking
    only whoever an admin targeted would miss it."""
    crowd(12)
    store.award(CHAT, BOB, 900_000, ADMIN)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    achievements.check(CHAT, ALICE)
    achievements.check(CHAT, BOB)
    assert "number_one" not in codes(achievements.held_by(CHAT, ALICE))

    store.set_balance(CHAT, BOB, 0, ADMIN)           # ALICE is now #1
    swept = dict(achievements.check_board(CHAT))
    assert ALICE in swept
    assert "number_one" in codes(swept[ALICE])


def test_the_sweep_skips_the_member_already_announced(fresh_db):
    crowd(12)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    assert ALICE not in dict(achievements.check_board(CHAT, skip=ALICE))


def test_next_rank_tier_skips_what_the_board_is_too_small_for(fresh_db):
    # A three-person board can never award Top 10 or Top 5, so the next real
    # goal is the podium.
    assert achievements.next_rank_tier(5, total=3).code == "podium"
    # At rank 7 of 12, Top 10 is already held and Top 5 is the climb.
    assert achievements.next_rank_tier(7, total=12).code == "top_5"
    # At rank 5 of 12, Top 5 is held too — next is the podium.
    assert achievements.next_rank_tier(5, total=12).code == "podium"
    assert achievements.next_rank_tier(1, total=12) is None


# ── champion ─────────────────────────────────────────────────────────────

def test_champion_needs_the_full_window(fresh_db):
    crowd(3)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    assert "champion" not in codes(achievements.check(CHAT, ALICE))


def test_champion_unlocks_after_holding_number_one(fresh_db, monkeypatch):
    crowd(3)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    # Age every entry so ALICE has been top for longer than the window.
    old = store.ago_iso(days=config.CHAMPION_DAYS + 2)
    with store.db.write() as c:
        c.execute("UPDATE ledger SET created_at=?", (old,))
    assert "champion" in codes(achievements.check(CHAT, ALICE))


def test_champion_is_denied_to_someone_who_only_just_took_the_lead(fresh_db):
    crowd(3)
    store.award(CHAT, BOB, 500_000, ADMIN)
    with store.db.write() as c:
        c.execute("UPDATE ledger SET created_at=?",
                  (store.ago_iso(days=config.CHAMPION_DAYS + 2),))
    store.award(CHAT, ALICE, 900_000, ADMIN)     # takes over today
    assert "champion" not in codes(achievements.check(CHAT, ALICE))


def test_held_rank_since_is_false_on_a_young_board(fresh_db):
    crowd(3)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    assert store.held_rank_since(CHAT, ALICE, days=config.CHAMPION_DAYS) is False


# ── announcing ───────────────────────────────────────────────────────────

def test_only_the_highest_tier_is_announced(fresh_db):
    store.set_balance(CHAT, ALICE, 400_000, ADMIN)
    unlocked = achievements.check(CHAT, ALICE)
    assert len(unlocked) == 7
    assert achievements.headline(unlocked).code == "whale"


def test_rank_leads_over_cash_when_both_land_together(fresh_db):
    """Becoming #1 is the story; the cash tier is a footnote."""
    crowd(12)
    store.set_balance(CHAT, ALICE, 400_000, ADMIN)
    assert achievements.headline(achievements.check(CHAT, ALICE)).code == "number_one"


def test_headline_of_nothing_is_none():
    assert achievements.headline([]) is None


def test_the_quieter_tiers_are_still_held(fresh_db):
    """Not announcing them must not mean not awarding them."""
    crowd(12)
    store.set_balance(CHAT, ALICE, 400_000, ADMIN)
    achievements.check(CHAT, ALICE)
    held = codes(achievements.held_by(CHAT, ALICE))
    assert "whale" in held and "top_10" in held and "number_one" in held


def test_recording_is_idempotent(fresh_db):
    store.award(CHAT, ALICE, 1_000, ADMIN)
    store.record_achievements(CHAT, ALICE, ["first_bag"], 1_000)
    store.record_achievements(CHAT, ALICE, ["first_bag"], 5_000)
    assert store.recorded_achievements(CHAT, ALICE) == {"first_bag"}
    assert len(store.achievement_log(CHAT, ALICE)) == 1


def test_held_by_is_ordered_easiest_first(fresh_db):
    crowd(12)
    store.set_balance(CHAT, ALICE, 400_000, ADMIN)
    achievements.check(CHAT, ALICE)
    rarities = [a.rarity for a in achievements.held_by(CHAT, ALICE)]
    assert rarities == sorted(rarities)


def test_the_sweep_still_awards_even_though_it_stays_quiet(fresh_db):
    """The 'Also unlocked' message was removed as noise, but the badges behind
    it must still be granted — otherwise climbing by someone else's reset
    silently earns nothing at all."""
    crowd(12)
    store.award(CHAT, BOB, 900_000, ADMIN)
    store.award(CHAT, ALICE, 500_000, ADMIN)
    achievements.check(CHAT, ALICE)
    achievements.check(CHAT, BOB)

    store.set_balance(CHAT, BOB, 0, ADMIN)      # ALICE inherits #1
    achievements.check_board(CHAT, skip=BOB)
    assert "number_one" in codes(achievements.held_by(CHAT, ALICE))
