"""Achievement definitions and unlock logic.

One central registry — no handler decides what an achievement is or when it is
earned. `qualifies()` is the single place that answers "what does this member
currently meet the requirement for", and `check()` is the single place that
records new ones.

An unlock is recorded rather than derived. Everything else in this bot is a
query over the ledger, but "have we already told the group about this?" is not
in the ledger, and a badge has to survive the member later dropping back below
the requirement. Once earned, kept: a deduction, a fall down the board, or a
new season never takes one away.
"""

import logging
from dataclasses import dataclass
from enum import IntEnum

from . import config, levels, store

log = logging.getLogger("rankbot.achievements")

# Requirement kinds.
CASH = "cash"        # balance to reach
RANK = "rank"        # position to reach, or better
TENURE = "tenure"    # days holding #1
STREAK = "streak"    # consecutive active days
LEVEL = "level"      # level to reach
FEAT = "feat"        # one-off events: takeovers, climbs


class Rarity(IntEnum):
    """Ordered, so the rarest unlocked badge is just a max()."""
    COMMON = 0
    RARE = 1
    EPIC = 2
    LEGENDARY = 3
    MYTHIC = 4

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class Achievement:
    code: str          # stable key; never rename one that's been awarded
    name: str
    description: str
    kind: str
    value: int
    rarity: Rarity
    weight: int        # tie-break for "which one to announce", within a rarity

    @property
    def icon(self) -> str:
        """Which drawn glyph represents this on the card.

        Deliberately not an emoji: the render fonts have no colour emoji, and
        a missing glyph would show as a blank box on every tile.
        """
        return {CASH: "coin", RANK: "crown", TENURE: "crown",
                STREAK: "flame", LEVEL: "star", FEAT: "bolt"}.get(self.kind, "star")


def _a(code, name, desc, kind, value, rarity, weight):
    return Achievement(code, name, desc, kind, value, rarity, weight)


CASH_TIERS = [
    _a("first_bag",    "FIRST BAG",    "Reach $1,000",     CASH, 1_000,     Rarity.COMMON,    1),
    _a("four_figures", "FOUR FIGURES", "Reach $5,000",     CASH, 5_000,     Rarity.COMMON,    2),
    _a("high_roller",  "HIGH ROLLER",  "Reach $10,000",    CASH, 10_000,    Rarity.RARE,      3),
    _a("big_money",    "BIG MONEY",    "Reach $25,000",    CASH, 25_000,    Rarity.RARE,      4),
    _a("money_maker",  "MONEY MAKER",  "Reach $50,000",    CASH, 50_000,    Rarity.EPIC,      5),
    _a("six_figures",  "SIX FIGURES",  "Reach $100,000",   CASH, 100_000,   Rarity.EPIC,      6),
    _a("whale",        "WHALE",        "Reach $250,000",   CASH, 250_000,   Rarity.LEGENDARY, 7),
    _a("mega_whale",   "MEGA WHALE",   "Reach $500,000",   CASH, 500_000,   Rarity.LEGENDARY, 8),
    _a("millionaire",  "MILLIONAIRE",  "Reach $1,000,000", CASH, 1_000_000, Rarity.MYTHIC,    9),
]

# `value` is "this rank or better", so reaching #1 also earns everything below.
RANK_TIERS = [
    _a("top_10",     "TOP 10",     "Reach the top 10", RANK, 10, Rarity.COMMON,    1),
    _a("top_5",      "TOP 5",      "Reach the top 5",  RANK, 5,  Rarity.RARE,      2),
    _a("podium",     "PODIUM",     "Reach the top 3",  RANK, 3,  Rarity.EPIC,      3),
    _a("challenger", "CHALLENGER", "Reach #2",         RANK, 2,  Rarity.EPIC,      4),
    # Weighted above the cash badges of the same rarity: taking #1 is the
    # story, and a headline that announced WHALE instead would bury it.
    _a("number_one", "NUMBER ONE", "Reach #1",         RANK, 1,  Rarity.LEGENDARY, 9),
]

# Code stays "champion" — it predates the rename and renaming a code that has
# already been awarded would orphan those unlocks.
KING = _a("champion", "KING", f"Hold #1 for {config.CHAMPION_DAYS} days",
          TENURE, config.CHAMPION_DAYS, Rarity.MYTHIC, 8)

FEATS = [
    _a("climber",     "CLIMBER",     "Climb 5 places",             FEAT, 5,  Rarity.RARE,      2),
    _a("rocket",      "ROCKET",      "Climb 10 places",            FEAT, 10, Rarity.EPIC,      4),
    _a("underdog",    "UNDERDOG",    "Outside the top 20 to the top 10",
                                                                   FEAT, 0,  Rarity.LEGENDARY, 6),
    _a("king_slayer", "KING SLAYER", "Take #1 from the leader",    FEAT, 0,  Rarity.MYTHIC,    9),
]

STREAK_TIERS = [
    _a("getting_started", "GETTING STARTED", "3 day streak",   STREAK, 3,   Rarity.COMMON,    1),
    _a("on_fire",         "ON FIRE",         "7 day streak",   STREAK, 7,   Rarity.RARE,      2),
    _a("unstoppable",     "UNSTOPPABLE",     "14 day streak",  STREAK, 14,  Rarity.EPIC,      3),
    _a("dedicated",       "DEDICATED",       "30 day streak",  STREAK, 30,  Rarity.EPIC,      5),
    _a("relentless",      "RELENTLESS",      "60 day streak",  STREAK, 60,  Rarity.LEGENDARY, 6),
    _a("no_days_off",     "NO DAYS OFF",     "100 day streak", STREAK, 100, Rarity.MYTHIC,    7),
]

LEVEL_TIERS = [
    _a("level_up",    "LEVEL UP",    "Reach level 5",   LEVEL, 5,   Rarity.COMMON,    1),
    _a("experienced", "EXPERIENCED", "Reach level 10",  LEVEL, 10,  Rarity.RARE,      2),
    _a("elite",       "ELITE",       "Reach level 20",  LEVEL, 20,  Rarity.EPIC,      3),
    _a("veteran",     "VETERAN",     "Reach level 30",  LEVEL, 30,  Rarity.EPIC,      4),
    _a("master",      "MASTER",      "Reach level 50",  LEVEL, 50,  Rarity.LEGENDARY, 5),
    _a("legend",      "LEGEND",      "Reach level 100", LEVEL, 100, Rarity.MYTHIC,    6),
]

TIERS = CASH_TIERS + RANK_TIERS + [KING] + FEATS + STREAK_TIERS + LEVEL_TIERS
BY_CODE = {a.code: a for a in TIERS}
TOTAL = len(TIERS)

CHAMPION = KING          # kept for callers that referred to it by the old name
DEEPEST_RANK = max(a.value for a in RANK_TIERS)


# ── requirements ─────────────────────────────────────────────────────────

def board_requirement(tier: Achievement) -> int:
    """A rank tier needs a board big enough for it to mean anything.

    Without this, every member of a four-person chat instantly earns Top 10
    and Top 5. Two is the floor everywhere: you have to have beaten somebody.
    """
    return max(2, tier.value)


def earned_at(balance: int) -> list[Achievement]:
    return [a for a in CASH_TIERS if balance >= a.value]


def earned_at_rank(rank: int | None, total: int) -> list[Achievement]:
    if rank is None:
        return []
    return [a for a in RANK_TIERS
            if rank <= a.value and total >= board_requirement(a)]


def earned_at_streak(days: int) -> list[Achievement]:
    return [a for a in STREAK_TIERS if days >= a.value]


def earned_at_level(level: int) -> list[Achievement]:
    return [a for a in LEVEL_TIERS if level >= a.value]


def earned_feats(chat_id: int, user_id: int, rank: int | None, total: int) -> list[Achievement]:
    """One-off events, judged against where this member stood a day ago."""
    if rank is None or total < 2:
        return []

    hours = config.RANK_CHANGE_WINDOW_HOURS
    then, now = store.rank_movement(chat_id, user_id, hours)
    out = []

    # King slayer is judged on the throne, not on the climb: arriving from
    # nowhere and taking #1 still dethrones somebody, so it must not depend on
    # the slayer having been ranked yesterday.
    if now == 1:
        previous = store.leader_as_of(chat_id, hours)
        if previous is not None and previous != user_id:
            out.append(BY_CODE["king_slayer"])

    # The climbing feats measure a distance, so they need both ends of it.
    if then is None or now is None:
        return out
    climbed = then - now
    if climbed >= 5 and total >= 6:
        out.append(BY_CODE["climber"])
    if climbed >= 10 and total >= 11:
        out.append(BY_CODE["rocket"])
    if then > 20 and now <= 10 and total >= 21:
        out.append(BY_CODE["underdog"])
    return out


def qualifies(chat_id: int, user_id: int) -> list[Achievement]:
    """Everything this member currently meets the requirement for."""
    balance = store.balance(chat_id, user_id)
    rank, total = store.rank_of(chat_id, user_id)
    level = levels.level_for_xp(store.lifetime_xp(chat_id, user_id))

    earned = earned_at(balance)
    earned += earned_at_rank(rank, total)
    earned += earned_at_level(level)
    earned += earned_at_streak(store.activity_streak(chat_id, user_id))
    earned += earned_feats(chat_id, user_id, rank, total)

    # Only worth the multi-query tenure check for someone actually on top.
    if (rank == 1 and total >= 2
            and store.held_rank_since(chat_id, user_id, config.CHAMPION_DAYS)):
        earned.append(KING)
    return earned


# ── recording ────────────────────────────────────────────────────────────

def check(chat_id: int, user_id: int) -> list[Achievement]:
    """Record and return any milestones this member has newly reached."""
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
    admin just targeted would miss those.
    """
    out = []
    for row in store.standings(chat_id)[:DEEPEST_RANK]:
        if row["user_id"] == skip:
            continue
        unlocked = check(chat_id, row["user_id"])
        if unlocked:
            out.append((row["user_id"], unlocked))
    return out


# ── reading ──────────────────────────────────────────────────────────────

def headline(unlocked: list[Achievement]) -> Achievement | None:
    """The single one worth announcing when several land together — rarest
    first, so taking #1 leads over the cash tier that came with it."""
    return max(unlocked, key=lambda a: (a.rarity, a.weight), default=None)


def held_by(chat_id: int, user_id: int) -> list[Achievement]:
    codes = store.recorded_achievements(chat_id, user_id)
    return [a for a in TIERS if a.code in codes]


def rarest(unlocked: list[Achievement]) -> Achievement | None:
    return headline(unlocked)


def next_tier(balance: int) -> Achievement | None:
    for tier in CASH_TIERS:
        if balance < tier.value:
            return tier
    return None


def next_rank_tier(rank: int | None, total: int = 0) -> Achievement | None:
    for tier in RANK_TIERS:
        if total < board_requirement(tier):
            continue
        if rank is None or rank > tier.value:
            return tier
    return None


def progress(chat_id: int, user_id: int) -> tuple[int, int]:
    """(unlocked, total) for the completion bar."""
    return len(store.recorded_achievements(chat_id, user_id) & set(BY_CODE)), TOTAL
