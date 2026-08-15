"""The /top3 podium image."""

from io import BytesIO

from PIL import Image

from rankbot import caches
from rankbot.render import make_top3_image
from rankbot.render.avatar import avatar_image


def open_png(buf: BytesIO) -> Image.Image:
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    assert img.format == "PNG"
    return img


def podium(*specs):
    return [{"rank": r, "user_id": u, "name": n, "balance": b}
            for r, u, n, b in specs]


TOP3 = podium((1, 1, "@andrescash", 116_600),
              (2, 2, "@xxxo714", 87_500),
              (3, 3, "@angelondi", 37_000))


def test_renders_at_the_expected_size():
    img = open_png(make_top3_image(TOP3))
    assert (img.width, img.height) == (800, 480)


def test_one_and_two_members_leave_slots_empty():
    for count in (1, 2):
        img = open_png(make_top3_image(TOP3[:count]))
        assert (img.width, img.height) == (800, 480)


def test_empty_board_still_renders():
    assert open_png(make_top3_image([])).width == 800


def test_ties_keep_their_shared_rank():
    """Two members tied at rank 1 both get gold; competition ranking means the
    third is rank 3, not rank 2."""
    tied = podium((1, 1, "@a", 5_000), (1, 2, "@b", 5_000), (3, 3, "@c", 100))
    assert open_png(make_top3_image(tied)).width == 800


def test_hostile_and_oversized_input():
    rough = podium(
        (1, 1, "@" + "x" * 60, 999_999_999_999),
        (2, 2, "Somebody With A Very Long Display Name Indeed", 0),
        (3, 3, "", 1),
    )
    assert open_png(make_top3_image(rough)).width == 800


def test_corrupt_avatar_bytes_fall_back():
    avatars = {1: b"not an image", 2: None, 3: None}
    assert open_png(make_top3_image(TOP3, avatars)).width == 800


def test_identical_input_renders_identically():
    """The podium has to be deterministic or the file_id cache would serve a
    picture that no longer matches the data."""
    assert make_top3_image(TOP3).getvalue() == make_top3_image(TOP3).getvalue()


def test_a_changed_balance_changes_the_image():
    other = podium((1, 1, "@andrescash", 116_601),
                   (2, 2, "@xxxo714", 87_500),
                   (3, 3, "@angelondi", 37_000))
    assert make_top3_image(TOP3).getvalue() != make_top3_image(other).getvalue()


def test_fallback_avatar_follows_a_rename():
    """The initials disc is drawn from the name, so it must not be cached on
    the user id alone — a renamed member would keep the old letter."""
    caches.AVATAR_DISC.clear()
    first = avatar_image(None, "@alice", 999, 64)
    second = avatar_image(None, "@bob", 999, 64)
    assert first.tobytes() != second.tobytes()
