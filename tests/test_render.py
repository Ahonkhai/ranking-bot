"""Render smoke tests.

Not pixel-for-pixel comparisons — those break on every Pillow point release.
These assert the things that actually broke in practice: that a render
completes for awkward input, that the output is a real PNG, that the band
layout adds up to the height it should, and that gradient memoization holds.
"""

from io import BytesIO

from PIL import Image

import rankbot.render.board as board
from rankbot.render import make_leaderboard_image
from rankbot.render import primitives

TITLES = ["Newcomer", "Rising Member", "Elite Member", "Veteran", "Legend"]


def rows(n, start=1):
    return [
        {"rank": start + i, "user_id": 1000 + i, "name": f"@member{i:02d}",
         "balance": 10_000 - i * 137, "title": TITLES[i % len(TITLES)]}
        for i in range(n)
    ]


def expected_height(page_rows, you=None) -> int:
    """Mirror of the band stack in make_leaderboard_image, in real pixels."""
    podium = [r for r in page_rows if r["rank"] <= 3]
    listed = [r for r in page_rows if r["rank"] > 3]
    h = board.FRAME + board.HEADER_H
    if podium:
        h += board.PODIUM_H
    if listed:
        h += board.GAP + board.IPAD + board.COL_H + len(listed) * board.ROW_H + board.IPAD
    if you:
        h += board.GAP + board.YOU_H
    h += board.GAP + board.FOOTER_H + board.FRAME
    return h // board.S


def open_png(buf: BytesIO) -> Image.Image:
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    assert img.format == "PNG"
    return img


def test_leaderboard_renders_at_the_expected_size():
    board_rows = rows(15)
    img = open_png(make_leaderboard_image(board_rows, total=15))
    assert img.width == 720
    # header + podium (ranks 1-3) + list of 12 + footer
    assert img.height == expected_height(board_rows)


def test_the_top_three_form_a_podium_that_makes_page_one_taller():
    """Page one carries the podium band; a later page of the same size doesn't."""
    page1 = open_png(make_leaderboard_image(rows(15), total=70))
    page3 = open_png(make_leaderboard_image(rows(15, start=31), page=3, pages=5, total=70))
    assert page1.height > page3.height
    assert page3.height == expected_height(rows(15, start=31))


def test_leaderboard_grows_for_the_you_are_here_strip():
    base = rows(5, start=20)
    plain = open_png(make_leaderboard_image(base, total=40))
    with_you = open_png(make_leaderboard_image(
        base, total=40,
        you={"rank": 37, "name": "@straggler", "balance": 12,
             "note": "88 BEHIND @x", "title": "Newcomer"}))
    assert with_you.height == plain.height + (board.GAP + board.YOU_H) // board.S


def test_a_partial_top_three_still_renders():
    """A board with only two members shows a two-person podium and no list."""
    img = open_png(make_leaderboard_image(rows(2), total=2))
    assert img.width == 720
    assert img.height == expected_height(rows(2))


def test_leaderboard_survives_hostile_names():
    """These are the names that used to make Telegram reject the send; they
    must also not break the renderer."""
    hostile = [
        {"rank": 1, "user_id": 1, "name": "the_real_dave", "balance": 100},
        {"rank": 2, "user_id": 2, "name": "*bossman*", "balance": 90},
        {"rank": 3, "user_id": 3, "name": "[bracket]", "balance": 80},
        {"rank": 4, "user_id": 4, "name": "<script>alert(1)</script>", "balance": 70},
        {"rank": 5, "user_id": 5, "name": "🐍🔥 emoji name", "balance": 60},
        {"rank": 6, "user_id": 6, "name": "A" * 120, "balance": 50, "title": "Legend"},
        {"rank": 7, "user_id": 7, "name": "", "balance": 40},
    ]
    img = open_png(make_leaderboard_image(hostile, total=7))
    assert img.width == 720


def test_leaderboard_draws_movement_arrows():
    movement = {1003: 3, 1004: -2}
    img = open_png(make_leaderboard_image(rows(6), total=6, movement=movement))
    assert img.width == 720


def test_empty_board_still_produces_an_image():
    img = open_png(make_leaderboard_image([], total=0))
    assert img.width == 720
    assert img.height == expected_height([])


def test_gradients_are_memoized_within_a_render():
    """A board asks for the same small ramps many times over."""
    primitives._metal_column.cache_clear()
    primitives._metal_full.cache_clear()
    primitives.gradient_text_img.cache_clear()
    make_leaderboard_image(rows(15), total=15)
    info = primitives._metal_full.cache_info()
    assert info.hits > info.misses, info


def test_an_identical_re_render_builds_no_new_gradients():
    board_rows = rows(15)
    make_leaderboard_image(board_rows, total=15)
    before = primitives._metal_column.cache_info().misses
    make_leaderboard_image(board_rows, total=15)
    assert primitives._metal_column.cache_info().misses == before


def test_fit_text_truncates_to_width():
    font = primitives.get_font(20, bold=True)
    long_name = "an extremely long display name that will never fit"
    fitted = primitives.fit_text(long_name, font, 120)
    assert fitted.endswith("…")
    assert primitives.text_size(font, fitted)[0] <= 120
    # A short name is returned untouched.
    assert primitives.fit_text("short", font, 400) == "short"
