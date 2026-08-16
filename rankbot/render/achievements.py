"""The /achievements card.

Same black-and-gold world as the board and the rank card. Rarity is carried by
a restrained tint on the tile's frame and glyph rather than by colouring the
whole card in — the palette stays gold, and the rarer badges simply read
warmer or cooler against it.
"""

from io import BytesIO

from PIL import Image, ImageDraw

from .. import config
from ..achievements import Rarity
from .avatar import place_avatar
from .palette import GOLD_M, HAIR, INK, MUTE, rank_metal
from .primitives import (composite_at, draw_tracked, fit_text, get_font,
                         glyph_img, gradient_panel, gradient_text_img,
                         metal_gradient, radial_glow, rounded_mask,
                         text_size, tracked_width, vgradient, vignette)

S = 2
W = 760 * S

GROUND_TOP, GROUND_BOT = (17, 15, 12), (8, 7, 6)
PANEL_TOP, PANEL_BOT = (30, 27, 20), (18, 16, 12)
DIM = (126, 114, 94)

COLUMNS = 3
ROWS = 4
PER_PAGE = COLUMNS * ROWS

# Rarity accents. Muted on purpose — the card is gold, and these only need to
# be different enough to tell apart at a glance.
RARITY_COLOUR = {
    Rarity.COMMON:    (150, 146, 138),
    Rarity.RARE:      (122, 156, 186),
    Rarity.EPIC:      (150, 124, 186),
    Rarity.LEGENDARY: (222, 178, 78),
    Rarity.MYTHIC:    (214, 122, 78),
}

LOCKED_FRAME = (70, 64, 54)
LOCKED_TEXT = (108, 100, 86)
LOCKED_GLYPH = (78, 72, 62)


def _fmt(n: int) -> str:
    return f"{config.CURRENCY_SYMBOL}{n:,}"


def _centre_text(draw, cx, y, text, font, fill):
    tw, _, b = text_size(font, text)
    draw.text((cx - tw / 2 - b[0], y), text, font=font, fill=fill)


def _tile(base, x, y, w, h, entry):
    """One achievement. `entry` carries the Achievement plus its unlock date."""
    achievement = entry["achievement"]
    unlocked = entry["unlocked_at"] is not None
    accent = RARITY_COLOUR[achievement.rarity] if unlocked else LOCKED_FRAME
    draw = ImageDraw.Draw(base)

    top = (34, 30, 22) if unlocked else (21, 19, 16)
    bottom = (20, 18, 13) if unlocked else (14, 13, 11)
    composite_at(base, gradient_panel((w, h), 14 * S, top, bottom), x, y)

    if unlocked and achievement.rarity >= Rarity.LEGENDARY:
        glow = radial_glow((w, h), accent, opacity=40)
        composite_at(base, glow, x, y)

    draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=14 * S,
                           outline=(*accent, 190 if unlocked else 90),
                           width=max(1, S))

    gsize = 34 * S
    glyph = glyph_img(achievement.icon if unlocked else "lock", gsize,
                      accent if unlocked else LOCKED_GLYPH)
    composite_at(base, glyph, x + (w - gsize) / 2, y + 14 * S)

    nfont = get_font(13 * S, bold=True)
    name = fit_text(achievement.name, nfont, w - 14 * S)
    _centre_text(draw, x + w / 2, y + 56 * S, name,
                 nfont, INK if unlocked else LOCKED_TEXT)

    dfont = get_font(10 * S, bold=False)
    desc = fit_text(achievement.description, dfont, w - 12 * S)
    _centre_text(draw, x + w / 2, y + 76 * S, desc,
                 dfont, DIM if unlocked else LOCKED_TEXT)

    if unlocked:
        rf = get_font(8 * S, bold=True)
        label = achievement.rarity.label
        rw = tracked_width(rf, label, S)
        draw_tracked(base, (x + w / 2 - rw / 2, y + h - 18 * S), label, rf,
                     (*accent, 235), S)
        if entry["unlocked_at"]:
            df = get_font(8 * S, bold=False)
            when = entry["unlocked_at"].strftime("%d %b %Y").upper()
            _centre_text(draw, x + w / 2, y + h - 30 * S, when, df, (92, 84, 70))


def make_achievements_card(view: dict) -> BytesIO:
    """Render one page. `view` is assembled by the handler — this module reads
    nothing and holds no state, so concurrent requests can't cross over."""
    entries = view["entries"]
    rows_needed = max(1, (len(entries) + COLUMNS - 1) // COLUMNS)

    header_h = 250 * S
    tile_h = 118 * S
    gap = 14 * S
    grid_h = rows_needed * tile_h + (rows_needed - 1) * gap
    footer_h = 30 * S
    H = header_h + grid_h + footer_h

    img = vgradient((W, H), GROUND_TOP, GROUND_BOT).convert("RGBA")
    composite_at(img, radial_glow((640 * S, 320 * S), (168, 128, 52), opacity=44),
                 W // 2 - 320 * S, -60 * S)
    draw = ImageDraw.Draw(img)

    # ── header ────────────────────────────────────────────────────────
    mx = 24 * S
    composite_at(img, glyph_img("crown", 30 * S, GOLD_M[1]), mx, 20 * S)
    draw_tracked(img, (mx + 42 * S, 24 * S), "ACHIEVEMENTS",
                 get_font(20 * S, bold=True), INK, 3 * S)
    if view["pages"] > 1:
        pf = get_font(12 * S, bold=True)
        ptxt = f"{view['page']} / {view['pages']}"
        ptw, _, _ = text_size(pf, ptxt)
        draw.text((W - mx - ptw, 30 * S), ptxt, font=pf, fill=(*HAIR, 220))

    # ── member strip ──────────────────────────────────────────────────
    strip_y = 62 * S
    strip_h = 96 * S
    composite_at(img, gradient_panel((W - 2 * mx, strip_h), 16 * S, PANEL_TOP, PANEL_BOT),
                 mx, strip_y)
    draw.rounded_rectangle([mx, strip_y, W - mx - 1, strip_y + strip_h - 1],
                           radius=16 * S, outline=(*HAIR, 90), width=max(1, S))

    av_d = 68 * S
    av_cx = mx + 22 * S + av_d // 2
    av_cy = strip_y + strip_h // 2
    place_avatar(img, view["avatar"], view["name"], view["user_id"], av_cx, av_cy,
                 av_d, rank_metal(view["rank"] or 99), glow=True,
                 ring_w=4 * S, glow_opacity=52)

    tx = av_cx + av_d // 2 + 22 * S
    nfont = get_font(22 * S, bold=True)
    draw.text((tx, strip_y + 16 * S),
              fit_text(view["name"], nfont, W - mx - 200 * S - tx), font=nfont, fill=INK)

    sub = f"Level {view['level']} • {view['level_title']}"
    draw.text((tx, strip_y + 46 * S), sub, font=get_font(13 * S, bold=False), fill=DIM)

    rank_txt = f"Rank #{view['rank']}" if view["rank"] else "Unranked"
    draw.text((tx, strip_y + 68 * S), rank_txt,
              font=get_font(12 * S, bold=True), fill=(*HAIR, 235))

    cash = gradient_text_img(_fmt(view["cash"]), get_font(24 * S, bold=True), GOLD_M)
    composite_at(img, cash, W - mx - 22 * S - cash.width, strip_y + 34 * S)

    # ── progress ──────────────────────────────────────────────────────
    py = strip_y + strip_h + 18 * S
    done, total = view["unlocked_count"], view["total"]
    pct = int(round(done / total * 100)) if total else 0

    lf = get_font(12 * S, bold=True)
    label = f"{done} / {total} UNLOCKED"
    draw_tracked(img, (mx, py), label, lf, INK, 2 * S)
    pctxt = f"{pct}% COMPLETE"
    ptw = tracked_width(lf, pctxt, 2 * S)
    draw_tracked(img, (W - mx - ptw, py), pctxt, lf, (*HAIR, 235), 2 * S)

    bar_y = py + 22 * S
    bar_h = 10 * S
    draw.rounded_rectangle([mx, bar_y, W - mx, bar_y + bar_h],
                           radius=bar_h // 2, fill=(44, 40, 31, 255))
    fill_w = int((W - 2 * mx) * (done / total if total else 0))
    if fill_w >= bar_h:
        fb = metal_gradient((fill_w, bar_h), GOLD_M).convert("RGBA")
        fb.putalpha(rounded_mask((fill_w, bar_h), bar_h // 2))
        composite_at(img, fb, mx, bar_y)

    # Rarest unlocked badge, when there is one.
    rarest = view.get("rarest")
    if rarest:
        accent = RARITY_COLOUR[rarest.rarity]
        rf = get_font(10 * S, bold=True)
        draw_tracked(img, (mx, bar_y + 22 * S), "RAREST", rf, MUTE, 2 * S)
        rw = tracked_width(rf, "RAREST", 2 * S)
        draw.text((mx + rw + 12 * S, bar_y + 20 * S),
                  f"{rarest.name}  ·  {rarest.rarity.label}",
                  font=get_font(11 * S, bold=True), fill=(*accent, 255))

    # ── grid ──────────────────────────────────────────────────────────
    grid_x = mx
    span = W - 2 * mx
    step = (span - (COLUMNS - 1) * gap) / COLUMNS
    for i, entry in enumerate(entries):
        col, row = i % COLUMNS, i // COLUMNS
        x = grid_x + col * (step + gap)
        y = header_h + row * (tile_h + gap)
        _tile(img, int(x), int(y), int(step), tile_h, entry)

    composite_at(img, vignette((W, H), strength=52, reach=1.4), 0, 0)
    draw.rounded_rectangle([3 * S, 3 * S, W - 3 * S - 1, H - 3 * S - 1],
                           radius=18 * S, outline=(78, 68, 50, 120), width=max(1, S))

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    buf.seek(0)
    return buf
