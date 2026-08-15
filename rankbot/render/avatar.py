"""Avatar rendering: circular photo, or a gold initial when there's no photo."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageOps

from .. import caches
from .palette import GOLD_M
from .primitives import composite_at, get_font, gradient_text_img, metal_gradient, paste_center


def make_circular_avatar(raw: bytes, size: int) -> Image.Image:
    av = Image.open(BytesIO(raw)).convert("RGBA")
    av = ImageOps.fit(av, (size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    av.putalpha(mask)
    return av


def make_initials_avatar(name: str, size: int) -> Image.Image:
    """Charcoal disc with a gold-gradient initial."""
    av = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(av).ellipse([0, 0, size - 1, size - 1], fill=(30, 27, 20, 255))
    letter = (name.lstrip("@")[:1] or "?").upper()
    g = gradient_text_img(letter, get_font(int(size * 0.52), bold=True), GOLD_M)
    paste_center(av, g, size / 2, size / 2)
    return av


def initial_for(name: str) -> str:
    return (name.lstrip("@")[:1] or "?").upper()


def avatar_image(raw, name: str, uid: int, size: int) -> Image.Image:
    """Circular photo when bytes are present, else initials. Never raises.

    The finished disc is cached at the exact diameter it's drawn at, so a
    member appearing on both the board and a rank card costs one decode.

    The initial is part of the key: a fallback avatar is drawn from the name,
    so keying on the user id alone would keep serving the old letter after
    someone renames.
    """
    key = (uid, size, True) if raw else (uid, size, False, initial_for(name))
    cached = caches.AVATAR_DISC.get(key)
    if cached is not None:
        return cached

    img = None
    if raw:
        try:
            img = make_circular_avatar(raw, size)
        except Exception:
            img = None
    if img is None:
        img = make_initials_avatar(name, size)

    caches.AVATAR_DISC.set(key, img)
    return img


def place_avatar(base, raw, name, uid, cx, cy, d, metal, glow=False,
                 ring_w: int | None = None, glow_opacity: int = 85) -> None:
    """Composite a circular avatar inside a metallic ring, with optional glow.

    The ring scales with the diameter by default, which suits the small board
    rows; the rank card passes an explicit thinner ring so a large portrait
    doesn't end up wearing a heavy band.
    """
    ring_w = max(2, ring_w if ring_w is not None else d // 14)
    outer = d + ring_w * 2
    if glow:
        from .primitives import soft_shadow
        g, pad = soft_shadow((outer, outer), outer // 2, blur=max(5, d // 10),
                             opacity=glow_opacity, color=tuple(metal[1]))
        composite_at(base, g, cx - outer / 2 - pad, cy - outer / 2 - pad)
    ring = metal_gradient((outer, outer), metal).convert("RGBA")
    rmask = Image.new("L", (outer, outer), 0)
    md = ImageDraw.Draw(rmask)
    md.ellipse([0, 0, outer - 1, outer - 1], fill=255)
    md.ellipse([ring_w, ring_w, outer - 1 - ring_w, outer - 1 - ring_w], fill=0)
    ring.putalpha(rmask)
    composite_at(base, ring, cx - outer / 2, cy - outer / 2)
    composite_at(base, avatar_image(raw, name, uid, d), cx - d / 2, cy - d / 2)
