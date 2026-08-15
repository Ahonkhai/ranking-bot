"""Render smoke tests.

Not pixel-for-pixel comparisons — those break on every Pillow point release.
These assert the things that actually broke in practice: that a render
completes for awkward input, that the output is a real PNG of the expected
shape, and that the gradient memoization is doing its job.
"""

from io import BytesIO

from PIL import Image

from rankbot.render import make_leaderboard_image
from rankbot.render import primitives


def rows(n, start=1):
    return [
        {"rank": start + i, "user_id": 1000 + i,
         "name": f"@member{i:02d}", "balance": 10_000 - i * 137}
        for i in range(n)
    ]


def open_png(buf: BytesIO) -> Image.Image:
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    assert img.format == "PNG"
    return img


def test_leaderboard_renders_at_the_expected_size():
    img = open_png(make_leaderboard_image(rows(15), total=15))
    assert img.width == 720
    # header + 15 rows + footer, no "you" strip
    assert img.height == 104 + 15 * 72 + 58


def test_leaderboard_grows_for_the_you_are_here_strip():
    plain = open_png(make_leaderboard_image(rows(5), total=40))
    with_you = open_png(make_leaderboard_image(
        rows(5), total=40,
        you={"rank": 37, "name": "@straggler", "balance": 12, "note": "88 BEHIND @x"}))
    assert with_you.height == plain.height + 66


def test_leaderboard_handles_a_later_page():
    img = open_png(make_leaderboard_image(rows(15, start=31), page=3, pages=5, total=70))
    assert img.height == 104 + 15 * 72 + 58


def test_leaderboard_survives_hostile_names():
    """These are the names that used to make Telegram reject the send; they
    must also not break the renderer."""
    hostile = [
        {"rank": 1, "user_id": 1, "name": "the_real_dave", "balance": 100},
        {"rank": 2, "user_id": 2, "name": "*bossman*", "balance": 90},
        {"rank": 3, "user_id": 3, "name": "[bracket]", "balance": 80},
        {"rank": 4, "user_id": 4, "name": "<script>alert(1)</script>", "balance": 70},
        {"rank": 5, "user_id": 5, "name": "🐍🔥 emoji name", "balance": 60},
        {"rank": 6, "user_id": 6, "name": "A" * 120, "balance": 50},
        {"rank": 7, "user_id": 7, "name": "", "balance": 40},
    ]
    img = open_png(make_leaderboard_image(hostile, total=7))
    assert img.width == 720


def test_leaderboard_draws_movement_arrows():
    movement = {1000: 3, 1001: -2}
    img = open_png(make_leaderboard_image(rows(4), total=4, movement=movement))
    assert img.width == 720


def test_empty_board_still_produces_an_image():
    img = open_png(make_leaderboard_image([], total=0))
    assert img.height == 104 + 58


def test_gradients_are_memoized_within_a_render():
    """A board asks for the same small ramps once per row."""
    primitives._metal_column.cache_clear()
    primitives._metal_full.cache_clear()
    primitives.gradient_text_img.cache_clear()
    make_leaderboard_image(rows(15), total=15)
    info = primitives._metal_full.cache_info()
    assert info.hits > info.misses, info


def test_an_identical_re_render_builds_no_new_gradients():
    board = rows(15)
    make_leaderboard_image(board, total=15)
    before = primitives._metal_column.cache_info().misses
    make_leaderboard_image(board, total=15)
    assert primitives._metal_column.cache_info().misses == before


def test_fit_text_truncates_to_width():
    font = primitives.get_font(20, bold=True)
    long_name = "an extremely long display name that will never fit"
    fitted = primitives.fit_text(long_name, font, 120)
    assert fitted.endswith("…")
    assert primitives.text_size(font, fitted)[0] <= 120
    # A short name is returned untouched.
    assert primitives.fit_text("short", font, 400) == "short"
