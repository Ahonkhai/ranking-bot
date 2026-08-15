"""XP, levels and member titles.

XP is not a second currency to keep in sync with cash — it is the lifetime sum
of everything a member has ever been awarded, read straight off the ledger.
That makes it monotonic by construction (cash can be spent or deducted, XP
never goes backwards) and means levels needed no new storage at all.

Everything here is driven by the constants at the top, so the curve and the
titles can be retuned without touching the renderer.
"""

import bisect
from dataclasses import dataclass

from . import config

# ── the curve ────────────────────────────────────────────────────────────
# Cumulative XP needed to *reach* a level:
#     f(L) = LINEAR * (L-1) + QUADRATIC * (L-1)^2
# Linear early on so the first levels come quickly, quadratic later so the
# top of the board stays hard to reach.

MAX_LEVEL = 200


def cumulative_xp_for_level(level: int) -> int:
    """Total lifetime XP required to reach `level`. Level 1 is always 0."""
    n = max(0, level - 1)
    return int(config.XP_LINEAR * n + config.XP_QUADRATIC * n * n)


def xp_required_for_level(level: int) -> int:
    """XP needed to get from the previous level to `level`."""
    if level <= 1:
        return 0
    return cumulative_xp_for_level(level) - cumulative_xp_for_level(level - 1)


def _thresholds() -> list[int]:
    """Cached ladder of cumulative thresholds, rebuilt if the curve changes."""
    key = (config.XP_LINEAR, config.XP_QUADRATIC)
    cached = getattr(_thresholds, "_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    ladder = [cumulative_xp_for_level(lv) for lv in range(1, MAX_LEVEL + 2)]
    _thresholds._cache = (key, ladder)
    return ladder


def level_for_xp(xp: int) -> int:
    """Highest level whose cumulative requirement `xp` satisfies.

    Bisection over the ladder rather than an algebraic inverse, so retuning
    the curve — even to a non-quadratic one — needs no matching maths here.
    """
    xp = max(0, int(xp))
    ladder = _thresholds()
    idx = bisect.bisect_right(ladder, xp)
    return max(1, min(idx, MAX_LEVEL))


# ── titles ───────────────────────────────────────────────────────────────
# (minimum level, title). Kept sorted; edit freely.
TITLES: list[tuple[int, str]] = [
    (1,  "Newcomer"),
    (5,  "Rising Member"),
    (10, "Established Member"),
    (20, "Elite Member"),
    (30, "Veteran"),
    (50, "Legend"),
]


def title_for_level(level: int) -> str:
    title = TITLES[0][1]
    for minimum, name in TITLES:
        if level >= minimum:
            title = name
        else:
            break
    return title


# ── progress ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Progress:
    """Everything the XP panel needs, already resolved."""
    xp: int             # lifetime XP
    level: int
    next_level: int
    earned: int         # XP counted by the bar
    needed: int         # XP the bar fills to
    fraction: float     # 0.0 - 1.0
    at_max: bool

    @property
    def percent(self) -> int:
        return int(round(self.fraction * 100))


def progress_for_xp(xp: int) -> Progress:
    """Where a member sits between their current level and the next.

    By default the bar measures progress *within* the current level, so it
    starts empty at every level-up and the two numbers under it are the same
    pair the percentage is computed from. Set XP_BAR_CUMULATIVE=1 to show
    lifetime XP against the next level's total requirement instead.
    """
    xp = max(0, int(xp))
    level = level_for_xp(xp)

    if level >= MAX_LEVEL:
        return Progress(xp, level, level, xp, xp, 1.0, True)

    next_level = level + 1
    if config.XP_BAR_CUMULATIVE:
        earned, needed = xp, cumulative_xp_for_level(next_level)
    else:
        floor = cumulative_xp_for_level(level)
        earned = xp - floor
        needed = cumulative_xp_for_level(next_level) - floor

    fraction = 0.0 if needed <= 0 else max(0.0, min(1.0, earned / needed))
    return Progress(xp, level, next_level, earned, needed, fraction, False)
