import os
import json
import asyncio
import math
from datetime import datetime
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
BOT_TOKEN  = os.getenv("BOT_TOKEN", "8805361777:AAHGWv_lymVdm7U9dR4rWAoPs4tK4NPsFRo")
DATA_FILE  = "data.json"
CURRENCY   = "💰"

# ─────────────────────────────────────────
#  DATA LAYER
# ─────────────────────────────────────────

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"users": {}}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

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

def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def draw_rounded_rect(draw, xy, radius, fill, border=None, border_width=2):
    x1, y1, x2, y2 = xy
    r = radius
    draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
    draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
    draw.ellipse([x1, y1, x1 + 2*r, y1 + 2*r], fill=fill)
    draw.ellipse([x2 - 2*r, y1, x2, y1 + 2*r], fill=fill)
    draw.ellipse([x1, y2 - 2*r, x1 + 2*r, y2], fill=fill)
    draw.ellipse([x2 - 2*r, y2 - 2*r, x2, y2], fill=fill)
    if border:
        for i in range(border_width):
            draw.arc([x1+i, y1+i, x1+2*r-i, y1+2*r-i], 180, 270, fill=border)
            draw.arc([x2-2*r+i, y1+i, x2-i, y1+2*r-i], 270, 360, fill=border)
            draw.arc([x1+i, y2-2*r+i, x1+2*r-i, y2-i], 90, 180, fill=border)
            draw.arc([x2-2*r+i, y2-2*r+i, x2-i, y2-i], 0, 90, fill=border)
            draw.line([x1+r, y1+i, x2-r, y1+i], fill=border)
            draw.line([x1+r, y2-i, x2-r, y2-i], fill=border)
            draw.line([x1+i, y1+r, x1+i, y2-r], fill=border)
            draw.line([x2-i, y1+r, x2-i, y2-r], fill=border)

def draw_noise_bg(img, base_color, amount=18):
    import random
    px = img.load()
    w, h = img.size
    r0, g0, b0 = base_color
    for _ in range(w * h // amount):
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        v = random.randint(-12, 12)
        r = max(0, min(255, r0 + v))
        g = max(0, min(255, g0 + v))
        b = max(0, min(255, b0 + v))
        px[x, y] = (r, g, b, 255)

def get_font(size, bold=False):
    # Try to load a system font, fall back to default
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

def draw_medal(draw, cx, cy, rank, r=22):
    """Draw a circular medal badge."""
    colors = {1: ("#FFB800", "#7A5500"), 2: ("#A8A8A8", "#4A4A4A"), 3: ("#CD7F32", "#6B3A1F")}
    fill, shadow = colors.get(rank, ("#2A2A4A", "#111128"))
    # shadow
    draw.ellipse([cx - r + 2, cy - r + 2, cx + r + 2, cy + r + 2], fill=shadow)
    # circle
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    # number
    font = get_font(18, bold=True)
    txt = str(rank)
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 1), txt, fill="#ffffff", font=font)

def draw_crown_badge(draw, cx, cy, r=22):
    """Draw a crown badge for admins."""
    draw.ellipse([cx - r + 2, cy - r + 2, cx + r + 2, cy + r + 2], fill="#5A4000")
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#FFB800")
    font = get_font(18, bold=True)
    bbox = draw.textbbox((0, 0), "👑", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 1), "♛", fill="#ffffff", font=font)

def draw_trophy(draw, x, y, size=28):
    """Simple trophy shape drawn with PIL."""
    c = "#FFB800"
    # cup body
    draw.ellipse([x, y, x + size, y + int(size * 0.8)], fill=c)
    draw.rectangle([x + int(size * 0.1), y + int(size * 0.35), x + int(size * 0.9), y + int(size * 0.65)], fill=c)
    # stem
    sw = int(size * 0.18)
    draw.rectangle([x + size // 2 - sw, y + int(size * 0.65), x + size // 2 + sw, y + int(size * 0.9)], fill=c)
    # base
    draw.rectangle([x + int(size * 0.1), y + int(size * 0.88), x + int(size * 0.9), y + size], fill=c)
    # handles
    hw = int(size * 0.15)
    draw.arc([x - hw, y + int(size * 0.1), x + hw, y + int(size * 0.55)], 270, 90, fill=c, width=3)
    draw.arc([x + size - hw, y + int(size * 0.1), x + size + hw, y + int(size * 0.55)], 90, 270, fill=c, width=3)

# ─────────────────────────────────────────
#  RANK CARD IMAGE  (/myrank)
# ─────────────────────────────────────────

def make_rank_card(username: str, cash: int, rank: int, total: int) -> BytesIO:
    W, H    = 700, 260
    BG      = (13, 13, 30)
    CARD_BG = (20, 20, 46)
    ACCENT  = (99, 179, 237)   # blue
    GREEN   = (74, 222, 128)

    img  = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(img)
    draw_noise_bg(img, BG, amount=25)

    # outer card
    draw_rounded_rect(draw, (24, 24, W - 24, H - 24), 18, fill=(*CARD_BG, 255), border=(*ACCENT, 100), border_width=2)

    # left accent bar
    draw.rectangle([24, 24, 30, H - 24], fill=(*ACCENT, 220))

    # rank badge
    draw_medal(draw, 80, H // 2, rank)

    # username
    ufont = get_font(26, bold=True)
    draw.text((120, 70), username[:26], fill="#ffffff", font=ufont)

    # cash
    cfont = get_font(22, bold=True)
    draw.text((120, 110), f"${fmt(cash)}", fill=GREEN, font=cfont)

    # rank text
    rfont = get_font(14)
    draw.text((120, 148), f"Rank {rank} of {total}", fill="#8899aa", font=rfont)

    # progress bar
    BAR_X1, BAR_X2 = 120, W - 50
    BAR_Y1, BAR_Y2 = 185, 205
    draw_rounded_rect(draw, (BAR_X1, BAR_Y1, BAR_X2, BAR_Y2), 8, fill=(40, 40, 70, 255))
    progress  = 1 - ((rank - 1) / max(total - 1, 1))
    fill_w    = int((BAR_X2 - BAR_X1) * max(progress, 0.03))
    # gradient fill
    for px in range(fill_w):
        t   = px / max(fill_w - 1, 1)
        r_  = int(99  + (74  - 99)  * t)
        g_  = int(179 + (222 - 179) * t)
        b_  = int(237 + (128 - 237) * t)
        draw.rectangle([BAR_X1 + px, BAR_Y1 + 2, BAR_X1 + px + 1, BAR_Y2 - 2], fill=(r_, g_, b_, 230))

    draw.text((BAR_X1, BAR_Y2 + 6), "Lowest", fill="#445566", font=get_font(11))
    draw.text((BAR_X2 - 30, BAR_Y2 + 6), "Top", fill="#445566", font=get_font(11))

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ─────────────────────────────────────────
#  LEADERBOARD IMAGE  (/leaderboard)
# ─────────────────────────────────────────

def make_leaderboard_image(members: list[tuple], admin_ids: set) -> BytesIO:
    top      = members[:15]
    n        = len(top)
    W        = 720
    ROW_H    = 64
    HEADER_H = 110
    FOOTER_H = 60
    H        = HEADER_H + n * ROW_H + FOOTER_H

    BG       = (10, 12, 26)
    CARD_BG  = (18, 20, 40)
    ROW_A    = (22, 24, 50)
    ROW_B    = (17, 19, 42)
    GOLD     = (255, 184, 0)
    GREEN    = (74, 222, 128)
    BLUE     = (99, 179, 237)

    img  = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(img)
    draw_noise_bg(img, BG, amount=30)

    # ── header card ──
    draw_rounded_rect(draw, (20, 14, W - 20, HEADER_H - 8), 14, fill=(*CARD_BG, 255), border=(*BLUE, 80), border_width=1)

    # trophy icon
    draw_trophy(draw, 36, 28, size=34)

    # title
    draw.text((84, 26), "LEADERBOARD", fill=GOLD, font=get_font(24, bold=True))
    draw.text((86, 58), "Top Ranked Users", fill="#667788", font=get_font(14))

    # date top-right
    date_str = datetime.now().strftime("%d %b %Y").upper()
    draw.text((W - 160, 38), f"📅 {date_str}", fill="#667788", font=get_font(12))

    # ── rows ──
    for i, (uid, user) in enumerate(top):
        y0     = HEADER_H + i * ROW_H
        y1     = y0 + ROW_H - 2
        is_adm = int(uid) in admin_ids
        bg     = ROW_A if i % 2 == 0 else ROW_B

        draw_rounded_rect(draw, (20, y0 + 2, W - 20, y1), 10, fill=(*bg, 255))

        # left accent for top 3
        if i == 0:
            draw.rectangle([20, y0 + 2, 25, y1], fill=(*GOLD, 255))
        elif i == 1:
            draw.rectangle([20, y0 + 2, 25, y1], fill=(168, 168, 168, 255))
        elif i == 2:
            draw.rectangle([20, y0 + 2, 25, y1], fill=(205, 127, 50, 255))

        # medal / crown badge
        cy = y0 + ROW_H // 2
        if is_adm:
            draw_crown_badge(draw, 62, cy, r=20)
        else:
            draw_medal(draw, 62, cy, i + 1, r=20)

        # name
        name   = user["name"][:26]
        ncolor = "#FFD700" if is_adm else ("#ffffff" if i < 3 else "#ccddee")
        nfont  = get_font(16, bold=(i < 3 or is_adm))
        draw.text((100, cy - 18), name, fill=ncolor, font=nfont)

        # trophy icon for amount
        draw_trophy(draw, W - 200, cy - 14, size=16)

        # cash amount
        cash_str = f"${fmt(user['cash'])}"
        cfont    = get_font(16, bold=True)
        bbox     = draw.textbbox((0, 0), cash_str, font=cfont)
        tw       = bbox[2] - bbox[0]
        draw.text((W - 40 - tw, cy - 10), cash_str, fill=GREEN, font=cfont)

    # ── footer ──
    fy = HEADER_H + n * ROW_H + 8
    draw_rounded_rect(draw, (20, fy, W - 20, fy + FOOTER_H - 12), 10, fill=(*CARD_BG, 255))

    # bar chart icon area
    for bi, bh in enumerate([18, 28, 22, 14, 24]):
        bx = 38 + bi * 10
        draw.rectangle([bx, fy + 30 - bh, bx + 7, fy + 30], fill=(*BLUE, 180))

    draw.text((100, fy + 10), "Keep climbing.", fill="#aabbcc", font=get_font(13, bold=True))
    draw.text((100, fy + 28), "The next rank is yours.", fill="#556677", font=get_font(11))

    rbot = "RANKING BOT"
    rfont = get_font(13, bold=True)
    rb_bbox = draw.textbbox((0, 0), rbot, font=rfont)
    draw.text((W - 40 - (rb_bbox[2] - rb_bbox[0]), fy + 18), rbot, fill=(*BLUE, 200), font=rfont)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
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

    img_buf = make_leaderboard_image(members, admin_ids)
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

    img_buf = make_rank_card(display_name(user), udata["cash"], rank, total)
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

    img_buf = make_rank_card(name, udata["cash"], rank, total)
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
        lines.append(f"{rank_emoji(i+1)} *{u['name']}* — {CURRENCY} {fmt(u['cash'])}")
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
        save_data({"users": {}})
        await query.edit_message_text("🗑️ Leaderboard wiped.")
    else:
        await query.edit_message_text("Reset cancelled.")

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

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