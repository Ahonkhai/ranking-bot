"""The /top3 podium image.

Second on the left, first raised in the centre under a laurel and crown, third
on the right — the arrangement everyone already reads as a podium, so the
ranking is legible before a single number is.
"""

from io import BytesIO

from PIL import Image, ImageDraw

from .avatar import place_avatar
from .palette import BG_BOT, BG_TOP, GOLD_M, HAIR, INK, MUTE, rank_metal
from .primitives import (composite_at, crown_img, draw_tracked, fit_text,
                         get_font, gradient_text_img, laurel_wreath,
                         metal_badge, rounded_mask, soft_shadow, text_size,
                         tracked_width, vgradient)

S = 2
W, H = 760 * S, 440 * S

BASELINE = 326 * S          # every pedestal sits on this line
COLUMNS = (190, 380, 570)   # centres: 2nd, 1st, 3rd
SLOT_ORDER = (1, 0, 2)      # which standings index lands in which column

PEDESTAL_W = 176 * S
PEDESTAL_H = (104 * S, 74 * S, 60 * S)  # by podium position: 1st, 2nd, 3rd
AVATAR_D = (112 * S, 92 * S, 92 * S)


def _fmt(n: int) -> str:
    return f"{n:,}"


def _shade(rgb, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)


def _pedestal(base, cx, top, height, metal):
    """A rounded plinth with a lit elliptical top face."""
    light, mid, deep = metal
    x0, x1 = cx - PEDESTAL_W // 2, cx + PEDESTAL_W // 2
    body_h = height
    radius = 14 * S
    face_h = 16 * S
    face_inset = 7 * S

    sh, pad = soft_shadow((PEDESTAL_W, body_h), radius, blur=7 * S, opacity=120)
    composite_at(base, sh, x0 - pad, top - pad + 5 * S)

    body = vgradient((PEDESTAL_W, body_h), _shade(deep, 0.95), _shade(deep, 0.30))
    body = body.convert("RGBA")
    body.putalpha(rounded_mask((PEDESTAL_W, body_h), radius))
    composite_at(base, body, x0, top)

    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([x0, top, x1 - 1, top + body_h - 1], radius=radius,
                           outline=(*mid, 120), width=max(1, S))

    # Top face, so the plinth reads as a solid the avatar stands on. Inset so
    # it can't protrude past the body's rounded corners and read as a saucer.
    fw = PEDESTAL_W - face_inset * 2
    face = Image.new("RGBA", (fw, face_h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)
    fd.ellipse([0, 0, fw - 1, face_h - 1], fill=(*_shade(mid, 0.42), 255))
    fd.ellipse([0, 0, fw - 1, face_h - 1], outline=(*_shade(light, 0.55), 110),
               width=max(1, S))
    composite_at(base, face, x0 + face_inset, top - face_h // 2)


def make_top3_image(rows: list[dict], avatars: dict | None = None) -> BytesIO:
    """Render up to three members. Fewer than three simply leaves slots empty."""
    avatars = avatars or {}
    img = vgradient((W, H), BG_TOP, BG_BOT).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # ── header ────────────────────────────────────────────────────────
    hx, hy = 22 * S, 16 * S
    chip = 26 * S
    badge = vgradient((chip, chip), GOLD_M[0], GOLD_M[2]).convert("RGBA")
    badge.putalpha(rounded_mask((chip, chip), 8 * S))
    composite_at(img, badge, hx, hy)
    composite_at(img, crown_img(int(chip * 0.62), ((60, 46, 18), (40, 31, 12), (26, 20, 8))),
                 hx + chip * 0.19, hy + chip * 0.26)
    draw_tracked(img, (hx + chip + 12 * S, hy + 4 * S), "TOP 3",
                 get_font(17 * S, bold=True), INK, 2 * S)

    # "VIEW ALL" — drawn to match the inline button attached to the message.
    vf = get_font(12 * S, bold=True)
    vw = tracked_width(vf, "VIEW ALL", 2 * S)
    bx1, by0 = W - 22 * S, hy - 2 * S
    bx0, by1 = bx1 - vw - 28 * S, hy + 30 * S
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=9 * S,
                           fill=(26, 23, 17, 255), outline=(*HAIR, 110), width=max(1, S))
    draw_tracked(img, (bx0 + 14 * S, by0 + 9 * S), "VIEW ALL", vf, (222, 208, 176), 2 * S)

    # ── podium ────────────────────────────────────────────────────────
    for slot, index in enumerate(SLOT_ORDER):
        if index >= len(rows):
            continue
        row = rows[index]
        cx = COLUMNS[slot] * S
        metal = rank_metal(row["rank"])
        height = PEDESTAL_H[index]
        av_d = AVATAR_D[index]
        top = BASELINE - height
        first = index == 0

        _pedestal(img, cx, top, height, metal)

        av_cy = top + 16 * S - av_d // 2
        if first:
            wreath = laurel_wreath(av_d, GOLD_M)
            composite_at(img, wreath, cx - wreath.width / 2, av_cy - wreath.height / 2)
        place_avatar(img, avatars.get(row["user_id"]), row["name"], row["user_id"],
                     cx, av_cy, av_d, metal, glow=first,
                     ring_w=max(3 * S, av_d // 26), glow_opacity=70 if first else 0)

        if first:
            crown = crown_img(38 * S, GOLD_M)
            composite_at(img, crown, cx - crown.width / 2,
                         av_cy - av_d / 2 - crown.height + 2 * S)
        else:
            br = 15 * S
            metal_badge(img, cx, av_cy - av_d / 2 - br + 3 * S, br, metal,
                        str(row["rank"]))

        # name and amount, aligned across all three columns
        nfont = get_font(16 * S, bold=True)
        name = fit_text(row["name"], nfont, PEDESTAL_W - 12 * S)
        ntw, _, nb = text_size(nfont, name)
        draw.text((cx - ntw / 2 - nb[0], BASELINE + 22 * S), name, font=nfont, fill=INK)

        afont = get_font((22 if first else 19) * S, bold=True)
        amount = gradient_text_img(f"${_fmt(row['balance'])}", afont, metal)
        composite_at(img, amount, cx - amount.width / 2, BASELINE + 50 * S)

    if not rows:
        f = get_font(18 * S, bold=True)
        tw, _, b = text_size(f, "No one is on the board yet")
        draw.text((W / 2 - tw / 2 - b[0], H / 2), "No one is on the board yet",
                  font=f, fill=MUTE)

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    buf.seek(0)
    return buf
