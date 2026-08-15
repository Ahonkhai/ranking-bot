"""Cash milestones.

An unlock is recorded rather than derived. Everything else in this bot is a
query over the ledger, but "have we already told the group about this?" is not
in the ledger — and re-announcing a milestone every time someone's balance
wobbles across it would be worse than storing one row.

Once earned, an achievement is kept for good: a later deduction or a new
season doesn't take it away.
"""

import logging
from dataclasses import dataclass

from . import store

log = logging.getLogger("rankbot.achievements")


@dataclass(frozen=True)
class Achievement:
    code: str          # stable key; never rename one that's been awarded
    emoji: str
    name: str
    threshold: int

    def label(self) -> str:
        return f"{self.emoji} {self.name}"


# Ordered by threshold. Codes are what's stored, so the emoji and wording can
# be retuned freely — only the codes are load-bearing.
TIERS: list[Achievement] = [
    Achievement("first_bag",    "💵",  "First Bag",    1_000),
    Achievement("four_figures", "💰",  "Four Figures", 5_000),
    Achievement("high_roller",  "🤑",  "High Roller",  10_000),
    Achievement("big_money",    "💎",  "Big Money",    25_000),
    Achievement("money_maker",  "🏦",  "Money Maker",  50_000),
    Achievement("six_figures",  "👑",  "Six Figures",  100_000),
    Achievement("whale",        "🐋",  "Whale",        250_000),
    Achievement("mega_whale",   "💠",  "Mega Whale",   500_000),
    Achievement("millionaire",  "🏛️", "Millionaire",  1_000_000),
]

BY_CODE = {a.code: a for a in TIERS}


def earned_at(balance: int) -> list[Achievement]:
    """Every tier a balance qualifies for, lowest first."""
    return [a for a in TIERS if balance >= a.threshold]


def next_tier(balance: int) -> Achievement | None:
    for tier in TIERS:
        if balance < tier.threshold:
            return tier
    return None


def check(chat_id: int, user_id: int) -> list[Achievement]:
    """Record and return any milestones this member has newly reached.

    Returns several at once when one award vaults multiple tiers — an admin
    running /setcash 300000 on a new member has genuinely earned all of them,
    and silently dropping the ones in between would be wrong.
    """
    balance = store.balance(chat_id, user_id)
    qualifies = earned_at(balance)
    if not qualifies:
        return []

    already = store.recorded_achievements(chat_id, user_id)
    fresh = [a for a in qualifies if a.code not in already]
    if not fresh:
        return []

    store.record_achievements(chat_id, user_id, [a.code for a in fresh], balance)
    log.info("chat %s user %s unlocked %s", chat_id, user_id,
             ", ".join(a.code for a in fresh))
    return fresh


def held_by(chat_id: int, user_id: int) -> list[Achievement]:
    """Everything this member has unlocked, in tier order."""
    codes = store.recorded_achievements(chat_id, user_id)
    return [a for a in TIERS if a.code in codes]
