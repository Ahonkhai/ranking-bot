"""XP curve, levels, titles, and the percentile maths."""

import pytest

from rankbot import cards, config, levels


def test_level_one_starts_at_zero_xp():
    assert levels.cumulative_xp_for_level(1) == 0
    assert levels.level_for_xp(0) == 1
    assert levels.level_for_xp(-500) == 1      # never below level 1


def test_the_curve_is_strictly_increasing():
    previous = -1
    for level in range(1, 60):
        current = levels.cumulative_xp_for_level(level)
        assert current > previous
        previous = current


def test_each_level_costs_more_than_the_last():
    gaps = [levels.xp_required_for_level(lv) for lv in range(2, 30)]
    assert gaps == sorted(gaps)
    assert levels.xp_required_for_level(1) == 0


def test_level_for_xp_matches_its_own_thresholds():
    for level in range(1, 60):
        floor = levels.cumulative_xp_for_level(level)
        assert levels.level_for_xp(floor) == level
        assert levels.level_for_xp(floor - 1) == level - 1 or level == 1


def test_titles_follow_the_configured_bands():
    assert levels.title_for_level(1) == "Newcomer"
    assert levels.title_for_level(4) == "Newcomer"
    assert levels.title_for_level(5) == "Rising Member"
    assert levels.title_for_level(12) == "Established Member"
    assert levels.title_for_level(21) == "Elite Member"
    assert levels.title_for_level(35) == "Veteran"
    assert levels.title_for_level(500) == "Legend"


def test_progress_within_a_level_starts_empty_and_fills():
    floor = levels.cumulative_xp_for_level(10)
    need = levels.xp_required_for_level(11)

    at_floor = levels.progress_for_xp(floor)
    assert at_floor.level == 10
    assert at_floor.next_level == 11
    assert at_floor.earned == 0
    assert at_floor.percent == 0

    halfway = levels.progress_for_xp(floor + need // 2)
    assert 45 <= halfway.percent <= 55

    almost = levels.progress_for_xp(floor + need - 1)
    assert almost.level == 10
    assert almost.percent >= 95


def test_the_bar_numbers_are_the_ones_the_percentage_uses():
    """Whatever the mode, the two figures under the bar must be the ratio the
    percentage is computed from, or the card contradicts itself."""
    for xp in (0, 1_500, 33_333, 250_000):
        p = levels.progress_for_xp(xp)
        if p.needed:
            assert p.percent == int(round(p.earned / p.needed * 100))


def test_cumulative_bar_mode(monkeypatch):
    monkeypatch.setattr(config, "XP_BAR_CUMULATIVE", True)
    floor = levels.cumulative_xp_for_level(10)
    p = levels.progress_for_xp(floor)
    assert p.earned == floor
    assert p.needed == levels.cumulative_xp_for_level(11)
    assert p.percent > 0            # cumulative bars are never empty


def test_max_level_is_clamped():
    p = levels.progress_for_xp(10 ** 12)
    assert p.at_max
    assert p.level == levels.MAX_LEVEL
    assert p.fraction == 1.0


def test_retuning_the_curve_takes_effect(monkeypatch):
    baseline = levels.level_for_xp(10_000)
    monkeypatch.setattr(config, "XP_LINEAR", 50)
    monkeypatch.setattr(config, "XP_QUADRATIC", 5)
    assert levels.level_for_xp(10_000) > baseline


# ── percentile ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("rank,total,expected", [
    (4, 100, 4),
    (25, 500, 5),
    (1, 1, 100),
    (1, 1000, 1),
    (100, 100, 100),
    (50, 100, 50),
])
def test_percentile(rank, total, expected):
    assert cards.percentile_for(rank, total) == expected


def test_percentile_never_reports_zero():
    assert cards.percentile_for(1, 10_000) == 1


def test_percentile_on_an_empty_board():
    assert cards.percentile_for(1, 0) == 100
