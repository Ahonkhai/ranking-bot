"""Drawing primitives.

The gradient builders walk a one-pixel column in Python and are called well
over a hundred times per leaderboard — page background, header panel, crown,
title fill, then per row a panel, an accent bar, an avatar ring, a badge disc,
a badge glow and a cash fill. The overwhelming majority of those calls pass
identical arguments, so the column is built once and reused; stretching a
cached 1×h column to full width is a C-level resize.

Anything returned from a cached function here is treated as read-only by every
caller: they `.convert()` or `.crop()` first, both of which produce a new
image, so the shared instance is never mutated.
"""

import math
import os
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

_FONT_DIR = Path(__file__).resolve().parents[2] / "fonts"


# ── fonts ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def get_font(size: int, bold: bool = False):
    candidates_bold = [
        _FONT_DIR / "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    candidates = [
        _FONT_DIR / "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in (candidates_bold if bold else candidates):
        if os.path.exists(path):
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


_MEASURE = ImageDraw.Draw(Image.new("L", (1, 1)))


@lru_cache(maxsize=4096)
def text_size(font, text: str):
    b = _MEASURE.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1], b


def fit_text(text: str, font, maxw: int) -> str:
    """Truncate with an ellipsis to fit `maxw`.

    Binary search rather than shaving one character at a time — long names used
    to cost a text measurement per character removed.
    """
    if not text:
        return ""
    if text_size(font, text)[0] <= maxw:
        return text
    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid] + "…"
        if text_size(font, candidate)[0] <= maxw:
            best, lo = candidate, mid + 1
        else:
            hi = mid - 1
    return best or "…"


# ── compositing ──────────────────────────────────────────────────────────

def composite_at(base, overlay, x, y) -> None:
    """Alpha-composite `overlay` onto `base` at (x, y), clipping anything
    off-canvas so blurred shadows that bleed past the edge just work."""
    x, y = int(round(x)), int(round(y))
    bw, bh = base.size
    ow, oh = overlay.size
    cx0, cy0 = max(0, -x), max(0, -y)
    cx1, cy1 = min(ow, bw - x), min(oh, bh - y)
    if cx0 >= cx1 or cy0 >= cy1:
        return
    region = (overlay.crop((cx0, cy0, cx1, cy1))
              if (cx0, cy0, cx1, cy1) != (0, 0, ow, oh) else overlay)
    base.alpha_composite(region, (x + cx0, y + cy0))


def paste_center(base, overlay, cx, cy) -> None:
    composite_at(base, overlay, cx - overlay.width / 2, cy - overlay.height / 2)


# ── gradients ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
def _v_column(h: int, top: tuple, bottom: tuple):
    """1×h vertical two-stop ramp."""
    col = Image.new("RGB", (1, h))
    px = col.load()
    span = max(h - 1, 1)
    for y in range(h):
        t = y / span
        px[0, y] = (int(top[0] + (bottom[0] - top[0]) * t),
                    int(top[1] + (bottom[1] - top[1]) * t),
                    int(top[2] + (bottom[2] - top[2]) * t))
    return col


@lru_cache(maxsize=1024)
def _metal_column(h: int, metal: tuple):
    """1×h metallic ramp: light -> mid (bright band at 45%) -> deep."""
    light, mid, deep = metal
    col = Image.new("RGB", (1, h))
    px = col.load()
    span = max(h - 1, 1)
    for y in range(h):
        t = y / span
        if t < 0.45:
            tt, a, b = t / 0.45, light, mid
        else:
            tt, a, b = (t - 0.45) / 0.55, mid, deep
        px[0, y] = (int(a[0] + (b[0] - a[0]) * tt),
                    int(a[1] + (b[1] - a[1]) * tt),
                    int(a[2] + (b[2] - a[2]) * tt))
    return col


# Stretching a cached column still costs a resize per call, and a board asks
# for the same small ramps (badges, rings, accent bars) once per row. Caching
# the finished image skips that too. Only small ones — a full-page background
# would dominate the cache for a single reuse.
_FULL_CACHE_PIXELS = 250_000


@lru_cache(maxsize=192)
def _v_full(size: tuple, top: tuple, bottom: tuple):
    return _v_column(size[1], top, bottom).resize(size)


@lru_cache(maxsize=192)
def _metal_full(size: tuple, metal: tuple):
    return _metal_column(size[1], metal).resize(size)


def vgradient(size, top, bottom):
    """Read-only: every caller `.convert()`s before drawing, which copies."""
    size = (int(size[0]), int(size[1]))
    top, bottom = tuple(top), tuple(bottom)
    if size[0] * size[1] <= _FULL_CACHE_PIXELS:
        return _v_full(size, top, bottom)
    return _v_column(size[1], top, bottom).resize(size)


def metal_gradient(size, metal):
    """Read-only: every caller `.convert()`s before drawing, which copies."""
    size = (int(size[0]), int(size[1]))
    metal = tuple(metal)
    if size[0] * size[1] <= _FULL_CACHE_PIXELS:
        return _metal_full(size, metal)
    return _metal_column(size[1], metal).resize(size)


# ── shapes ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
def rounded_mask(size: tuple, radius: int):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def gradient_panel(size, radius, top, bottom):
    g = vgradient(size, top, bottom).convert("RGBA")
    g.putalpha(rounded_mask(tuple(size), radius))
    return g


@lru_cache(maxsize=512)
def soft_shadow(size: tuple, radius: int, blur: int, opacity: int = 150,
                color: tuple = (0, 0, 0)):
    """Returns (rgba_shadow, pad). Composite at (x - pad, y - pad + dy)."""
    pad = blur * 3
    shape = Image.new("L", size, 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=opacity)
    full = Image.new("L", (size[0] + 2 * pad, size[1] + 2 * pad), 0)
    full.paste(shape, (pad, pad))
    layer = Image.composite(Image.new("RGBA", full.size, (*color, 255)),
                            Image.new("RGBA", full.size, (*color, 0)), full)
    return layer.filter(ImageFilter.GaussianBlur(blur)), pad


# ── text ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def gradient_text_img(text: str, font, metal: tuple):
    """RGBA image of `text` filled with a metallic vertical gradient."""
    tw, th, b = text_size(font, text)
    pad = max(2, th // 6)
    size = (max(1, tw + 2 * pad), max(1, th + 2 * pad))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).text((pad - b[0], pad - b[1]), text, font=font, fill=255)
    grad = metal_gradient(size, metal).convert("RGBA")
    grad.putalpha(mask)
    return grad


def draw_text_shadow(base, xy, text, font, fill, off=2, shadow=(0, 0, 0, 150)) -> None:
    d = ImageDraw.Draw(base)
    d.text((xy[0] + off, xy[1] + off), text, font=font, fill=shadow)
    d.text(xy, text, font=font, fill=fill)


# ── ornaments ────────────────────────────────────────────────────────────

def metal_badge(base, cx, cy, r, metal, label, label_fill=(38, 26, 8, 255),
                glow=False) -> None:
    """Circular metallic badge: gradient fill, rim, top highlight, label."""
    d = int(2 * r)
    if glow:
        g, pad = soft_shadow((d, d), int(r), blur=max(3, int(r // 2)),
                             opacity=180, color=tuple(metal[1]))
        composite_at(base, g, cx - d / 2 - pad, cy - d / 2 - pad)
    grad = metal_gradient((d, d), metal).convert("RGBA")
    grad.putalpha(rounded_mask((d, d), int(r)))
    composite_at(base, grad, cx - r, cy - r)
    dr = ImageDraw.Draw(base)
    dr.ellipse([cx - r, cy - r, cx + r - 1, cy + r - 1],
               outline=(255, 240, 205, 150), width=max(1, int(r // 12)))
    dr.arc([cx - r + r // 6, cy - r + r // 6, cx + r - r // 6, cy + r - r // 6],
           198, 342, fill=(255, 255, 255, 120), width=max(1, int(r // 9)))
    # Shrink the label so two- and three-digit ranks stay inside the disc.
    size = max(9, int(r * (1.0 if len(label) <= 1 else 0.82 if len(label) == 2 else 0.62)))
    font = get_font(size, bold=True)
    tw, th, b = text_size(font, label)
    dr.text((cx - tw / 2 - b[0], cy - th / 2 - b[1]), label, font=font, fill=label_fill)


@lru_cache(maxsize=64)
def crown_img(w: int, metal: tuple):
    """A metallic three-point crown, drawn rather than taken from a font."""
    h = max(8, int(w * 0.82))
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    pts = [(0.06 * w, 0.80 * h), (0.06 * w, 0.34 * h), (0.27 * w, 0.54 * h),
           (0.50 * w, 0.16 * h), (0.73 * w, 0.54 * h), (0.94 * w, 0.34 * h),
           (0.94 * w, 0.80 * h)]
    d.polygon([(int(x), int(y)) for x, y in pts], fill=255)
    d.rectangle([int(0.06 * w), int(0.70 * h), int(0.94 * w), int(0.84 * h)], fill=255)
    for fx, fy in ((0.06, 0.34), (0.50, 0.16), (0.94, 0.34)):
        r = max(2, int(0.06 * w))
        d.ellipse([int(fx * w) - r, int(fy * h) - r,
                   int(fx * w) + r, int(fy * h) + r], fill=255)
    grad = metal_gradient((w, h), metal).convert("RGBA")
    grad.putalpha(mask)
    return grad


@lru_cache(maxsize=64)
def diamond_img(s: int, metal: tuple):
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon([(s / 2, 0), (s, s / 2), (s / 2, s), (0, s / 2)], fill=255)
    g = metal_gradient((s, s), metal).convert("RGBA")
    g.putalpha(mask)
    return g


@lru_cache(maxsize=64)
def chevron_img(w: int, color: tuple, up: bool = True):
    """Small solid triangle for the ▲/▼ movement indicators."""
    h = max(4, int(w * 0.8))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = ([(w / 2, 0), (w, h), (0, h)] if up else [(0, 0), (w, 0), (w / 2, h)])
    d.polygon(pts, fill=(*color, 255))
    return img


@lru_cache(maxsize=64)
def arrow_img(w: int, color: tuple, up: bool = True):
    """Stemmed ↑ / ↓ arrow, drawn rather than taken from a font.

    Font coverage for arrow glyphs is inconsistent and a missing glyph would
    render as a blank box in the one place the card has to be unambiguous.
    """
    h = max(8, int(w * 1.5))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stem = max(2, w // 5)
    head = w
    hh = int(h * 0.45)
    cx = w / 2
    if up:
        d.polygon([(cx, 0), (head, hh), (0, hh)], fill=(*color, 255))
        d.rectangle([cx - stem / 2, hh - stem / 2, cx + stem / 2, h], fill=(*color, 255))
    else:
        d.polygon([(cx, h), (head, h - hh), (0, h - hh)], fill=(*color, 255))
        d.rectangle([cx - stem / 2, 0, cx + stem / 2, h - hh + stem / 2], fill=(*color, 255))
    return img


def tracked_width(font, text: str, tracking: int) -> int:
    """Width of `text` once `tracking` extra pixels sit between characters."""
    if not text:
        return 0
    return sum(text_size(font, ch)[0] for ch in text) + tracking * (len(text) - 1)


def draw_tracked(base, xy, text: str, font, fill, tracking: int) -> None:
    """Letter-spaced text. PIL has no tracking of its own, and the uppercase
    labels on the card need it to read as considered rather than cramped."""
    d = ImageDraw.Draw(base)
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += text_size(font, ch)[0] + tracking


@lru_cache(maxsize=32)
def radial_glow(size: tuple, color: tuple, opacity: int = 90, falloff: float = 2.2):
    """A soft elliptical pool of light.

    Built at low resolution and scaled up — the falloff is smooth enough that
    the interpolation is invisible, and it keeps the per-pixel Python loop to a
    few thousand iterations instead of millions.
    """
    small = 96
    mask = Image.new("L", (small, small), 0)
    px = mask.load()
    half = small / 2
    for y in range(small):
        dy = (y - half) / half
        for x in range(small):
            dx = (x - half) / half
            d = math.hypot(dx, dy)
            if d >= 1.0:
                continue
            px[x, y] = int(opacity * (1.0 - d) ** falloff)
    layer = Image.new("RGBA", size, (*color, 0))
    layer.putalpha(mask.resize(size, Image.BICUBIC))
    return layer


@lru_cache(maxsize=8)
def vignette(size: tuple, strength: int = 120, reach: float = 1.28):
    """Darkened corners, so the eye lands in the middle of the frame."""
    small = 96
    mask = Image.new("L", (small, small), 0)
    px = mask.load()
    half = small / 2
    for y in range(small):
        dy = (y - half) / half
        for x in range(small):
            dx = (x - half) / half
            d = min(1.0, math.hypot(dx, dy) / reach)
            px[x, y] = int(strength * d ** 2.4)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.putalpha(mask.resize(size, Image.BICUBIC))
    return layer


def reflect(source, fade_to: float = 0.42, opacity: int = 70):
    """A fading mirror image, for standing something on a polished floor."""
    w, h = source.size
    flipped = source.transpose(Image.FLIP_TOP_BOTTOM)
    keep = max(1, int(h * fade_to))
    flipped = flipped.crop((0, 0, w, keep))
    ramp = vgradient((w, keep), (opacity, opacity, opacity), (0, 0, 0)).convert("L")
    flipped.putalpha(ImageChops.multiply(flipped.getchannel("A"), ramp))
    return flipped


@lru_cache(maxsize=32)
def padlock_img(w: int, color: tuple = (30, 24, 10)):
    """Small padlock glyph, drawn so it can't fall back to a missing emoji."""
    h = int(w * 1.12)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body_top = int(h * 0.44)
    d.rounded_rectangle([int(w * 0.12), body_top, int(w * 0.88), h - 1],
                        radius=max(2, int(w * 0.14)), fill=(*color, 255))
    shackle = max(2, int(w * 0.14))
    d.arc([int(w * 0.26), int(h * 0.10), int(w * 0.74), int(h * 0.68)],
          180, 360, fill=(*color, 255), width=shackle)
    return img


def _leaf_polygon(cx, cy, length, width, rotation):
    """An almond leaf as a polygon, so it can be rotated without a resample."""
    points = []
    steps = 14
    for i in range(steps):
        a = 2 * math.pi * i / steps
        # Taper both ends to a point rather than leaving a plain ellipse.
        x = (length / 2) * math.cos(a)
        y = (width / 2) * math.sin(a) * abs(math.cos(a / 2)) ** 0.6
        px = cx + x * math.cos(rotation) - y * math.sin(rotation)
        py = cy + x * math.sin(rotation) + y * math.cos(rotation)
        points.append((px, py))
    return points


@lru_cache(maxsize=16)
def laurel_wreath(d: int, metal: tuple, gap_deg: int = 78, leaves: int = 13):
    """Two laurel branches sweeping up either side of a circle of diameter `d`.

    Returns an RGBA layer sized to the wreath; composite it centred on the
    avatar. Deterministic, so it is built once per (size, metal).
    """
    light, mid, deep = metal
    pad = max(8, int(d * 0.21))
    size = d + pad * 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    cx = cy = size / 2
    ring = d / 2 + pad * 0.40

    for side in (-1, 1):
        start, end = 90.0, 90.0 + side * (180 - gap_deg / 2)
        for i in range(leaves):
            t = i / (leaves - 1)
            angle = math.radians(start + (end - start) * t)
            # Leaves shrink towards the tip of each branch, as real laurel does.
            scale = 1.0 - 0.34 * t
            length = d * 0.25 * scale
            width = d * 0.10 * scale
            lx = cx + math.cos(angle) * ring
            ly = cy + math.sin(angle) * ring
            rotation = angle + math.pi / 2 + side * math.radians(26)
            shade = mid if i % 2 else light
            alpha = int(235 - 40 * t)
            dr.polygon(_leaf_polygon(lx, ly, length, width, rotation),
                       fill=(*shade, alpha))
            # A vein down each leaf, so the wreath reads as foliage rather
            # than a ring of flat lozenges.
            vx = math.cos(rotation) * length * 0.36
            vy = math.sin(rotation) * length * 0.36
            dr.line([(lx - vx, ly - vy), (lx + vx, ly + vy)],
                    fill=(*deep, int(alpha * 0.55)), width=max(1, int(width * 0.14)))

        # The stem the leaves grow from.
        arc_box = [cx - ring, cy - ring, cx + ring, cy + ring]
        a0, a1 = (start, end) if side > 0 else (end, start)
        dr.arc(arc_box, a0, a1, fill=(*deep, 190), width=max(1, int(d * 0.012)))

    return layer


@lru_cache(maxsize=16)
def light_burst(size: tuple, radius: int, color: tuple = (198, 162, 86),
                rays: int = 26, seed: int = 7):
    """Radiating light rays and drifting particles.

    Seeded, so it is deterministic and therefore cacheable: the backdrop is
    identical on every card and gets built once for the process.
    """
    rng = random.Random(seed)
    w, h = size
    cx, cy = w / 2, h / 2
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    for i in range(rays):
        angle = (i / rays) * 2 * math.pi + rng.uniform(-0.06, 0.06)
        inner = radius * rng.uniform(1.05, 1.25)
        length = radius * rng.uniform(0.35, 1.15)
        alpha = rng.randint(22, 74)
        width = 1 if rng.random() < 0.7 else 2
        x0, y0 = cx + math.cos(angle) * inner, cy + math.sin(angle) * inner
        x1, y1 = cx + math.cos(angle) * (inner + length), cy + math.sin(angle) * (inner + length)
        d.line([(x0, y0), (x1, y1)], fill=(*color, alpha), width=width)

    for _ in range(46):
        angle = rng.uniform(0, 2 * math.pi)
        dist = radius * rng.uniform(1.05, 2.0)
        px, py = cx + math.cos(angle) * dist, cy + math.sin(angle) * dist
        r = rng.uniform(0.8, 2.4)
        alpha = rng.randint(40, 130)
        d.ellipse([px - r, py - r, px + r, py + r], fill=(*color, alpha))

    return layer.filter(ImageFilter.GaussianBlur(0.6))
