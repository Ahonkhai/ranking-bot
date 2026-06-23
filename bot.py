import os
import json
import time
import asyncio
from functools import lru_cache
from datetime import datetime
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")
DATA_FILE  = os.getenv("DATA_FILE", "data.json")   # point at a mounted volume in prod
CURRENCY   = "💰"

# ── In-memory state (loaded once at startup) + concurrency guards ──
DATA: dict        = {"users": {}}
DATA_LOCK         = asyncio.Lock()        # serialize read-modify-write on DATA
RENDER_SEM        = asyncio.Semaphore(1)  # one PIL render at a time, off the loop

# Avatar cache:  uid -> (fetched_at_epoch, png_bytes | None)
AVATAR_CACHE: dict[int, tuple] = {}
AVATAR_TTL = 3600  # seconds

# ─────────────────────────────────────────
#  DATA LAYER
# ─────────────────────────────────────────

def init_data():
    """Load data.json from disk once, into the shared in-memory DATA dict."""
    global DATA
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                DATA = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: could not read {DATA_FILE} ({e}); starting empty.")
            DATA = {"users": {}}
    DATA.setdefault("users", {})

def load_data() -> dict:
    """Return the shared in-memory store (no disk read)."""
    return DATA

def save_data(data: dict | None = None):
    """Atomically persist DATA: write a temp file, then os.replace it in."""
    d = DATA if data is None else data
    directory = os.path.dirname(DATA_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{DATA_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)   # atomic on the same filesystem

def get_user(data: dict, uid: int, name: str = "") -> dict:
    key = str(uid)
    if key not in data["users"]:
        data["users"][key] = {"name": name or f"User{uid}", "cash": 0}
    elif name:
        data["users"][key]["name"] = name
    return data["users"][key]

def sorted_members(data: dict) -> list[tuple]:
    return sorted(data["users"].items(), key=lambda x: x[1]["cash"], reverse=True)

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    admins = await update.effective_chat.get_administrators()
    return update.effective_user.id in {a.user.id for a in admins}

def rank_emoji(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

def fmt(n: int) -> str:
    return f"{n:,}"

def display_name(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or f"User{user.id}"

async def resolve_target(update, context, args):
    """
    Returns (user_id, name_str, amount) from either:
      - reply style:  reply to message + /cmd amount
      - tag style:    /cmd amount @username  OR  /cmd @username amount
    Returns (None, None, None) on bad input, (-1, name, amount) if username not found in data.
    """
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
        if not args:
            return None, None, None
        try:
            amount = int(args[0])
        except ValueError:
            return None, None, None
        return t.id, display_name(t), amount

    username = None
    amount   = None
    for a in args:
        if a.startswith("@"):
            username = a[1:]
        else:
            try:
                amount = int(a)
            except ValueError:
                pass

    if username is None or amount is None:
        return None, None, None

    data = load_data()
    for uid, u in data["users"].items():
        saved = u["name"].lstrip("@")
        if saved.lower() == username.lower():
            return int(uid), u["name"], amount

    return -1, f"@{username}", amount

# ─────────────────────────────────────────
#  DRAWING HELPERS
# ─────────────────────────────────────────

# Warm near-black background + panel gradients
BG_TOP, BG_BOT       = (22, 19, 14), (7, 6, 5)
PANEL_TOP, PANEL_BOT = (32, 28, 20), (15, 13, 9)
INK   = (245, 239, 225)   # warm white  (names / headings)
MUTE  = (151, 133, 92)    # muted tan   (subtitles / labels)
HAIR  = (198, 162, 86)    # gold hairline

# Metallic gradients, expressed as (light, mid, deep)
GOLD_M    = ((255, 233, 153), (240, 193, 66), (150, 105, 27))
SILVER_M  = ((238, 240, 246), (190, 194, 202), (98, 102, 112))
BRONZE_M  = ((237, 178, 122), (193, 121, 66), (110, 67, 34))
GOLDDIM_M = ((205, 176, 110), (150, 122, 60), (92, 72, 30))

def rank_metal(rank):
    return {1: GOLD_M, 2: SILVER_M, 3: BRONZE_M}.get(rank, GOLDDIM_M)

def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def composite_at(base, overlay, x, y):
    """Alpha-composite `overlay` onto `base` at (x, y); clips off-canvas/negative
    coords (so blurred shadows that bleed past the edge just work)."""
    x, y   = int(round(x)), int(round(y))
    bw, bh = base.size
    ow, oh = overlay.size
    cx0, cy0 = max(0, -x), max(0, -y)
    cx1, cy1 = min(ow, bw - x), min(oh, bh - y)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    region = overlay.crop((cx0, cy0, cx1, cy1)) if (cx0, cy0, cx1, cy1) != (0, 0, ow, oh) else overlay
    base.alpha_composite(region, (x + cx0, y + cy0))

def paste_center(base, overlay, cx, cy):
    composite_at(base, overlay, cx - overlay.width / 2, cy - overlay.height / 2)

def vgradient(size, top, bottom):
    """Vertical 2-stop RGB gradient (1px column stretched to width)."""
    w, h = size
    col, px = Image.new("RGB", (1, h)), None
    px = col.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = (int(top[0] + (bottom[0]-top[0])*t),
                    int(top[1] + (bottom[1]-top[1])*t),
                    int(top[2] + (bottom[2]-top[2])*t))
    return col.resize((w, h))

def metal_gradient(size, metal):
    """Vertical metallic sheen: light → mid (bright band ~45%) → deep."""
    light, mid, deep = metal
    w, h = size
    col = Image.new("RGB", (1, h))
    px  = col.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        if t < 0.45:
            tt, a, b = t / 0.45, light, mid
        else:
            tt, a, b = (t - 0.45) / 0.55, mid, deep
        px[0, y] = (int(a[0]+(b[0]-a[0])*tt), int(a[1]+(b[1]-a[1])*tt), int(a[2]+(b[2]-a[2])*tt))
    return col.resize((w, h))

def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=radius, fill=255)
    return m

def gradient_panel(size, radius, top, bottom):
    g = vgradient(size, top, bottom).convert("RGBA")
    g.putalpha(rounded_mask(size, radius))
    return g

def soft_shadow(size, radius, blur, opacity=150, color=(0, 0, 0)):
    """Return (rgba_shadow, pad). Composite it at (x - pad, y - pad + dy)."""
    pad   = blur * 3
    shape = Image.new("L", size, 0)
    ImageDraw.Draw(shape).rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=radius, fill=opacity)
    full  = Image.new("L", (size[0] + 2*pad, size[1] + 2*pad), 0)
    full.paste(shape, (pad, pad))
    layer = Image.composite(Image.new("RGBA", full.size, (*color, 255)),
                            Image.new("RGBA", full.size, (*color, 0)), full)
    return layer.filter(ImageFilter.GaussianBlur(blur)), pad

def text_size(font, text):
    b = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    return b[2]-b[0], b[3]-b[1], b

def fit_text(text, font, maxw):
    if text_size(font, text)[0] <= maxw:
        return text
    while text and text_size(font, text + "…")[0] > maxw:
        text = text[:-1]
    return (text + "…") if text else "…"

def gradient_text_img(text, font, metal):
    """RGBA image of `text` filled with a metallic vertical gradient."""
    tw, th, b = text_size(font, text)
    pad  = max(2, th // 6)
    size = (max(1, tw + 2*pad), max(1, th + 2*pad))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).text((pad - b[0], pad - b[1]), text, font=font, fill=255)
    grad = metal_gradient(size, metal).convert("RGBA")
    grad.putalpha(mask)
    return grad

def draw_text_shadow(base, xy, text, font, fill, off=2, shadow=(0, 0, 0, 150)):
    d = ImageDraw.Draw(base)
    d.text((xy[0]+off, xy[1]+off), text, font=font, fill=shadow)
    d.text(xy, text, font=font, fill=fill)

@lru_cache(maxsize=None)
def get_font(size, bold=False):
    # Cached: the same (size, bold) reuses one font object instead of re-reading disk.
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in (candidates_bold if bold else candidates):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def metal_badge(base, cx, cy, r, metal, label, label_fill=(38, 26, 8, 255), glow=False):
    """Circular metallic badge: gradient fill, rim, top highlight, centered label."""
    d = int(2 * r)
    if glow:
        g, pad = soft_shadow((d, d), r, blur=max(3, r // 2), opacity=180, color=metal[1])
        composite_at(base, g, cx - d/2 - pad, cy - d/2 - pad)
    grad = metal_gradient((d, d), metal).convert("RGBA")
    grad.putalpha(rounded_mask((d, d), r))
    composite_at(base, grad, cx - r, cy - r)
    dr = ImageDraw.Draw(base)
    dr.ellipse([cx-r, cy-r, cx+r-1, cy+r-1], outline=(255, 240, 205, 150), width=max(1, int(r//12)))
    dr.arc([cx-r+r//6, cy-r+r//6, cx+r-r//6, cy+r-r//6], 198, 342,
           fill=(255, 255, 255, 120), width=max(1, int(r//9)))
    font = get_font(max(9, int(r)), bold=True)
    tw, th, b = text_size(font, label)
    dr.text((cx - tw/2 - b[0], cy - th/2 - b[1]), label, font=font, fill=label_fill)

def crown_img(w, metal):
    """A metallic 3-point crown (drawn, not a font glyph) as an RGBA image."""
    h    = max(8, int(w * 0.82))
    mask = Image.new("L", (w, h), 0)
    d    = ImageDraw.Draw(mask)
    pts  = [(0.06*w, 0.80*h), (0.06*w, 0.34*h), (0.27*w, 0.54*h), (0.50*w, 0.16*h),
            (0.73*w, 0.54*h), (0.94*w, 0.34*h), (0.94*w, 0.80*h)]
    d.polygon([(int(x), int(y)) for x, y in pts], fill=255)
    d.rectangle([int(0.06*w), int(0.70*h), int(0.94*w), int(0.84*h)], fill=255)
    for fx, fy in ((0.06, 0.34), (0.50, 0.16), (0.94, 0.34)):
        r = max(2, int(0.06*w))
        d.ellipse([int(fx*w)-r, int(fy*h)-r, int(fx*w)+r, int(fy*h)+r], fill=255)
    grad = metal_gradient((w, h), metal).convert("RGBA")
    grad.putalpha(mask)
    return grad

def diamond_img(s, metal):
    """A small metallic diamond (rotated square) as an RGBA image."""
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon([(s/2, 0), (s, s/2), (s/2, s), (0, s/2)], fill=255)
    g = metal_gradient((s, s), metal).convert("RGBA")
    g.putalpha(mask)
    return g

# ─────────────────────────────────────────
#  AVATAR HELPERS
# ─────────────────────────────────────────

async def fetch_avatar_bytes(bot, uid: int) -> bytes | None:
    """Download a user's current profile photo (largest size). Cached for AVATAR_TTL.
    Returns None on privacy restrictions / no photo / any error — callers fall back."""
    now    = time.time()
    cached = AVATAR_CACHE.get(uid)
    if cached and now - cached[0] < AVATAR_TTL:
        return cached[1]
    raw = None
    try:
        photos = await bot.get_user_profile_photos(uid, limit=1)
        if photos.total_count and photos.photos:
            largest = photos.photos[0][-1]            # biggest PhotoSize of the first photo
            f       = await bot.get_file(largest.file_id)
            raw     = bytes(await f.download_as_bytearray())
    except Exception:
        raw = None
    AVATAR_CACHE[uid] = (now, raw)
    return raw

def make_circular_avatar(raw: bytes, size: int) -> Image.Image:
    """Crop image bytes into a circular RGBA avatar of the given diameter."""
    av   = Image.open(BytesIO(raw)).convert("RGBA")
    av   = ImageOps.fit(av, (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    av.putalpha(mask)
    return av

def make_initials_avatar(name: str, uid, size: int) -> Image.Image:
    """Charcoal disc with a gold-gradient initial — fallback when no photo exists."""
    av = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(av).ellipse([0, 0, size - 1, size - 1], fill=(30, 27, 20, 255))
    letter = (name.lstrip("@")[:1] or "?").upper()
    g = gradient_text_img(letter, get_font(int(size * 0.52), bold=True), GOLD_M)
    paste_center(av, g, size / 2, size / 2)
    return av

def avatar_image(raw, name, uid, size: int) -> Image.Image:
    """Circular photo if bytes are present, else an initials avatar. Never raises."""
    if raw:
        try:
            return make_circular_avatar(raw, size)
        except Exception:
            pass
    return make_initials_avatar(name, uid, size)

def place_avatar(base, raw, name, uid, cx, cy, d, metal, glow=False):
    """Composite a circular avatar at (cx, cy) inside a metallic ring (+ optional glow)."""
    ring_w = max(3, d // 14)
    outer  = d + ring_w * 2
    if glow:
        g, pad = soft_shadow((outer, outer), outer // 2, blur=max(5, d // 10), opacity=85, color=metal[1])
        composite_at(base, g, cx - outer/2 - pad, cy - outer/2 - pad)
    ring  = metal_gradient((outer, outer), metal).convert("RGBA")
    rmask = Image.new("L", (outer, outer), 0)
    md    = ImageDraw.Draw(rmask)
    md.ellipse([0, 0, outer-1, outer-1], fill=255)
    md.ellipse([ring_w, ring_w, outer-1-ring_w, outer-1-ring_w], fill=0)
    ring.putalpha(rmask)
    composite_at(base, ring, cx - outer/2, cy - outer/2)
    composite_at(base, avatar_image(raw, name, uid, d), cx - d/2, cy - d/2)

# ─────────────────────────────────────────
#  RANK CARD IMAGE  (/myrank)
# ─────────────────────────────────────────

def make_rank_card(username: str, cash: int, rank: int, total: int,
                   avatar_raw: bytes | None = None, uid=0) -> BytesIO:
    S      = 2                          # supersample, downscaled at the end
    W, H   = 720 * S, 280 * S
    metal  = rank_metal(rank)

    img = vgradient((W, H), BG_TOP, BG_BOT).convert("RGBA")

    # outer panel: drop shadow + gradient fill + gold hairline
    m      = 18 * S
    pw, ph = W - 2*m, H - 2*m
    rad    = 26 * S
    sh, pad = soft_shadow((pw, ph), rad, blur=9*S, opacity=140)
    composite_at(img, sh, m - pad, m - pad + 4*S)
    composite_at(img, gradient_panel((pw, ph), rad, PANEL_TOP, PANEL_BOT), m, m)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([m, m, m+pw-1, m+ph-1], radius=rad, outline=(*HAIR, 110), width=max(1, S))

    # metallic accent bar (left)
    bar = metal_gradient((6*S, ph - 28*S), metal).convert("RGBA")
    bar.putalpha(rounded_mask(bar.size, 3*S))
    composite_at(img, bar, m + 14*S, m + 14*S)

    # avatar + corner rank badge
    av_d  = 108 * S
    av_cx = m + 34*S + av_d // 2
    av_cy = H // 2
    place_avatar(img, avatar_raw, username, uid, av_cx, av_cy, av_d, metal, glow=(rank == 1))
    br = 18 * S
    metal_badge(img, av_cx + av_d//2 - br, av_cy + av_d//2 - br, br, metal, str(rank))

    # text column
    tx = av_cx + av_d//2 + 30*S
    pr = W - m - 24*S

    nfont = get_font(30*S, bold=True)
    draw_text_shadow(img, (tx, m + 22*S), fit_text(username[:26], nfont, pr - tx), nfont, INK, off=2*S)

    draw.text((tx, m + 70*S), f"RANK {rank} OF {total}", fill=MUTE, font=get_font(13*S, bold=True))
    draw.line([tx, m + 100*S, pr, m + 100*S], fill=(*HAIR, 70), width=max(1, S))

    # cash — gold gradient with a diamond marker
    gnum    = gradient_text_img(f"${fmt(cash)}", get_font(34*S, bold=True), GOLD_M)
    diamond = diamond_img(20*S, GOLD_M)
    cash_y  = m + 116*S
    composite_at(img, diamond, tx, cash_y + (gnum.height - diamond.height)//2)
    composite_at(img, gnum, tx + diamond.width + 12*S, cash_y)

    # progress bar — position within the board
    bx1, bx2 = tx, pr
    by1, by2 = H - m - 50*S, H - m - 30*S
    barh     = by2 - by1
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=barh//2, fill=(44, 39, 28, 255))
    progress = 1 - ((rank - 1) / max(total - 1, 1))
    fillw    = int((bx2 - bx1) * max(progress, 0.05))
    if fillw >= barh:
        fb = metal_gradient((fillw, barh), GOLD_M).convert("RGBA")
        fb.putalpha(rounded_mask((fillw, barh), barh//2))
        composite_at(img, fb, bx1, by1)
    lf = get_font(11*S, bold=True)
    draw.text((bx1, by2 + 5*S), "LOWEST", fill=MUTE, font=lf)
    tw, _, _ = text_size(lf, "TOP")
    draw.text((bx2 - tw, by2 + 5*S), "TOP", fill=MUTE, font=lf)

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf

# ─────────────────────────────────────────
#  LEADERBOARD IMAGE  (/leaderboard)
# ─────────────────────────────────────────

def make_leaderboard_image(members: list[tuple], admin_ids: set, avatars: dict | None = None) -> BytesIO:
    S       = 2
    top     = members[:15]
    n       = len(top)
    W       = 720 * S
    HEADER  = 100 * S
    ROW     = 72  * S
    FOOTER  = 58  * S
    H       = HEADER + n*ROW + FOOTER
    mx      = 22 * S
    avatars = avatars or {}

    img  = vgradient((W, H), BG_TOP, BG_BOT).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # ── header ──
    hp_h = HEADER - 22*S
    composite_at(img, gradient_panel((W - 2*mx, hp_h), 18*S, PANEL_TOP, PANEL_BOT), mx, 12*S)
    draw.rounded_rectangle([mx, 12*S, W-mx-1, 12*S+hp_h-1], radius=18*S, outline=(*HAIR, 110), width=max(1, S))

    crown = crown_img(42*S, GOLD_M)
    composite_at(img, crown, mx + 24*S, 30*S)
    title_x = mx + 24*S + crown.width + 18*S
    composite_at(img, gradient_text_img("LEADERBOARD", get_font(30*S, bold=True), GOLD_M), title_x, 24*S)
    draw.text((title_x + 2*S, 64*S), "TOP RANKED MEMBERS", fill=MUTE, font=get_font(12*S, bold=True))

    date_str = datetime.now().strftime("%d %b %Y").upper()
    df = get_font(12*S, bold=True)
    dtw, _, _ = text_size(df, date_str)
    draw.text((W - mx - 22*S - dtw, 42*S), date_str, fill=MUTE, font=df)

    # ── rows ──
    for i, (uid, user) in enumerate(top):
        y0       = HEADER + i*ROW
        ry1, ry2 = y0 + 6*S, y0 + ROW - 6*S
        rh       = ry2 - ry1
        cy       = (ry1 + ry2) // 2
        is_adm   = int(uid) in admin_ids
        metal    = rank_metal(i + 1)

        # row panel
        if i < 3:
            tint = {0: (46, 38, 20), 1: (40, 41, 45), 2: (44, 33, 22)}[i]
            composite_at(img, gradient_panel((W - 2*mx, rh), 14*S, tint, PANEL_BOT), mx, ry1)
            draw.rounded_rectangle([mx, ry1, W-mx-1, ry2-1], radius=14*S, outline=(*metal[1], 160), width=max(1, S))
            bar = metal_gradient((5*S, rh - 16*S), metal).convert("RGBA")
            bar.putalpha(rounded_mask(bar.size, 2*S))
            composite_at(img, bar, mx + 8*S, ry1 + 8*S)
        else:
            base = (26, 23, 17) if i % 2 == 0 else (20, 18, 13)
            composite_at(img, gradient_panel((W - 2*mx, rh), 14*S, base, PANEL_BOT), mx, ry1)
            draw.rounded_rectangle([mx, ry1, W-mx-1, ry2-1], radius=14*S, outline=(*HAIR, 45), width=1)

        # avatar + corner rank badge
        av_d  = 50 * S
        av_cx = mx + 26*S + av_d//2
        place_avatar(img, avatars.get(uid), user["name"], uid, av_cx, cy, av_d, metal, glow=(i == 0))
        br = 13 * S
        metal_badge(img, av_cx + av_d//2 - br + 2*S, cy + av_d//2 - br + 2*S, br, metal, str(i + 1))

        # name (gold + crown for admins)
        nx    = av_cx + av_d//2 + 24*S
        if is_adm:
            ad_crown = crown_img(20*S, GOLD_M)
            composite_at(img, ad_crown, nx, cy - ad_crown.height//2)
            nx += ad_crown.width + 10*S
        nmaxw = (W - mx - 210*S) - nx
        nfont = get_font(17*S, bold=True)
        ncol  = (247, 226, 150) if is_adm else INK
        draw_text_shadow(img, (nx, cy - 13*S), fit_text(user["name"][:28], nfont, nmaxw), nfont, ncol, off=S)

        # cash (right-aligned, gold gradient)
        gimg = gradient_text_img(f"${fmt(user['cash'])}", get_font(17*S, bold=True),
                                 GOLD_M if i < 3 else GOLDDIM_M)
        composite_at(img, gimg, W - mx - 22*S - gimg.width, cy - gimg.height//2)

    # ── footer ──
    fy = HEADER + n*ROW + 6*S
    composite_at(img, gradient_panel((W - 2*mx, FOOTER - 14*S), 12*S, PANEL_TOP, PANEL_BOT), mx, fy)
    draw.line([mx + 16*S, fy - 4*S, W - mx - 16*S, fy - 4*S], fill=(*HAIR, 60), width=1)
    draw.text((mx + 22*S, fy + 12*S), "Keep climbing — the next rank is yours.",
              fill=MUTE, font=get_font(12*S, bold=True))
    wm = gradient_text_img("RANKING BOT", get_font(13*S, bold=True), GOLD_M)
    composite_at(img, wm, W - mx - 22*S - wm.width, fy + 11*S)

    img = img.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf

# ─────────────────────────────────────────
#  COMMANDS  —  PUBLIC
# ─────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Ranking Bot*\n\n"
        "*Member commands:*\n"
        "/leaderboard — view the full ranking\n"
        "/myrank — see your rank card\n"
        "/rank @user — check someone else's rank\n"
        "/top3 — quick top 3 shoutout\n\n"
        "*Admin commands:*\n"
        "/setcash @user <amount> — set a member's amount\n"
        "/addcash @user <amount> — add to a member's amount\n"
        "/removecash @user <amount> — deduct from a member's amount\n"
        "/resetmember @user — zero out a member\n"
        "/resetboard — wipe the entire board",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data["users"]:
        await update.message.reply_text("The leaderboard is empty. Admins can use /setcash to add members.")
        return

    admins    = await update.effective_chat.get_administrators()
    admin_ids = {a.user.id for a in admins}
    members   = sorted_members(data)

    top     = members[:15]
    raws    = await asyncio.gather(*(fetch_avatar_bytes(context.bot, int(uid)) for uid, _ in top))
    avatars = {uid: raw for (uid, _), raw in zip(top, raws)}

    async with RENDER_SEM:
        img_buf = await asyncio.to_thread(make_leaderboard_image, members, admin_ids, avatars)
    await update.message.reply_photo(
        photo=img_buf,
        caption=f"🏆 *Leaderboard* — {len(members)} members",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_myrank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    data    = load_data()
    uid_str = str(user.id)

    if uid_str not in data["users"]:
        await update.message.reply_text("You're not on the board yet. Ask an admin to add you.")
        return

    udata   = data["users"][uid_str]
    members = sorted_members(data)
    rank    = next(i + 1 for i, (uid, _) in enumerate(members) if uid == uid_str)
    total   = len(members)

    avatar = await fetch_avatar_bytes(context.bot, user.id)
    async with RENDER_SEM:
        img_buf = await asyncio.to_thread(
            make_rank_card, display_name(user), udata["cash"], rank, total, avatar, user.id
        )
    await update.message.reply_photo(
        photo=img_buf,
        caption=f"*{display_name(user)}* — {rank_emoji(rank)} Rank {rank} of {total}  |  {CURRENCY} {fmt(udata['cash'])}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check someone else's rank by replying or tagging: /rank @username"""
    data    = load_data()
    uid_str = None
    name    = None

    # reply style
    if update.message.reply_to_message:
        t       = update.message.reply_to_message.from_user
        uid_str = str(t.id)
        name    = display_name(t)
    # tag style: /rank @username
    elif context.args:
        tag = context.args[0].lstrip("@")
        for uid, u in data["users"].items():
            if u["name"].lstrip("@").lower() == tag.lower():
                uid_str = uid
                name    = u["name"]
                break
        if not uid_str:
            await update.message.reply_text(f"❌ @{tag} isn't on the board yet.")
            return
    else:
        await update.message.reply_text("Usage: `/rank @username`  or reply to their message + `/rank`", parse_mode=ParseMode.MARKDOWN)
        return

    if uid_str not in data["users"]:
        await update.message.reply_text(f"{name} isn't on the board yet.")
        return

    udata   = data["users"][uid_str]
    members = sorted_members(data)
    rank    = next(i + 1 for i, (uid, _) in enumerate(members) if uid == uid_str)
    total   = len(members)

    avatar = await fetch_avatar_bytes(context.bot, int(uid_str))
    async with RENDER_SEM:
        img_buf = await asyncio.to_thread(
            make_rank_card, name, udata["cash"], rank, total, avatar, int(uid_str)
        )
    await update.message.reply_photo(
        photo=img_buf,
        caption=f"*{name}* — {rank_emoji(rank)} Rank {rank} of {total}  |  ${fmt(udata['cash'])}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_top3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data    = load_data()
    members = sorted_members(data)[:3]
    if not members:
        await update.message.reply_text("No one on the board yet.")
        return

    lines = ["🏆 *Top 3*\n"]
    for i, (_, u) in enumerate(members):
        lines.append(f"{rank_emoji(i+1)} *{u['name']}* — ${fmt(u['cash'])}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────
#  COMMANDS  —  ADMIN ONLY
# ─────────────────────────────────────────

async def cmd_setcash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admins only.")
        return
    uid, name, amount = await resolve_target(update, context, context.args)
    if uid is None:
        await update.message.reply_text("Usage: `/setcash 5000 @username`  or reply to a message + `/setcash 5000`", parse_mode=ParseMode.MARKDOWN)
        return
    if amount < 0:
        await update.message.reply_text("Amount must be a non-negative number.")
        return
    if uid == -1:
        await update.message.reply_text(f"❌ {name} hasn't messaged in the group yet — can't find them. Have them send a message first.")
        return
    async with DATA_LOCK:
        data  = load_data()
        udata = get_user(data, uid, name)
        udata["cash"] = amount
        save_data(data)
        members = sorted_members(data)
        rank    = next(i + 1 for i, (u, _) in enumerate(members) if u == str(uid))
    await update.message.reply_text(
        f"✅ *{name}* set to *${fmt(amount)}*  —  now rank #{rank}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_addcash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admins only.")
        return
    uid, name, amount = await resolve_target(update, context, context.args)
    if uid is None:
        await update.message.reply_text("Usage: `/addcash 5000 @username`  or reply to a message + `/addcash 5000`", parse_mode=ParseMode.MARKDOWN)
        return
    if amount <= 0:
        await update.message.reply_text("Amount must be a positive number.")
        return
    if uid == -1:
        await update.message.reply_text(f"❌ {name} hasn't messaged in the group yet — can't find them. Have them send a message first.")
        return
    async with DATA_LOCK:
        data  = load_data()
        udata = get_user(data, uid, name)
        udata["cash"] += amount
        save_data(data)
        members = sorted_members(data)
        rank    = next(i + 1 for i, (u, _) in enumerate(members) if u == str(uid))
    await update.message.reply_text(
        f"✅ Added *${fmt(amount)}* to *{name}*\nNew total: *${fmt(udata['cash'])}*  —  rank #{rank}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_removecash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admins only.")
        return
    uid, name, amount = await resolve_target(update, context, context.args)
    if uid is None:
        await update.message.reply_text("Usage: `/removecash 5000 @username`  or reply to a message + `/removecash 5000`", parse_mode=ParseMode.MARKDOWN)
        return
    if amount <= 0:
        await update.message.reply_text("Amount must be a positive number.")
        return
    if uid == -1:
        await update.message.reply_text(f"❌ {name} hasn't messaged in the group yet — can't find them. Have them send a message first.")
        return
    async with DATA_LOCK:
        data  = load_data()
        udata = get_user(data, uid, name)
        udata["cash"] = max(0, udata["cash"] - amount)
        save_data(data)
        members = sorted_members(data)
        rank    = next(i + 1 for i, (u, _) in enumerate(members) if u == str(uid))
    await update.message.reply_text(
        f"✅ Removed *${fmt(amount)}* from *{name}*\nNew total: *${fmt(udata['cash'])}*  —  rank #{rank}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_resetmember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admins only.")
        return
    # resetmember has no amount — handle tag or reply separately
    target_user = None
    target_name = None
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
        target_user = str(t.id)
        target_name = display_name(t)
    elif context.args:
        tag = context.args[0].lstrip("@")
        data = load_data()
        for uid, u in data["users"].items():
            if u["name"].lstrip("@").lower() == tag.lower():
                target_user = uid
                target_name = u["name"]
                break
        if not target_user:
            await update.message.reply_text(f"❌ @{tag} not found. Have them send a message first.")
            return
    else:
        await update.message.reply_text("Usage: `/resetmember @username`  or reply to their message + `/resetmember`", parse_mode=ParseMode.MARKDOWN)
        return
    async with DATA_LOCK:
        data = load_data()
        if target_user in data["users"]:
            data["users"][target_user]["cash"] = 0
            save_data(data)
    await update.message.reply_text(
        f"✅ *{target_name}* has been reset to $0.",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_resetboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admins only.")
        return
    keyboard = [[
        InlineKeyboardButton("✅ Yes, reset everything", callback_data="reset_confirm"),
        InlineKeyboardButton("❌ Cancel",                callback_data="reset_cancel"),
    ]]
    await update.message.reply_text(
        "⚠️ *This will wipe ALL member data permanently.* Are you sure?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(update, context):
        await query.edit_message_text("❌ Admins only.")
        return
    if query.data == "reset_confirm":
        async with DATA_LOCK:
            DATA["users"].clear()
            save_data()
        await query.edit_message_text("🗑️ Leaderboard wiped.")
    else:
        await query.edit_message_text("Reset cancelled.")

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    init_data()
    # Generous timeouts: the route to api.telegram.org can be slow/throttled,
    # and the default 5s connect timeout intermittently fails the TLS handshake.
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )

    # public
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("myrank",      cmd_myrank))
    app.add_handler(CommandHandler("rank",        cmd_rank))
    app.add_handler(CommandHandler("top3",        cmd_top3))

    # admin
    app.add_handler(CommandHandler("setcash",     cmd_setcash))
    app.add_handler(CommandHandler("addcash",     cmd_addcash))
    app.add_handler(CommandHandler("removecash",  cmd_removecash))
    app.add_handler(CommandHandler("resetmember", cmd_resetmember))
    app.add_handler(CommandHandler("resetboard",  cmd_resetboard))
    app.add_handler(CallbackQueryHandler(reset_callback, pattern="^reset_"))

    print("🤖 Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()