"""The /leaderboard image — a premium, framed ranking poster.

The picture is built in three bands: a centered header, a three-person podium
for the top three, and a glass list for everyone below them. The podium only
appears on the page that actually holds ranks 1–3 (page one), so later pages
degrade to header + list without any special-casing at the call site — the
renderer decides from the ranks it was handed.

Every value comes in on the arguments; this module looks nothing up, so two
concurrent renders can never bleed one board's data into another's.
"""

from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw

from .. import config
from .avatar import place_avatar
from .palette import (BG_BOT, BG_TOP, DOWN, FLAT, GOLD_M, GOLDDIM_M, HAIR, INK,
                      MUTE, PANEL_BOT, UP, rank_metal)
from .primitives import (arrow_img, composite_at, crown_img, diamond_img,
                         draw_tracked, fit_text, get_font, gradient_panel,
                         gradient_text_img, laurel_wreath, light_burst,
                         metal_gradient, radial_glow, text_size, tracked_width,
                         vignette)

S = 2  # supersample factor, downscaled at the end
W = 720 * S
MX = 24 * S                      # content margin
FRAME = 10 * S                   # outer gold frame inset

# Band heights, in supersampled pixels.
HEADER_H = 196 * S
PODIUM_H = 452 * S
GAP      = 16 * S
FOOTER_H = 66 * S

# List metrics.
COL_H  = 34 * S                  # column-header strip
ROW_H  = 80 * S
IPAD   = 10 * S                  # list-panel inner padding
YOU_H  = 74 * S

SUBTITLE = "THE INNER CIRCLE"
SIGNOFF  = "BRING LICKS"

# Faint fills for the glass surfaces.
LIST_TOP, LIST_BOT = (26, 23, 17), (12, 11, 8)
TILE_TOP, TILE_BOT = (40, 35, 24), (22, 19, 13)


def _fmt(n: int) -> str:
    return f"{n:,}"


def _cash(n: int) -> str:
    return f"{config.CURRENCY_SYMBOL}{_fmt(n)}"


def _badge_label(title: str | None) -> str | None:
    """The row/podium status badge text.

    A display transform of the real level title, not new data: the ranks share
    the word "Member", which reads as noise in a two-word pill, so it's dropped
    to leave the punchy half — "Elite Member" → "ELITE".
    """
    if not title:
        return None
    return title.upper().replace(" MEMBER", "").strip()


def _centre_text(draw, cx, y, text, font, fill) -> None:
    tw, _, b = text_size(font, text)
    draw.text((cx - tw / 2 - b[0], y), text, font=font, fill=fill)


# ── ornaments ──────────────────────────────────────────────────────────────

def _shield(w: int, h: int, metal, label: str) -> Image.Image:
    """A metallic rank shield: rounded top, pointed base, number inside."""
    mask = Image.new("L", (w, h), 0)
    pts = [(2, 2), (w - 2, 2), (w - 2, int(h * 0.52)),
           (w / 2, h - 2), (2, int(h * 0.52))]
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    img = metal_gradient((w, h), metal).convert("RGBA")
    img.putalpha(mask)
    d = ImageDraw.Draw(img)
    d.line(pts + [pts[0]], fill=(255, 240, 205, 150), width=max(1, S))
    f = get_font(int(h * 0.40), bold=True)
    _centre_text(d, w / 2, h * 0.40 - text_size(f, label)[1] / 2, label, f, (34, 24, 8, 255))
    return img


def _pedestal(base, cx, base_y, w, h, metal) -> None:
    """A dark cylinder podium with a metal rim — the plinth a winner stands on."""
    eh = int(w * 0.20)
    x0, top_y = int(cx - w / 2), int(base_y - h)
    body = gradient_panel((int(w), int(h + eh)), 0, (30, 27, 20), (9, 8, 6))
    d = ImageDraw.Draw(base)
    d.ellipse([x0, base_y - eh / 2, x0 + w, base_y + eh / 2], fill=(8, 7, 6, 255))
    composite_at(base, body, x0, top_y)
    # front rim of the base, and the elliptical cap the avatar sits on
    d.ellipse([x0, top_y - eh / 2, x0 + w, top_y + eh / 2],
              fill=(24, 21, 15, 255), outline=(*metal[1], 210), width=max(1, S))
    d.arc([x0, base_y - eh, x0 + w, base_y], 20, 160, fill=(*metal[2], 150), width=max(1, S))


def _status_pill(base, x, cy, label, *, align="left", metal=GOLDDIM_M):
    """Small level-title badge. Returns its width so callers can lay out around it."""
    f = get_font(11 * S, bold=True)
    tw = tracked_width(f, label, S)
    px, h = 11 * S, 23 * S
    w = tw + 2 * px
    x0 = x if align == "left" else int(x - w / 2)
    y0 = int(cy - h / 2)
    composite_at(base, gradient_panel((w, h), h // 2, (46, 40, 27), (26, 22, 15)), x0, y0)
    ImageDraw.Draw(base).rounded_rectangle([x0, y0, x0 + w - 1, y0 + h - 1],
                                           radius=h // 2, outline=(*metal[1], 150), width=1)
    draw_tracked(base, (x0 + px, y0 + 6 * S), label, f, (228, 212, 176, 255), S)
    return w


def _movement(base, draw, cx, cy, delta, font) -> None:
    """↑ n / ↓ n / — , centred on cx. Never invents a value it wasn't given."""
    if not delta:
        _centre_text(draw, cx, cy - text_size(font, "—")[1] / 2, "—", font, FLAT)
        return
    up = delta > 0
    colour = UP if up else DOWN
    arrow = arrow_img(11 * S, colour, up=up)
    txt = str(abs(delta))
    tw, th, b = text_size(font, txt)
    block = arrow.width + 7 * S + tw
    x = cx - block / 2
    composite_at(base, arrow, x, cy - arrow.height / 2)
    draw.text((x + arrow.width + 7 * S - b[0], cy - th / 2 - b[1]), txt, font=font, fill=colour)


# ── bands ────────────────────────────────────────────────────────────────

def _header(img, draw, y0, total) -> None:
    cx = W // 2

    # crown, top-left
    crown = crown_img(30 * S, GOLD_M)
    composite_at(img, crown, MX + 6 * S, y0 + 14 * S)

    # total members, top-right — the one live stat the header carries
    tf = get_font(11 * S, bold=True)
    lbl = "TOTAL MEMBERS"
    lw = tracked_width(tf, lbl, 2 * S)
    draw_tracked(img, (W - MX - lw, y0 + 12 * S), lbl, tf, MUTE, 2 * S)
    count = gradient_text_img(_fmt(total), get_font(22 * S, bold=True), GOLD_M)
    composite_at(img, count, W - MX - count.width, y0 + 26 * S)

    # title
    tfont = get_font(52 * S, bold=True)
    title = gradient_text_img("THE RANKINGS", tfont, GOLD_M)
    max_w = W - 2 * (MX + 40 * S)
    if title.width > max_w:
        title = title.resize((max_w, int(title.height * max_w / title.width)))
    composite_at(img, title, cx - title.width // 2, y0 + 40 * S)
    ty = y0 + 40 * S + title.height

    # subtitle
    sf = get_font(17 * S, bold=True)
    sw = tracked_width(sf, SUBTITLE, 6 * S)
    draw_tracked(img, (cx - sw / 2, ty + 8 * S), SUBTITLE, sf, (208, 184, 122), 6 * S)

    # a thin flourish, then the date
    fy = ty + 8 * S + text_size(sf, SUBTITLE)[1] + 14 * S
    dia = diamond_img(7 * S, GOLD_M)
    composite_at(img, dia, cx - dia.width // 2, fy - dia.height // 2)
    for sgn in (-1, 1):
        x_in = cx + sgn * 18 * S
        x_out = cx + sgn * 70 * S
        draw.line([min(x_in, x_out), fy, max(x_in, x_out), fy], fill=(*HAIR, 130), width=max(1, S))

    df = get_font(13 * S, bold=True)
    date_str = datetime.now().strftime("%d %b %Y").upper()
    dw = tracked_width(df, date_str, 2 * S)
    draw_tracked(img, (cx - dw / 2, fy + 12 * S), date_str, df, (206, 197, 178), 2 * S)


def _podium_person(img, draw, cx, base_y, ped_h, ped_w, row, admin_ids):
    metal = rank_metal(row["rank"])
    is_top = row["rank"] == 1
    d = 136 * S if is_top else 108 * S
    top_y = base_y - ped_h
    av_cy = int(top_y - d / 2 + 30 * S)

    _pedestal(img, cx, base_y, ped_w, ped_h, metal)

    if is_top:
        glow = radial_glow((int(d * 2.2), int(d * 2.2)), GOLD_M[1], opacity=120)
        composite_at(img, glow, cx - glow.width // 2, av_cy - glow.height // 2)
        wreath = laurel_wreath(d + 18 * S, GOLD_M)
        composite_at(img, wreath, cx - wreath.width // 2, av_cy - wreath.height // 2)

    place_avatar(img, row.get("avatar"), row["name"], row["user_id"], cx, av_cy, d, metal,
                 glow=is_top, ring_w=6 * S if is_top else 5 * S, glow_opacity=70)

    if is_top:
        crown = crown_img(46 * S, GOLD_M)
        composite_at(img, crown, cx - crown.width // 2, int(av_cy - d / 2 - crown.height + 6 * S))

    # rank shield, on the pedestal front
    sw, sh = (46 * S, 56 * S) if is_top else (40 * S, 48 * S)
    shield = _shield(sw, sh, metal, str(row["rank"]))
    composite_at(img, shield, cx - sw / 2, int(top_y + ped_h * 0.44 - sh / 2))

    # name, badge, score — a shared band beneath every pedestal
    name_y = base_y + 20 * S
    nfont = get_font(19 * S, bold=True)
    col_w = ped_w + 64 * S
    name = fit_text(row["name"], nfont, col_w)
    if row["user_id"] in admin_ids:
        ac = crown_img(16 * S, GOLD_M)
        nw = text_size(nfont, name)[0]
        composite_at(img, ac, int(cx - nw / 2 - ac.width - 6 * S), int(name_y + 3 * S))
    _centre_text(draw, cx, name_y, name, nfont, (247, 226, 150) if row["user_id"] in admin_ids else INK)

    label = _badge_label(row.get("title"))
    score_y = name_y + 30 * S
    if label:
        _status_pill(img, cx, name_y + 30 * S + 4 * S, label, align="center", metal=metal)
        score_y = name_y + 58 * S

    sfont = get_font(30 * S if is_top else 25 * S, bold=True)
    score = gradient_text_img(_cash(row["balance"]), sfont, metal)
    composite_at(img, score, cx - score.width // 2, score_y)


def _podium(img, draw, y0, podium, admin_ids) -> None:
    by_rank = {r["rank"]: r for r in podium}
    base_y = y0 + 296 * S
    cx = W // 2
    # Draw the shorter side plinths first so the taller centre overlaps them.
    layout = [
        (2, cx - 196 * S, 74 * S, 120 * S),
        (3, cx + 196 * S, 56 * S, 120 * S),
        (1, cx,           104 * S, 150 * S),
    ]
    for rank, px, ph, pw in layout:
        if rank in by_rank:
            _podium_person(img, draw, px, base_y, ph, pw, by_rank[rank], admin_ids)


def _list(img, draw, y0, rows, admin_ids, movement) -> int:
    """The glass list of ranks 4+. Returns the band height it consumed."""
    n = len(rows)
    h = IPAD + COL_H + n * ROW_H + IPAD
    x0, x1 = MX, W - MX
    composite_at(img, gradient_panel((x1 - x0, h), 22 * S, LIST_TOP, LIST_BOT), x0, y0)
    draw.rounded_rectangle([x0, y0, x1 - 1, y0 + h - 1], radius=22 * S,
                           outline=(*HAIR, 120), width=max(1, S))

    rank_cx = x0 + 40 * S
    av_cx   = x0 + 104 * S
    name_x  = av_cx + 46 * S
    cash_r  = x1 - 28 * S
    mv_cx   = x1 - 250 * S
    name_max = mv_cx - 60 * S - name_x

    # column headers
    hf = get_font(11 * S, bold=True)
    hy = y0 + IPAD + 10 * S
    draw_tracked(img, (rank_cx - tracked_width(hf, "RANK", 2 * S) / 2, hy), "RANK", hf, MUTE, 2 * S)
    draw_tracked(img, (name_x, hy), "MEMBER", hf, MUTE, 2 * S)
    draw_tracked(img, (mv_cx - tracked_width(hf, "MOVEMENT", 2 * S) / 2, hy), "MOVEMENT", hf, MUTE, 2 * S)
    ctw = tracked_width(hf, "TOTAL CASH", 2 * S)
    draw_tracked(img, (cash_r - ctw, hy), "TOTAL CASH", hf, MUTE, 2 * S)

    rows_top = y0 + IPAD + COL_H
    nfont = get_font(18 * S, bold=True)
    rankf = get_font(17 * S, bold=True)
    cashf = get_font(21 * S, bold=True)
    mvf   = get_font(15 * S, bold=True)

    for i, row in enumerate(rows):
        cy = int(rows_top + i * ROW_H + ROW_H / 2)
        if i:
            draw.line([x0 + 20 * S, rows_top + i * ROW_H, x1 - 20 * S, rows_top + i * ROW_H],
                      fill=(*HAIR, 34), width=1)

        # rank tile
        tw_, th_ = 46 * S, 46 * S
        tx, ty = int(rank_cx - tw_ / 2), int(cy - th_ / 2)
        composite_at(img, gradient_panel((tw_, th_), 12 * S, TILE_TOP, TILE_BOT), tx, ty)
        draw.rounded_rectangle([tx, ty, tx + tw_ - 1, ty + th_ - 1], radius=12 * S,
                               outline=(*HAIR, 120), width=1)
        _centre_text(draw, rank_cx, cy - text_size(rankf, str(row["rank"]))[1] / 2 - 2 * S,
                     str(row["rank"]), rankf, INK)

        # avatar
        place_avatar(img, row.get("avatar"), row["name"], row["user_id"], av_cx, cy,
                     54 * S, GOLDDIM_M, ring_w=3 * S)

        is_adm = row["user_id"] in admin_ids
        label = _badge_label(row.get("title"))
        nx = name_x
        if is_adm:
            ac = crown_img(18 * S, GOLD_M)
            composite_at(img, ac, nx, cy - 22 * S)
            nx += ac.width + 8 * S
        name = fit_text(row["name"], nfont, name_max - (nx - name_x))
        draw.text((nx, cy - 22 * S), name, font=nfont, fill=(247, 226, 150) if is_adm else INK)
        if label:
            _status_pill(img, name_x, cy + 14 * S, label)

        # movement, then cash on the far right
        _movement(img, draw, mv_cx, cy, movement.get(row["user_id"]), mvf)
        cash = gradient_text_img(_cash(row["balance"]), cashf, GOLD_M)
        composite_at(img, cash, cash_r - cash.width, cy - cash.height // 2)

    return h


def _you(img, draw, y0, you) -> None:
    x0, x1 = MX, W - MX
    h = YOU_H
    composite_at(img, gradient_panel((x1 - x0, h), 16 * S, (44, 37, 20), PANEL_BOT), x0, y0)
    draw.rounded_rectangle([x0, y0, x1 - 1, y0 + h - 1], radius=16 * S,
                           outline=(*HAIR, 150), width=max(1, S))
    cy = y0 + h // 2

    tag = gradient_text_img("YOU", get_font(12 * S, bold=True), GOLD_M)
    composite_at(img, tag, x0 + 20 * S, cy - tag.height // 2)
    tx = x0 + 20 * S + tag.width + 16 * S

    rf = get_font(16 * S, bold=True)
    rank_txt = f"#{you['rank']}"
    draw.text((tx, cy - 11 * S), rank_txt, fill=INK, font=rf)
    tx += text_size(rf, rank_txt)[0] + 14 * S

    cash = gradient_text_img(_cash(you["balance"]), get_font(16 * S, bold=True), GOLD_M)
    cash_x = x1 - 22 * S - cash.width
    composite_at(img, cash, cash_x, cy - cash.height // 2)

    note = you.get("note") or ""
    gnf = get_font(12 * S, bold=True)
    if note:
        gtw = text_size(gnf, note)[0]
        draw.text((cash_x - 18 * S - gtw, cy - 7 * S), note, fill=MUTE, font=gnf)
        name_limit = cash_x - 26 * S - gtw
    else:
        name_limit = cash_x - 18 * S
    nf = get_font(15 * S, bold=True)
    draw.text((tx, cy - 10 * S), fit_text(you["name"], nf, max(40 * S, name_limit - tx)),
              fill=(240, 226, 190), font=nf)


def _footer(img, draw, y0) -> None:
    """A hairline rule and the sign-off — the only footer text there is."""
    draw.line([MX + 4 * S, y0 + 2 * S, W - MX - 4 * S, y0 + 2 * S], fill=(*HAIR, 55), width=1)
    f = get_font(13 * S, bold=True)
    track = 4 * S
    # draw_tracked can't carry a metal fill, so the gold glyphs are laid one at a
    # time to keep both the gradient and the letter-spacing, right-aligned.
    gx = W - MX - 4 * S - tracked_width(f, SIGNOFF, track)
    for ch in SIGNOFF:
        if ch != " ":
            composite_at(img, gradient_text_img(ch, f, GOLD_M), gx, y0 + 22 * S)
        gx += text_size(f, ch)[0] + track


def make_leaderboard_image(
    rows: list[dict],
    admin_ids: set | None = None,
    avatars: dict | None = None,
    *,
    page: int = 1,
    pages: int = 1,
    total: int = 0,
    scope_label: str = "THIS SEASON",
    season: int | None = None,
    movement: dict | None = None,
    you: dict | None = None,
) -> BytesIO:
    """Render one page of the board.

    `rows` carry their true global rank, so the podium only forms on the page
    holding ranks 1–3 and later pages fall through to a plain list.
    """
    admin_ids = admin_ids or set()
    avatars   = avatars or {}
    movement  = movement or {}

    # Copy each row with its avatar attached, so the band helpers stay
    # data-driven and the caller's shared dicts are never mutated.
    rows = [dict(r, avatar=avatars.get(r["user_id"])) for r in rows]

    podium = [r for r in rows if r["rank"] <= 3]
    listed = [r for r in rows if r["rank"] > 3]
    has_podium = bool(podium)

    # ── measure, so the background gradient can be built at the right height ──
    y = FRAME
    header_y = y
    y += HEADER_H
    if has_podium:
        podium_y = y
        y += PODIUM_H
    if listed:
        y += GAP
        list_y = y
        list_h = IPAD + COL_H + len(listed) * ROW_H + IPAD
        y += list_h
    if you:
        y += GAP
        you_y = y
        y += YOU_H
    y += GAP
    footer_y = y
    y += FOOTER_H + FRAME
    H = y

    # ── ground: warm near-black, a pool of gold behind the podium, particles ──
    img = gradient_panel((W, H), 26 * S, BG_TOP, BG_BOT)
    ground = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    ground.alpha_composite(img)
    img = ground
    draw = ImageDraw.Draw(img)

    if has_podium:
        glow = radial_glow((W, PODIUM_H + 120 * S), GOLD_M[1], opacity=70, falloff=1.8)
        composite_at(img, glow, 0, podium_y - 40 * S)
    burst = light_burst((W, 320 * S), 150 * S)
    composite_at(img, burst, 0, header_y + 40 * S)

    composite_at(img, vignette((W, H), strength=150), 0, 0)

    # ── outer frame ──────────────────────────────────────────────────────────
    draw.rounded_rectangle([FRAME, FRAME, W - FRAME - 1, H - FRAME - 1],
                           radius=22 * S, outline=(*HAIR, 200), width=max(2, S))
    draw.rounded_rectangle([FRAME + 4 * S, FRAME + 4 * S, W - FRAME - 4 * S - 1, H - FRAME - 4 * S - 1],
                           radius=18 * S, outline=(*HAIR, 60), width=1)

    # ── bands ────────────────────────────────────────────────────────────────
    _header(img, draw, header_y, total)
    if has_podium:
        _podium(img, draw, podium_y, podium, admin_ids)
    if listed:
        _list(img, draw, list_y, listed, admin_ids, movement)
    if you:
        _you(img, draw, you_y, you)
    _footer(img, draw, footer_y)

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    buf.seek(0)
    return buf
