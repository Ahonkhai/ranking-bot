"""Milestones: cash thresholds, rank positions, and holding the top spot.

An unlock is recorded rather than derived. Everything else in this bot is a
query over the ledger, but "have we already told the group about this?" is not
in the ledger — and re-announcing a milestone every time someone's balance
wobbles across it would be worse than storing one row.

Once earned, an achievement is kept for good: a later deduction, a drop down
the board, or a new season doesn't take it away.
"""

import logging
from dataclasses import dataclass

from . import config, store

log = logging.getLogger("rankbot.achievements")

CASH = "cash"      # value is a balance to reach
RANK = "rank"      # value is a position to reach or better
TENURE = "tenure"  # value is a number of days holding #1


@dataclass(frozen=True)
class Achievement:
    code: str          # stable key; never rename one that's been awarded
    emoji: str
    name: str
    kind: str
    value: int
    rarity: int        # picks the one to announce when several land together
    requirement: str

    def label(self) -> str:
        return f"{self.emoji} {self.name}"


# Codes are what's stored, so emoji, wording, values and rarity can all be
# retuned freely — only the codes are load-bearing.
CASH_TIERS: list[Achievement] = [
    Achievement("first_bag",    "💵",  "First Bag",    CASH, 1_000,     1, "Reach $1,000"),
    Achievement("four_figures", "💰",  "Four Figures", CASH, 5_000,     2, "Reach $5,000"),
    Achievement("high_roller",  "🤑",  "High Roller",  CASH, 10_000,    3, "Reach $10,000"),
    Achievement("big_money",    "💎",  "Big Money",    CASH, 25_000,    4, "Reach $25,000"),
    Achievement("money_maker",  "🏦",  "Money Maker",  CASH, 50_000,    5, "Reach $50,000"),
    Achievement("six_figures",  "👑",  "Six Figures",  CASH, 100_000,   6, "Reach $100,000"),
    Achievement("whale",        "🐋",  "Whale",        CASH, 250_000,   7, "Reach $250,000"),
    Achievement("mega_whale",   "💠",  "Mega Whale",   CASH, 500_000,   8, "Reach $500,000"),
    Achievement("millionaire",  "🏛️", "Millionaire",  CASH, 1_000_000, 9, "Reach $1,000,000"),
]

# Ordered hardest-last. `value` is "this rank or better", so reaching #1 also
# earns everything below it — the same way Whale implies Big Money.
RANK_TIERS: list[Achievement] = [
    Achievement("top_10",     "🥉", "Top 10",     RANK, 10, 3,  "Reach the top 10"),
    Achievement("top_5",      "🥈", "Top 5",      RANK, 5,  5,  "Reach the top 5"),
    Achievement("podium",     "🥇", "Podium",     RANK, 3,  7,  "Reach the top 3"),
    Achievement("challenger", "⚔️", "Challenger", RANK, 2,  8,  "Reach #2"),
    Achievement("number_one", "👑", "Number One", RANK, 1,  11, "Reach #1"),
]

CHAMPION = Achievement(
    "champion", "🏆", "Champion", TENURE, config.CHAMPION_DAYS, 13,
    f"Hold #1 for {config.CHAMPION_DAYS} days",
)

TIERS: list[Achievement] = CASH_TIERS + RANK_TIERS + [CHAMPION]
BY_CODE = {a.code: a for a in TIERS}

# The deepest rank any achievement cares about, so a board sweep can stop early.
DEEPEST_RANK = max(a.value for a in RANK_TIERS)


def earned_at(balance: int) -> list[Achievement]:
    """Every cash tier a balance qualifies for, lowest first."""
    return [a for a in CASH_TIERS if balance >= a.value]


# A rank tier also needs a board big enough for it to mean anything. Without
# this, every member of a four-person chat instantly earns Top 10 and Top 5,
# which is noise rather than an achievement. Two is the floor everywhere: you
# have to have beaten somebody.
def board_requirement(tier: Achievement) -> int:
    return max(2, tier.value)


def earned_at_rank(rank: int | None, total: int) -> list[Achievement]:
    """Every rank tier a position qualifies for. Lower rank number is better."""
    if rank is None:
        return []
    return [a for a in RANK_TIERS
            if rank <= a.value and total >= board_requirement(a)]


def next_tier(balance: int) -> Achievement | None:
    for tier in CASH_TIERS:
        if balance < tier.value:
            return tier
    return None


def next_rank_tier(rank: int | None, total: int = 0) -> Achievement | None:
    """The next rank worth climbing to, skipping tiers this board is too small
    to award."""
    for tier in RANK_TIERS:
        if total < board_requirement(tier):
            continue
        if rank is None or rank > tier.value:
            return tier
    return None


def qualifies(chat_id: int, user_id: int) -> list[Achievement]:
    """Everything this member currently meets the requirement for."""
    earned = earned_at(store.balance(chat_id, user_id))

    rank, total = store.rank_of(chat_id, user_id)
    earned += earned_at_rank(rank, total)

    # Only worth the multi-query tenure check for someone actually on top of a
    # board with somebody else on it.
    if (rank == 1 and total >= 2
            and store.held_rank_since(chat_id, user_id, config.CHAMPION_DAYS)):
        earned.append(CHAMPION)
    return earned


def check(chat_id: int, user_id: int) -> list[Achievement]:
    """Record and return any milestones this member has newly reached.

    Returns several at once when one award vaults multiple tiers — an admin
    running /setcash 300000 on a new member has genuinely earned all of them,
    and silently dropping the ones in between would be wrong. Only the
    headline is announced; the rest show up in /achievements.
    """
    current = qualifies(chat_id, user_id)
    if not current:
        return []

    already = store.recorded_achievements(chat_id, user_id)
    fresh = [a for a in current if a.code not in already]
    if not fresh:
        return []

    store.record_achievements(chat_id, user_id, [a.code for a in fresh],
                              store.balance(chat_id, user_id))
    log.info("chat %s user %s unlocked %s", chat_id, user_id,
             ", ".join(a.code for a in fresh))
    return fresh


def check_board(chat_id: int, skip: int | None = None) -> list[tuple[int, list[Achievement]]]:
    """Sweep the top of the board for newly earned rank milestones.

    A rank can improve without the member's own balance moving — someone above
    them is reset, or overtaken by a third party — so checking only whoever an
    admin just targeted would miss those. Bounded to the deepest rank any
    achievement cares about.
    """
    out = []
    for row in store.standings(chat_id)[:DEEPEST_RANK]:
        if row["user_id"] == skip:
            continue
        unlocked = check(chat_id, row["user_id"])
        if unlocked:
            out.append((row["user_id"], unlocked))
    return out


def headline(unlocked: list[Achievement]) -> Achievement | None:
    """The single tier worth announcing when several unlock at once.

    Picked by rarity rather than by list order, so reaching #1 and $400,000 in
    one stroke leads with Number One — the part anyone in the chat cares about.
    """
    return max(unlocked, key=lambda a: a.rarity, default=None)


def held_by(chat_id: int, user_id: int) -> list[Achievement]:
    """Everything this member has unlocked, easiest first."""
    codes = store.recorded_achievements(chat_id, user_id)
    return sorted((a for a in TIERS if a.code in codes), key=lambda a: a.rarity)
