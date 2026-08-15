"""The /myrank and /rank card — a vertical, premium dark-and-gold profile.

Every value comes in on a RankCard value object; this module looks nothing up
and holds no module-level mutable image state, so concurrent renders cannot
bleed one member's data onto another's card.
"""

from io import BytesIO

from PIL import Image, ImageDraw

from .. import config
from ..cards import RankCard
from .avatar import place_avatar
from .palette import DOWN, FLAT, GOLD_M, HAIR, INK, MUTE, UP, rank_metal
from .primitives import (arrow_img, composite_at, draw_tracked, get_font,
                         gradient_panel, gradient_text_img, light_burst,
                         metal_gradient, paste_center, rounded_mask, soft_shadow,
                         text_size, tracked_width, vgradient)

S = 2                       # supersample factor, downscaled at the end
W, H = 600 * S, 984 * S     # portrait, close to the reference proportions

# Grounds. Deeper than the leaderboard's so the gold reads as the only light.
CARD_TOP, CARD_BOT = (24, 21, 16), (12, 11, 9)
PAGE_TOP, PAGE_BOT = (10, 9, 8), (6, 6, 5)
PANEL_TOP, PANEL_BOT = (30, 27, 20), (19, 17, 13)

DIM = (128, 116, 96)        # secondary label grey, warmed toward the gold


def _fmt(n: int) -> str:
    return f"{n:,}"


def _centre(base, img, cx, y) -> None:
    composite_at(base, img, cx - img.width / 2, y)


def _centre_text(draw, cx, y, text, font, fill) -> None:
    tw, _, b = text_size(font, text)
    draw.text((cx - tw / 2 - b[0], y), text, font=font, fill=fill)


def _centre_tracked(base, cx, y, text, font, fill, tracking) -> None:
    width = tracked_width(font, text, tracking)
    draw_tracked(base, (cx - width / 2, y), text, font, fill, tracking)


def make_rank_card(card: RankCard, avatar_raw: bytes | None = None) -> BytesIO:
    metal = rank_metal(card.rank)
    cx = W // 2

    img = vgradient((W, H), PAGE_TOP, PAGE_BOT).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # ── header, above the card ────────────────────────────────────────
    # A drawn figure, not an emoji — emoji font coverage isn't guaranteed on
    # the host and a missing glyph would show as a box.
    hx, hy = 16 * S, 14 * S
    head_r = 4 * S
    draw.ellipse([hx, hy + 3 * S, hx + head_r * 2, hy + 3 * S + head_r * 2],
                 fill=(*HAIR, 255))
    draw.pieslice([hx - 2 * S, hy + 11 * S, hx + head_r * 2 + 2 * S, hy + 24 * S],
                  180, 360, fill=(*HAIR, 255))
    draw_tracked(img, (hx + 20 * S, hy + 3 * S), card.header,
                 get_font(15 * S, bold=True), INK, 2 * S)

    # ── card panel ────────────────────────────────────────────────────
    m0, m1 = 10 * S, 46 * S           # left/right margin, top offset
    pw, ph = W - 2 * m0, H - m1 - 12 * S
    rad = 30 * S
    sh, pad = soft_shadow((pw, ph), rad, blur=10 * S, opacity=120)
    composite_at(img, sh, m0 - pad, m1 - pad + 5 * S)
    composite_at(img, gradient_panel((pw, ph), rad, CARD_TOP, CARD_BOT), m0, m1)
    draw.rounded_rectangle([m0, m1, m0 + pw - 1, m1 + ph - 1], radius=rad,
                           outline=(*HAIR, 120), width=max(1, S))

    # ── rank badge ────────────────────────────────────────────────────
    bw, bh = 168 * S, 96 * S
    bx, by = cx - bw // 2, 88 * S
    composite_at(img, gradient_panel((bw, bh), 24 * S, (34, 30, 21), (18, 16, 12)), bx, by)
    draw.rounded_rectangle([bx, by, bx + bw - 1, by + bh - 1], radius=24 * S,
                           outline=(*metal[1], 210), width=max(2, S))
    rf = get_font(13 * S, bold=True)
    _centre_tracked(img, cx, by + 14 * S, "RANK", rf, (*HAIR, 255), 3 * S)
    nf = get_font(46 * S, bold=True)
    _centre_text(draw, cx, by + 36 * S, str(card.rank), nf, INK)

    # ── profile ───────────────────────────────────────────────────────
    av_d = 174 * S
    av_cy = 322 * S
    burst = light_burst((W, 330 * S), av_d // 2)
    composite_at(img, burst, 0, av_cy - 165 * S)
    place_avatar(img, avatar_raw, card.name, card.user_id, cx, av_cy, av_d, GOLD_M,
                 glow=True, ring_w=7 * S, glow_opacity=58)

    # badge overlapping the lower right of the portrait
    br = 27 * S
    off = int(av_d / 2 * 0.72)
    bcx, bcy = cx + off, av_cy + off
    grad = metal_gradient((br * 2, br * 2), GOLD_M).convert("RGBA")
    grad.putalpha(rounded_mask((br * 2, br * 2), br))
    g, gp = soft_shadow((br * 2, br * 2), br, blur=6 * S, opacity=130, color=GOLD_M[1])
    composite_at(img, g, bcx - br - gp, bcy - br - gp)
    composite_at(img, grad, bcx - br, bcy - br)
    draw.ellipse([bcx - br, bcy - br, bcx + br - 1, bcy + br - 1],
                 outline=(18, 15, 9, 230), width=max(2, S))
    if card.crowned:
        from .primitives import crown_img
        emblem = crown_img(28 * S, ((40, 32, 14), (28, 22, 10), (18, 14, 6)))
        paste_center(img, emblem, bcx, bcy + S)
    else:
        _centre_text(draw, bcx, bcy - 11 * S, str(card.level),
                     get_font(20 * S, bold=True), (30, 24, 10, 255))

    # ── username ──────────────────────────────────────────────────────
    name = card.name
    nfont = get_font(34 * S, bold=True)
    while text_size(nfont, name)[0] > pw - 60 * S and len(name) > 4:
        name = name[:-2] + "…"
    _centre_text(draw, cx, 448 * S, name, nfont, INK)

    # ── level line ────────────────────────────────────────────────────
    lvl = f"Level {card.level}"
    sep = "  •  "
    lf = get_font(17 * S, bold=True)
    tf = get_font(17 * S, bold=False)
    lw = text_size(lf, lvl)[0]
    sw = text_size(tf, sep)[0]
    tw = text_size(tf, card.level_title)[0]
    lx = cx - (lw + sw + tw) / 2
    draw.text((lx, 500 * S), lvl, font=lf, fill=(*HAIR, 255))
    draw.text((lx + lw, 500 * S), sep, font=tf, fill=DIM)
    draw.text((lx + lw + sw, 500 * S), card.level_title, font=tf, fill=(196, 186, 168))

    # ── total cash ────────────────────────────────────────────────────
    cf = get_font(13 * S, bold=True)
    label = "TOTAL CASH"
    label_w = tracked_width(cf, label, 3 * S)
    ly = 552 * S
    _centre_tracked(img, cx, ly, label, cf, (*HAIR, 255), 3 * S)
    rule_y = ly + 8 * S
    for x0, x1 in ((cx - label_w / 2 - 34 * S, cx - label_w / 2 - 12 * S),
                   (cx + label_w / 2 + 12 * S, cx + label_w / 2 + 34 * S)):
        draw.line([x0, rule_y, x1, rule_y], fill=(*HAIR, 150), width=max(1, S))

    amount = f"{config.CURRENCY_SYMBOL}{_fmt(card.cash)}"
    afont = get_font(56 * S, bold=True)
    while text_size(afont, amount)[0] > pw - 70 * S and afont.size > 20 * S:
        afont = get_font(int(afont.size * 0.9), bold=True)
    _centre(img, gradient_text_img(amount, afont, GOLD_M), cx, 578 * S)

    # Recent movement. Hidden entirely when there is nothing real to show.
    if card.recent_delta:
        up = card.recent_delta > 0
        text = f"{'+' if up else '−'} {_fmt(abs(card.recent_delta))}"
        _centre_text(draw, cx, 654 * S, text, get_font(19 * S, bold=True),
                     UP if up else DOWN)

    # ── XP progress panel ─────────────────────────────────────────────
    px0, px1 = 30 * S, W - 30 * S
    py0, py1 = 700 * S, 828 * S
    composite_at(img, gradient_panel((px1 - px0, py1 - py0), 18 * S, PANEL_TOP, PANEL_BOT),
                 px0, py0)
    draw.rounded_rectangle([px0, py0, px1 - 1, py1 - 1], radius=18 * S,
                           outline=(*HAIR, 55), width=1)

    prog = card.progress
    heading = ("Maximum level reached" if prog.at_max
               else f"Progress to Level {prog.next_level}")
    draw.text((px0 + 22 * S, py0 + 18 * S), heading, font=get_font(16 * S, bold=False),
              fill=(206, 197, 180))

    pf = get_font(15 * S, bold=True)
    pct = f"{prog.percent}%"
    pct_w = text_size(pf, pct)[0]
    bar_x0 = px0 + 22 * S
    bar_x1 = px1 - 22 * S - pct_w - 16 * S
    bar_y0 = py0 + 56 * S
    bar_h = 16 * S
    draw.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y0 + bar_h],
                           radius=bar_h // 2, fill=(46, 42, 33, 255))
    fill_w = int((bar_x1 - bar_x0) * prog.fraction)
    if fill_w >= bar_h:
        fb = metal_gradient((fill_w, bar_h), GOLD_M).convert("RGBA")
        fb.putalpha(rounded_mask((fill_w, bar_h), bar_h // 2))
        composite_at(img, fb, bar_x0, bar_y0)
    elif fill_w > 0:
        draw.ellipse([bar_x0, bar_y0, bar_x0 + bar_h, bar_y0 + bar_h], fill=(*GOLD_M[1], 255))
    draw.text((px1 - 22 * S - pct_w, bar_y0 - 2 * S), pct, font=pf, fill=INK)

    xp_line = (f"{_fmt(prog.xp)} XP" if prog.at_max
               else f"{_fmt(prog.earned)} / {_fmt(prog.needed)} XP")
    draw.text((bar_x0, py0 + 88 * S), xp_line, font=get_font(14 * S, bold=False), fill=DIM)

    # ── bottom statistics ─────────────────────────────────────────────
    sy = 880 * S
    columns = [
        ("JOINED", card.joined.strftime("%d %b %Y").upper() if card.joined else "—", INK),
        ("RANK CHANGE", None, None),
        ("PERCENTILE", f"TOP {card.percentile}%", (*HAIR, 255)),
    ]
    col_w = (W - 2 * m0) / 3
    kf = get_font(12 * S, bold=True)
    vf = get_font(17 * S, bold=True)

    for i, (label, value, colour) in enumerate(columns):
        ccx = m0 + col_w * (i + 0.5)
        _centre_tracked(img, ccx, sy, label, kf, MUTE, 2 * S)
        if label == "RANK CHANGE":
            _draw_rank_change(img, draw, ccx, sy + 26 * S, card.rank_change, vf)
        else:
            _centre_text(draw, ccx, sy + 26 * S, value, vf, colour)
        if i:
            dx = m0 + col_w * i
            draw.line([dx, sy - 4 * S, dx, sy + 52 * S], fill=(*HAIR, 45), width=1)

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    buf.seek(0)
    return buf


def _draw_rank_change(base, draw, ccx, y, change: int | None, font) -> None:
    """↑ n climbed, ↓ n dropped, — when there's no earlier rank to compare."""
    if not change:
        text = "—"
        colour = FLAT if change is None else MUTE
        tw, _, b = text_size(font, text)
        draw.text((ccx - tw / 2 - b[0], y), text, font=font, fill=colour)
        return

    up = change > 0
    colour = UP if up else DOWN
    arrow = arrow_img(11 * S, colour, up=up)
    text = str(abs(change))
    tw, _, b = text_size(font, text)
    block = arrow.width + 7 * S + tw
    x = ccx - block / 2
    composite_at(base, arrow, x, y + 3 * S)
    draw.text((x + arrow.width + 7 * S - b[0], y), text, font=font, fill=colour)
