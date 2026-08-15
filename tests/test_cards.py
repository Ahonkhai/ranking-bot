"""The rank card end to end: data assembly, then rendering every case the
card has to survive."""

from io import BytesIO

from PIL import Image

from rankbot import cards, config, store
from rankbot.render.card import make_rank_card
from tests.conftest import CHAT

ADMIN = 111


def open_png(buf: BytesIO) -> Image.Image:
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    assert img.format == "PNG"
    return img


def seed(balances: dict[int, int]):
    for uid, amount in balances.items():
        store.upsert_member(CHAT, uid, f"user{uid}", f"User {uid}")
        if amount:
            store.award(CHAT, uid, amount, ADMIN, "seed")
        else:
            store.award(CHAT, uid, 0, ADMIN, "seed")


# ── data ─────────────────────────────────────────────────────────────────

def test_card_reflects_the_live_board(fresh_db):
    seed({1: 116_600, 2: 87_500, 3: 37_000, 4: 33_333})
    card = cards.build(CHAT, 4, "@fourth")
    assert card.rank == 4
    assert card.total == 4
    assert card.cash == 33_333
    assert card.percentile == 100          # last of four
    assert card.header == "MY RANK"


def test_rank_moves_when_the_score_does(fresh_db):
    seed({1: 100, 2: 200, 3: 300})
    assert cards.build(CHAT, 1, "@a").rank == 3
    store.award(CHAT, 1, 5_000, ADMIN)
    assert cards.build(CHAT, 1, "@a").rank == 1


def test_missing_member_returns_none(fresh_db):
    seed({1: 100})
    assert cards.build(CHAT, 999, "@ghost") is None


def test_ties_share_a_rank_and_the_next_one_skips(fresh_db):
    seed({1: 500, 2: 300, 3: 300, 4: 100})
    ranks = {c: cards.build(CHAT, c, f"@{c}").rank for c in (1, 2, 3, 4)}
    assert ranks == {1: 1, 2: 2, 3: 2, 4: 4}


def test_ranking_is_deterministic_across_calls(fresh_db):
    seed({1: 300, 2: 300, 3: 300})
    first = [r["user_id"] for r in store.standings(CHAT)]
    for _ in range(5):
        assert [r["user_id"] for r in store.standings(CHAT)] == first


def test_no_previous_rank_yields_no_movement(fresh_db):
    seed({1: 100, 2: 200})
    assert cards.build(CHAT, 1, "@a").rank_change is None


def test_positive_and_negative_movement(fresh_db, monkeypatch):
    # Seed "yesterday", then move today, so there is a prior rank to compare.
    seed({1: 100, 2: 200, 3: 300})
    old = store.ago_iso(days=3)
    with store.db.write() as c:
        c.execute("UPDATE ledger SET created_at=?", (old,))

    store.award(CHAT, 1, 10_000, ADMIN)      # last -> first
    climbed = cards.build(CHAT, 1, "@a")
    dropped = cards.build(CHAT, 3, "@c")
    assert climbed.rank_change == 2          # 3rd -> 1st
    assert dropped.rank_change == -1         # 1st -> 2nd


def test_zero_movement_is_zero_not_none(fresh_db):
    seed({1: 100, 2: 200})
    with store.db.write() as c:
        c.execute("UPDATE ledger SET created_at=?", (store.ago_iso(days=3),))
    store.award(CHAT, 1, 1, ADMIN)           # not enough to overtake
    assert cards.build(CHAT, 1, "@a").rank_change == 0


def test_xp_is_lifetime_and_survives_a_deduction(fresh_db):
    seed({1: 5_000})
    before = cards.build(CHAT, 1, "@a").progress.xp
    store.deduct(CHAT, 1, 4_000, ADMIN)
    after = cards.build(CHAT, 1, "@a")
    assert after.cash == 1_000               # cash fell
    assert after.progress.xp == before       # XP did not


def test_xp_survives_a_season_reset(fresh_db):
    seed({1: 9_000})
    level_before = cards.build(CHAT, 1, "@a").level
    store.close_season(CHAT)
    store.award(CHAT, 1, 10, ADMIN)          # back on the new season's board
    card = cards.build(CHAT, 1, "@a")
    assert card.cash == 10
    assert card.level >= level_before


def test_joined_date_comes_from_the_first_entry(fresh_db):
    seed({1: 100})
    card = cards.build(CHAT, 1, "@a")
    assert card.joined is not None


def test_crown_for_rank_one_and_for_admins(fresh_db):
    seed({1: 900, 2: 100})
    assert cards.build(CHAT, 1, "@a").crowned is True
    assert cards.build(CHAT, 2, "@b").crowned is False
    assert cards.build(CHAT, 2, "@b", is_admin=True).crowned is True


def test_member_header(fresh_db):
    seed({1: 100})
    assert cards.build(CHAT, 1, "@a", header="MEMBER RANK").header == "MEMBER RANK"


# ── rendering ────────────────────────────────────────────────────────────

def render_for(uid, name="@member", **kw):
    card = cards.build(CHAT, uid, name, **kw)
    assert card is not None
    return open_png(make_rank_card(card))


def test_card_renders_at_the_expected_size(fresh_db):
    seed({1: 33_333})
    img = render_for(1)
    assert (img.width, img.height) == (600, 984)


def test_rank_one_middle_and_last(fresh_db):
    seed({i: 1_000 * (30 - i) for i in range(1, 31)})
    for uid in (1, 15, 30):
        assert render_for(uid).width == 600


def test_member_without_a_username_uses_their_display_name(fresh_db):
    store.upsert_member(CHAT, 42, None, "Ada Lovelace")
    store.award(CHAT, 42, 500, ADMIN)
    card = cards.build(CHAT, 42, store.member_name(CHAT, 42))
    assert card.name == "Ada Lovelace"
    assert open_png(make_rank_card(card)).width == 600


def test_member_without_a_profile_photo_gets_an_initial(fresh_db):
    seed({1: 500})
    card = cards.build(CHAT, 1, "@solo")
    assert open_png(make_rank_card(card, avatar_raw=None)).width == 600


def test_corrupt_avatar_bytes_fall_back_instead_of_raising(fresh_db):
    seed({1: 500})
    card = cards.build(CHAT, 1, "@solo")
    assert open_png(make_rank_card(card, avatar_raw=b"not a png")).width == 600


def test_hostile_and_oversized_names(fresh_db):
    seed({1: 500})
    for name in ("the_real_dave", "<script>", "*bossman*", "A" * 90, "🐍 emoji", "@x"):
        card = cards.build(CHAT, 1, name)
        assert open_png(make_rank_card(card)).width == 600


def test_large_scores_do_not_overflow_the_card(fresh_db):
    seed({1: 999_999_999_999})
    assert render_for(1).width == 600


def test_zero_score_renders(fresh_db):
    seed({1: 0, 2: 100})
    assert render_for(1).width == 600


def test_lone_member_does_not_divide_by_zero(fresh_db):
    seed({1: 100})
    card = cards.build(CHAT, 1, "@solo")
    assert card.rank == 1 and card.total == 1
    assert card.percentile == 100
    assert open_png(make_rank_card(card)).width == 600


def test_movement_variants_all_render(fresh_db):
    seed({1: 500})
    base = cards.build(CHAT, 1, "@a")
    from dataclasses import replace
    for change in (None, 0, 3, -2, 47):
        assert open_png(make_rank_card(replace(base, rank_change=change))).width == 600


def test_recent_delta_variants_all_render(fresh_db):
    seed({1: 500})
    base = cards.build(CHAT, 1, "@a")
    from dataclasses import replace
    for delta in (0, 1_250, -980):
        assert open_png(make_rank_card(replace(base, recent_delta=delta))).width == 600


def test_currency_symbol_is_configurable(fresh_db, monkeypatch):
    monkeypatch.setattr(config, "CURRENCY_SYMBOL", "€")
    seed({1: 500})
    assert render_for(1).width == 600


def test_concurrent_renders_do_not_share_state(fresh_db):
    """Two members rendered from threads must each get their own image."""
    import concurrent.futures as cf
    seed({1: 900, 2: 100})
    a = cards.build(CHAT, 1, "@first")
    b = cards.build(CHAT, 2, "@second")
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda c: make_rank_card(c).getvalue(),
                                [a, b, a, b, a, b]))
    assert results[0] == results[2] == results[4]
    assert results[1] == results[3] == results[5]
    assert results[0] != results[1]
