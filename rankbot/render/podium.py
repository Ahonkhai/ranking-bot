"""The /top3 podium image.

Second on the left, first raised in the centre under a laurel and crown, third
on the right — the arrangement everyone already reads as a ranking, so the
order is legible before a single number is.
"""

from io import BytesIO

from PIL import Image, ImageDraw

from .. import config
from .avatar import place_avatar
from .palette import GOLD_M, HAIR, INK, MUTE, rank_metal
from .primitives import (composite_at, crown_img, draw_tracked, fit_text,
                         get_font, gradient_text_img, laurel_wreath,
                         metal_badge, padlock_img, radial_glow, rounded_mask,
                         soft_shadow, text_size, tracked_width, vgradient)

S = 2
W, H = 800 * S, 480 * S      # the reference's landscape proportions

GROUND_TOP, GROUND_BOT = (17, 15, 12), (7, 6, 6)

BASELINE = 368 * S           # every pedestal stands on this line
COLUMNS = (205, 400, 595)    # centres: 2nd, 1st, 3rd
SLOT_ORDER = (1, 0, 2)       # which standings index lands in which column

PEDESTAL_W = 186 * S
PEDESTAL_H = (118 * S, 84 * S, 68 * S)   # by rank position: 1st, 2nd, 3rd
AVATAR_D = (128 * S, 100 * S, 100 * S)
OVERLAP = (12 * S, 11 * S, 11 * S)       # how far the avatar sinks into the top


def _fmt(n: int) -> str:
    return f"{config.CURRENCY_SYMBOL}{n:,}"


def _shade(rgb, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)


def _cylinder(base, cx, top, height, metal):
    """A podium drum: elliptical top face, straight sides, rounded foot.

    Drawn as one silhouette filled with a vertical gradient, so the body and
    the curved foot share an edge and it reads as a solid — rather than a slab
    with a disc balanced on top of it.
    """
    light, mid, deep = metal
    w = PEDESTAL_W
    face_h = 34 * S
    x0 = cx - w // 2

    sil = Image.new("L", (w, height), 0)
    sd = ImageDraw.Draw(sil)
    sd.ellipse([0, 0, w - 1, face_h - 1], fill=255)
    sd.rectangle([0, face_h // 2, w - 1, height - face_h // 2], fill=255)
    sd.ellipse([0, height - face_h, w - 1, height - 1], fill=255)

    body = vgradient((w, height), _shade(deep, 0.76), _shade(deep, 0.24)).convert("RGBA")
    body.putalpha(sil)

    sh, pad = soft_shadow((w, height), face_h // 2, blur=8 * S, opacity=120)
    composite_at(base, sh, x0 - pad, top - pad + 6 * S)
    composite_at(base, body, x0, top)

    # Lit top surface.
    face = Image.new("RGBA", (w, face_h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)
    fd.ellipse([0, 0, w - 1, face_h - 1], fill=(*_shade(mid, 0.50), 255))
    fd.ellipse([int(w * 0.10), int(face_h * 0.18),
                int(w * 0.90), int(face_h * 0.82)],
               fill=(*_shade(mid, 0.62), 255))
    fd.ellipse([0, 0, w - 1, face_h - 1], outline=(*_shade(light, 0.62), 150),
               width=max(1, S))
    composite_at(base, face, x0, top)

    # A hairline down each side lifts the drum off the background.
    dr = ImageDraw.Draw(base)
    for x in (x0, x0 + w - 1):
        dr.line([x, top + face_h // 2, x, top + height - face_h // 2],
                fill=(*_shade(mid, 0.7), 80), width=max(1, S))


def make_top3_image(rows: list[dict], avatars: dict | None = None) -> BytesIO:
    """Render up to three members. Fewer than three simply leaves slots empty."""
    avatars = avatars or {}
    img = vgradient((W, H), GROUND_TOP, GROUND_BOT).convert("RGBA")

    # Warm pool of light behind the podium, brightest under the champion.
    composite_at(img, radial_glow((740 * S, 430 * S), (176, 132, 52), opacity=58),
                 W // 2 - 370 * S, 86 * S)
    draw = ImageDraw.Draw(img)

    # ── header ────────────────────────────────────────────────────────
    hx, hy = 24 * S, 18 * S
    chip = 30 * S
    badge = vgradient((chip, chip), GOLD_M[0], GOLD_M[2]).convert("RGBA")
    badge.putalpha(rounded_mask((chip, chip), 9 * S))
    composite_at(img, badge, hx, hy)
    lock = padlock_img(int(chip * 0.52))
    composite_at(img, lock, hx + (chip - lock.width) / 2, hy + (chip - lock.height) / 2)
    draw_tracked(img, (hx + chip + 13 * S, hy + 6 * S), "TOP 3",
                 get_font(18 * S, bold=True), INK, 2 * S)

    # "VIEW ALL" — drawn to match the inline button attached to the message.
    vf = get_font(12 * S, bold=True)
    vw = tracked_width(vf, "VIEW ALL", 2 * S)
    bx1, by0 = W - 24 * S, hy - 2 * S
    bx0, by1 = bx1 - vw - 30 * S, hy + 34 * S
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=10 * S,
                           fill=(24, 22, 18, 255), outline=(*HAIR, 120), width=max(1, S))
    draw_tracked(img, (bx0 + 15 * S, by0 + 11 * S), "VIEW ALL", vf, (226, 213, 182), 2 * S)

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

        _cylinder(img, cx, top, height, metal)

        av_cy = top + OVERLAP[index] - av_d // 2

        if first:
            # The champion gets the light, the laurel and the crown; the other
            # two keep plain metal rings so the hierarchy stays obvious.
            halo = radial_glow((av_d * 3, av_d * 3), GOLD_M[1], opacity=86)
            composite_at(img, halo, cx - halo.width / 2, av_cy - halo.height / 2)
            wreath = laurel_wreath(av_d, GOLD_M)
            composite_at(img, wreath, cx - wreath.width / 2, av_cy - wreath.height / 2)

        place_avatar(img, avatars.get(row["user_id"]), row["name"], row["user_id"],
                     cx, av_cy, av_d, metal, glow=first,
                     ring_w=max(3 * S, av_d // 24), glow_opacity=64 if first else 0)

        if first:
            crown = crown_img(46 * S, GOLD_M)
            composite_at(img, crown, cx - crown.width / 2,
                         av_cy - av_d / 2 - crown.height + 4 * S)
        else:
            br = 17 * S
            by = av_cy - av_d / 2 - br + 5 * S
            draw.ellipse([cx - br - 2 * S, by - br - 2 * S,
                          cx + br + 2 * S, by + br + 2 * S],
                         fill=(16, 15, 12, 255))
            metal_badge(img, cx, by, br, metal, str(row["rank"]))

        # Name and amount, aligned across all three columns.
        nfont = get_font(17 * S, bold=True)
        name = fit_text(row["name"], nfont, PEDESTAL_W - 10 * S)
        ntw, _, nb = text_size(nfont, name)
        draw.text((cx - ntw / 2 - nb[0], BASELINE + 26 * S), name, font=nfont, fill=INK)

        afont = get_font((25 if first else 21) * S, bold=True)
        amount = gradient_text_img(_fmt(row["balance"]), afont, metal)
        composite_at(img, amount, cx - amount.width / 2, BASELINE + 54 * S)

    if not rows:
        f = get_font(19 * S, bold=True)
        message = "No one is on the board yet"
        tw, _, b = text_size(f, message)
        draw.text((W / 2 - tw / 2 - b[0], H / 2), message, font=f, fill=MUTE)

    # Containing hairline, so the card has an edge on any chat background.
    draw.rounded_rectangle([3 * S, 3 * S, W - 3 * S - 1, H - 3 * S - 1],
                           radius=20 * S, outline=(78, 68, 50, 130), width=max(1, S))

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    buf.seek(0)
    return buf
