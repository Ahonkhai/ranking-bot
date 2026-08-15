"""Colours and metals. Unchanged from the original design — this is the part
of the bot that was already right."""

# Warm near-black ground and panel gradients.
BG_TOP, BG_BOT       = (22, 19, 14), (7, 6, 5)
PANEL_TOP, PANEL_BOT = (32, 28, 20), (15, 13, 9)

INK  = (245, 239, 225)   # warm white — names, headings
MUTE = (151, 133, 92)    # muted tan  — subtitles, labels
HAIR = (198, 162, 86)    # gold hairline

# Movement indicators. Kept distinct from the metals so a climb doesn't read
# as just more gold.
UP   = (126, 186, 118)
DOWN = (206, 106, 88)
FLAT = (120, 108, 82)

# Metallic gradients as (light, mid, deep).
GOLD_M    = ((255, 233, 153), (240, 193, 66), (150, 105, 27))
SILVER_M  = ((238, 240, 246), (190, 194, 202), (98, 102, 112))
BRONZE_M  = ((237, 178, 122), (193, 121, 66), (110, 67, 34))
GOLDDIM_M = ((205, 176, 110), (150, 122, 60), (92, 72, 30))

# Row tints for the podium places.
PODIUM_TINT = {0: (46, 38, 20), 1: (40, 41, 45), 2: (44, 33, 22)}


def rank_metal(rank: int):
    return {1: GOLD_M, 2: SILVER_M, 3: BRONZE_M}.get(rank, GOLDDIM_M)


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
