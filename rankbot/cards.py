"""Assembling everything a rank card shows, in one place.

The renderer receives a finished RankCard and does no lookups of its own, so
there is no shared mutable state between concurrent requests: two members
asking at the same time each get their own value object.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from . import config, levels, store


@dataclass(frozen=True)
class RankCard:
    header: str                  # "MY RANK" / "MEMBER RANK"
    name: str
    user_id: int
    rank: int
    total: int
    cash: int
    recent_delta: int            # cash movement in the rank-change window
    level: int
    level_title: str
    progress: levels.Progress
    rank_change: int | None      # positive = climbed; None = no prior rank
    percentile: int              # "TOP n%"
    joined: datetime | None
    crowned: bool                # rank 1, or a chat admin

    @property
    def next_level(self) -> int:
        return self.progress.next_level


def percentile_for(rank: int, total: int) -> int:
    """'TOP n%'. Rank 4 of 100 is TOP 4%; rank 25 of 500 is TOP 5%.

    Rounded up so the figure is never flattering by rounding, and floored at
    1 so nobody is ever shown TOP 0%.
    """
    if total <= 0:
        return 100
    return max(1, min(100, math.ceil(rank / total * 100)))


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def build(chat_id: int, user_id: int, name: str, *, header: str = "MY RANK",
          is_admin: bool = False) -> RankCard | None:
    """Gather a member's card. None when they have no ranked entries yet."""
    board = store.standings(chat_id)
    total = len(board)
    entry = next((r for r in board if r["user_id"] == user_id), None)
    if entry is None:
        return None

    rank = entry["rank"]
    cash = entry["balance"]

    window = config.RANK_CHANGE_WINDOW_HOURS
    cutoff = store.ago_iso(hours=window)
    previous = store.ranks_as_of(chat_id, "season", cutoff).get(user_id)
    rank_change = (previous - rank) if previous else None

    xp = store.lifetime_xp(chat_id, user_id)
    progress = levels.progress_for_xp(xp)

    return RankCard(
        header=header,
        name=name,
        user_id=user_id,
        rank=rank,
        total=total,
        cash=cash,
        recent_delta=store.window_delta(chat_id, user_id, days=window / 24),
        level=progress.level,
        level_title=levels.title_for_level(progress.level),
        progress=progress,
        rank_change=rank_change,
        percentile=percentile_for(rank, total),
        joined=_parse(store.joined_at(chat_id, user_id)),
        crowned=(rank == 1 or is_admin),
    )
