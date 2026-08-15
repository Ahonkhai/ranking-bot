"""The /leaderboard image."""

from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw

from .avatar import place_avatar
from .palette import (BG_BOT, BG_TOP, DOWN, GOLD_M, GOLDDIM_M, HAIR, INK, MUTE,
                      PANEL_BOT, PANEL_TOP, PODIUM_TINT, UP, rank_metal)
from .primitives import (chevron_img, composite_at, draw_text_shadow, crown_img,
                         fit_text, get_font, gradient_panel, gradient_text_img,
                         metal_badge, metal_gradient, rounded_mask, text_size,
                         vgradient)

S = 2  # supersample factor, downscaled at the end


def _fmt(n: int) -> str:
    return f"{n:,}"


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

    `rows` are already sliced and carry their true global rank, so page 3 shows
    ranks 31-45 with the right metals rather than restarting at gold.
    """
    admin_ids = admin_ids or set()
    avatars   = avatars or {}
    movement  = movement or {}
    n         = len(rows)

    W      = 720 * S
    HEADER = 104 * S
    ROW    = 72 * S
    STRIP  = 66 * S if you else 0
    FOOTER = 58 * S
    H      = HEADER + n * ROW + STRIP + FOOTER
    mx     = 22 * S

    img  = vgradient((W, H), BG_TOP, BG_BOT).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # ── header ────────────────────────────────────────────────────────
    hp_h = HEADER - 22 * S
    composite_at(img, gradient_panel((W - 2 * mx, hp_h), 18 * S, PANEL_TOP, PANEL_BOT), mx, 12 * S)
    draw.rounded_rectangle([mx, 12 * S, W - mx - 1, 12 * S + hp_h - 1],
                           radius=18 * S, outline=(*HAIR, 110), width=max(1, S))

    crown = crown_img(42 * S, GOLD_M)
    composite_at(img, crown, mx + 24 * S, 30 * S)
    title_x = mx + 24 * S + crown.width + 18 * S
    composite_at(img, gradient_text_img("LEADERBOARD", get_font(30 * S, bold=True), GOLD_M),
                 title_x, 24 * S)

    sub = scope_label if season is None else f"{scope_label}  ·  SEASON {season}"
    draw.text((title_x + 2 * S, 64 * S), sub, fill=MUTE, font=get_font(12 * S, bold=True))

    # date, and page indicator underneath it when there's more than one page
    df = get_font(12 * S, bold=True)
    date_str = datetime.now().strftime("%d %b %Y").upper()
    dtw, _, _ = text_size(df, date_str)
    draw.text((W - mx - 22 * S - dtw, 34 * S), date_str, fill=MUTE, font=df)
    if pages > 1:
        pstr = f"PAGE {page} / {pages}"
        ptw, _, _ = text_size(df, pstr)
        draw.text((W - mx - 22 * S - ptw, 54 * S), pstr, fill=(*HAIR, 220), font=df)

    # ── rows ──────────────────────────────────────────────────────────
    for i, row in enumerate(rows):
        rank   = row["rank"]
        uid    = row["user_id"]
        y0     = HEADER + i * ROW
        ry1    = y0 + 6 * S
        ry2    = y0 + ROW - 6 * S
        rh     = ry2 - ry1
        cy     = (ry1 + ry2) // 2
        is_adm = uid in admin_ids
        metal  = rank_metal(rank)
        podium = rank <= 3

        if podium:
            tint = PODIUM_TINT[rank - 1]
            composite_at(img, gradient_panel((W - 2 * mx, rh), 14 * S, tint, PANEL_BOT), mx, ry1)
            draw.rounded_rectangle([mx, ry1, W - mx - 1, ry2 - 1], radius=14 * S,
                                   outline=(*metal[1], 160), width=max(1, S))
            bar = metal_gradient((5 * S, rh - 16 * S), metal).convert("RGBA")
            bar.putalpha(rounded_mask(bar.size, 2 * S))
            composite_at(img, bar, mx + 8 * S, ry1 + 8 * S)
        else:
            base = (26, 23, 17) if i % 2 == 0 else (20, 18, 13)
            composite_at(img, gradient_panel((W - 2 * mx, rh), 14 * S, base, PANEL_BOT), mx, ry1)
            draw.rounded_rectangle([mx, ry1, W - mx - 1, ry2 - 1], radius=14 * S,
                                   outline=(*HAIR, 45), width=1)

        # avatar + corner rank badge
        av_d  = 50 * S
        av_cx = mx + 26 * S + av_d // 2
        place_avatar(img, avatars.get(uid), row["name"], uid, av_cx, cy, av_d, metal,
                     glow=(rank == 1))
        br = 13 * S
        metal_badge(img, av_cx + av_d // 2 - br + 2 * S, cy + av_d // 2 - br + 2 * S,
                    br, metal, str(rank))

        # cash, right-aligned
        gimg = gradient_text_img(f"${_fmt(row['balance'])}", get_font(17 * S, bold=True),
                                 GOLD_M if podium else GOLDDIM_M)
        cash_x = W - mx - 22 * S - gimg.width
        composite_at(img, gimg, cash_x, cy - gimg.height // 2)

        # movement indicator, immediately left of the amount
        right_limit = cash_x
        delta = movement.get(uid)
        if delta:
            up    = delta > 0
            color = UP if up else DOWN
            chev  = chevron_img(9 * S, color, up=up)
            mfont = get_font(11 * S, bold=True)
            mtxt  = str(abs(delta))
            mtw, mth, mb = text_size(mfont, mtxt)
            block = chev.width + 3 * S + mtw
            mx0   = cash_x - 16 * S - block
            composite_at(img, chev, mx0, cy - chev.height // 2)
            draw.text((mx0 + chev.width + 3 * S, cy - mth // 2 - mb[1]), mtxt,
                      font=mfont, fill=color)
            right_limit = mx0

        # name, with a crown for chat admins
        nx = av_cx + av_d // 2 + 24 * S
        if is_adm:
            ad_crown = crown_img(20 * S, GOLD_M)
            composite_at(img, ad_crown, nx, cy - ad_crown.height // 2)
            nx += ad_crown.width + 10 * S
        nfont = get_font(17 * S, bold=True)
        nmaxw = max(40 * S, right_limit - 18 * S - nx)
        ncol  = (247, 226, 150) if is_adm else INK
        draw_text_shadow(img, (nx, cy - 13 * S), fit_text(row["name"][:40], nfont, nmaxw),
                         nfont, ncol, off=S)

    # ── "you are here" strip ──────────────────────────────────────────
    if you:
        sy = HEADER + n * ROW + 4 * S
        sh = STRIP - 12 * S
        composite_at(img, gradient_panel((W - 2 * mx, sh), 12 * S, (38, 32, 18), PANEL_BOT), mx, sy)
        draw.rounded_rectangle([mx, sy, W - mx - 1, sy + sh - 1], radius=12 * S,
                               outline=(*HAIR, 130), width=max(1, S))
        scy = sy + sh // 2

        tag = gradient_text_img("YOU", get_font(12 * S, bold=True), GOLD_M)
        composite_at(img, tag, mx + 18 * S, scy - tag.height // 2)
        tx = mx + 18 * S + tag.width + 14 * S

        rank_txt = f"#{you['rank']}"
        rf = get_font(16 * S, bold=True)
        draw.text((tx, scy - 11 * S), rank_txt, fill=INK, font=rf)
        rtw, _, _ = text_size(rf, rank_txt)
        tx += rtw + 12 * S

        nf = get_font(15 * S, bold=True)
        gap_note = you.get("note") or ""
        gnf = get_font(12 * S, bold=True)
        gtw, _, _ = text_size(gnf, gap_note) if gap_note else (0, 0, None)

        cash = gradient_text_img(f"${_fmt(you['balance'])}", get_font(15 * S, bold=True), GOLD_M)
        cash_x = W - mx - 20 * S - cash.width
        composite_at(img, cash, cash_x, scy - cash.height // 2)

        if gap_note:
            draw.text((cash_x - 18 * S - gtw, scy - 7 * S), gap_note, fill=MUTE, font=gnf)
            name_limit = cash_x - 26 * S - gtw
        else:
            name_limit = cash_x - 18 * S
        draw.text((tx, scy - 10 * S), fit_text(you["name"][:32], nf, max(40 * S, name_limit - tx)),
                  fill=(240, 226, 190), font=nf)

    # ── footer ────────────────────────────────────────────────────────
    fy = HEADER + n * ROW + STRIP + 6 * S
    composite_at(img, gradient_panel((W - 2 * mx, FOOTER - 14 * S), 12 * S, PANEL_TOP, PANEL_BOT), mx, fy)
    draw.line([mx + 16 * S, fy - 4 * S, W - mx - 16 * S, fy - 4 * S], fill=(*HAIR, 60), width=1)
    tagline = (f"{total} ranked members — keep climbing." if total
               else "Keep climbing — the next rank is yours.")
    draw.text((mx + 22 * S, fy + 12 * S), tagline, fill=MUTE, font=get_font(12 * S, bold=True))
    wm = gradient_text_img("RANKING BOT", get_font(13 * S, bold=True), GOLD_M)
    composite_at(img, wm, W - mx - 22 * S - wm.width, fy + 11 * S)

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    buf.seek(0)
    return buf
