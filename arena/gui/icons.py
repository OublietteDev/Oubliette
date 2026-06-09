"""Procedural icon generation for radial menu slots.

Generates small pygame Surface icons for D&D actions, weapons, spells,
cantrips, and standard actions. Icons are drawn using pygame primitives
and cached after first creation.

Each icon is a square SRCALPHA surface rendered at a requested size.
"""

from __future__ import annotations

import math

import pygame

# Icon cache: (icon_id, size) -> Surface
_icon_cache: dict[tuple[str, int], pygame.Surface] = {}


def get_icon(name: str, size: int) -> pygame.Surface | None:
    """Get a cached icon surface for the given action/spell name.

    Returns None if no icon mapping exists for the name.
    The icon is a square SRCALPHA surface of ``size x size`` pixels.
    """
    icon_id = _resolve_icon_id(name)
    if icon_id is None:
        return None

    key = (icon_id, size)
    if key not in _icon_cache:
        surf = _render_icon(icon_id, size)
        if surf is None:
            return None
        _icon_cache[key] = surf
    return _icon_cache[key]


# ── Name → icon ID mapping ──────────────────────────────────────────

# Exact name matches (case-insensitive)
_EXACT_MAP: dict[str, str] = {
    # Weapons — melee
    "longsword": "sword",
    "shortsword": "sword",
    "greatsword": "sword_large",
    "rapier": "sword",
    "scimitar": "sword",
    "dagger": "dagger",
    "handaxe": "axe",
    "battleaxe": "axe",
    "greataxe": "axe_large",
    "warhammer": "hammer",
    "maul": "hammer",
    "mace": "hammer",
    "flail": "flail",
    "morningstar": "flail",
    "halberd": "polearm",
    "glaive": "polearm",
    "pike": "polearm",
    "spear": "polearm",
    "javelin": "polearm",
    "lance": "polearm",
    "quarterstaff": "staff",
    "trident": "trident",
    "war pick": "pick",
    "whip": "whip",
    "club": "club",
    "greatclub": "club",
    "sickle": "sickle",
    "light hammer": "hammer",
    # Weapons — ranged
    "longbow": "bow",
    "shortbow": "bow",
    "crossbow": "crossbow",
    "light crossbow": "crossbow",
    "heavy crossbow": "crossbow",
    "hand crossbow": "crossbow",
    "sling": "sling",
    "dart": "dagger",
    "blowgun": "crossbow",
    "net": "net",
    # Natural weapons
    "bite": "bite",
    "claw": "claw",
    "slam": "fist",
    "tail": "tail",
    "gore": "horns",
    "hooves": "hooves",
    "sting": "sting",
    "tentacle": "tentacle",
    "multiattack": "multi",
    # Cantrips
    "fire bolt": "fire",
    "firebolt": "fire",
    "ray of frost": "frost",
    "eldritch blast": "eldritch",
    "sacred flame": "radiant",
    "toll the dead": "skull",
    "chill touch": "necrotic",
    "shocking grasp": "lightning",
    "acid splash": "acid",
    "poison spray": "poison",
    "produce flame": "fire",
    "thorn whip": "thorns",
    "vicious mockery": "music",
    "minor illusion": "eye",
    "prestidigitation": "sparkle",
    "thaumaturgy": "sparkle",
    "druidcraft": "leaf",
    "mage hand": "hand",
    "light": "radiant",
    "spare the dying": "heal",
    "guidance": "radiant",
    "resistance": "shield_magic",
    "mending": "heal",
    "true strike": "eye",
    "blade ward": "shield_magic",
    "friends": "charm",
    "message": "music",
    "dancing lights": "radiant",
    "word of radiance": "radiant",
    "thunderclap": "lightning",
    "sword burst": "sword",
    "booming blade": "sword",
    "green-flame blade": "fire",
    "magic stone": "earth",
    "shillelagh": "staff",
    "infestation": "poison",
    "create bonfire": "fire",
    "frostbite": "frost",
    "primal savagery": "claw",
    # Spells — damage
    "fireball": "fire",
    "lightning bolt": "lightning",
    "thunder wave": "lightning",
    "burning hands": "fire",
    "ice storm": "frost",
    "cone of cold": "frost",
    "scorching ray": "fire",
    "magic missile": "sparkle",
    "chromatic orb": "sparkle",
    "witch bolt": "lightning",
    "shatter": "lightning",
    "guiding bolt": "radiant",
    "inflict wounds": "necrotic",
    "cloud of daggers": "dagger",
    "moonbeam": "radiant",
    "call lightning": "lightning",
    "blight": "necrotic",
    "flame strike": "fire",
    "disintegrate": "necrotic",
    "meteor swarm": "fire",
    "chain lightning": "lightning",
    "spiritual weapon": "radiant",
    "spirit guardians": "radiant",
    # Spells — healing
    "cure wounds": "heal",
    "healing word": "heal",
    "mass cure wounds": "heal",
    "mass healing word": "heal",
    "heal": "heal",
    "prayer of healing": "heal",
    "revivify": "heal",
    "raise dead": "heal",
    "greater restoration": "heal",
    "lesser restoration": "heal",
    "restoration": "heal",
    # Spells — buff/utility
    "shield": "shield_magic",
    "shield of faith": "shield_magic",
    "mage armor": "shield_magic",
    "bless": "radiant",
    "bane": "necrotic",
    "hex": "necrotic",
    "hunter's mark": "eye",
    "haste": "sparkle",
    "slow": "frost",
    "hold person": "charm",
    "hold monster": "charm",
    "counterspell": "shield_magic",
    "dispel magic": "sparkle",
    "misty step": "teleport",
    "dimension door": "teleport",
    "teleport": "teleport",
    "fly": "wind",
    "invisibility": "eye",
    "greater invisibility": "eye",
    "silence": "music",
    "darkness": "necrotic",
    "web": "net",
    "entangle": "thorns",
    "polymorph": "sparkle",
    "banishment": "teleport",
    "suggestion": "charm",
    "command": "charm",
    "sleep": "charm",
    "faerie fire": "radiant",
    "detect magic": "eye",
    "identify": "eye",
    "comprehend languages": "music",
    "speak with animals": "music",
    "animal friendship": "charm",
    "goodberry": "leaf",
    "fog cloud": "wind",
    "gust of wind": "wind",
    "mirror image": "eye",
    "blur": "eye",
    "protection from evil and good": "shield_magic",
    "absorb elements": "shield_magic",
    "feather fall": "wind",
    "expeditious retreat": "wind",
    "longstrider": "wind",
    "jump": "wind",
    "enhance ability": "sparkle",
    "enlarge/reduce": "sparkle",
    "levitate": "wind",
    "water breathing": "water",
    "water walk": "water",
    "plant growth": "leaf",
    "speak with dead": "skull",
    "animate dead": "skull",
    "bestow curse": "skull",
    "remove curse": "heal",
    "daylight": "radiant",
    "tongues": "music",
    "freedom of movement": "wind",
    "death ward": "shield_magic",
    "conjure animals": "claw",
    "conjure woodland beings": "leaf",
    "wall of fire": "fire",
    "wall of stone": "earth",
    "wall of force": "shield_magic",
    "wall of ice": "frost",
    "stoneskin": "earth",
    "dominate person": "charm",
    "dominate monster": "charm",
    "feeblemind": "skull",
    "power word stun": "lightning",
    "power word kill": "skull",
    "wish": "sparkle",
    # Standard actions
    "dash": "dash",
    "disengage": "disengage",
    "dodge": "dodge",
    "hide": "hide",
    "help": "help",
    # Special radial slots
    "cantrips": "cantrip_group",
    "spells": "spell_group",
    "tactics": "tactics_group",
    "end turn": "end_turn",
    "off-hand": "offhand",
}

# Keyword fallbacks — checked if no exact match
_KEYWORD_MAP: list[tuple[str, str]] = [
    ("sword", "sword"),
    ("blade", "sword"),
    ("axe", "axe"),
    ("bow", "bow"),
    ("arrow", "bow"),
    ("bolt", "lightning"),
    ("hammer", "hammer"),
    ("mace", "hammer"),
    ("staff", "staff"),
    ("wand", "sparkle"),
    ("fire", "fire"),
    ("flame", "fire"),
    ("burn", "fire"),
    ("frost", "frost"),
    ("ice", "frost"),
    ("cold", "frost"),
    ("lightning", "lightning"),
    ("thunder", "lightning"),
    ("shock", "lightning"),
    ("heal", "heal"),
    ("cure", "heal"),
    ("restor", "heal"),
    ("poison", "poison"),
    ("acid", "acid"),
    ("necrotic", "necrotic"),
    ("radiant", "radiant"),
    ("holy", "radiant"),
    ("divine", "radiant"),
    ("smite", "radiant"),
    ("claw", "claw"),
    ("bite", "bite"),
    ("fang", "bite"),
    ("breath", "fire"),
    ("shield", "shield_magic"),
    ("ward", "shield_magic"),
    ("protect", "shield_magic"),
    ("charm", "charm"),
    ("dominate", "charm"),
    ("fear", "skull"),
    ("curse", "skull"),
    ("death", "skull"),
    ("teleport", "teleport"),
    ("dimension", "teleport"),
    ("misty", "teleport"),
    ("summon", "sparkle"),
    ("conjure", "sparkle"),
    ("web", "net"),
    ("entangle", "thorns"),
    ("vine", "thorns"),
    ("thorn", "thorns"),
    ("spear", "polearm"),
    ("pike", "polearm"),
    ("trident", "trident"),
    ("crossbow", "crossbow"),
    ("dagger", "dagger"),
    ("knock", "fist"),
    ("punch", "fist"),
    ("slam", "fist"),
    ("kick", "fist"),
    ("whip", "whip"),
    ("eye", "eye"),
    ("detect", "eye"),
    ("see", "eye"),
    ("wind", "wind"),
    ("fly", "wind"),
    ("ray", "sparkle"),
    ("beam", "sparkle"),
    ("orb", "sparkle"),
    ("stone", "earth"),
    ("rock", "earth"),
    ("earth", "earth"),
    ("water", "water"),
    ("wave", "water"),
    ("leaf", "leaf"),
    ("plant", "leaf"),
    ("nature", "leaf"),
    ("music", "music"),
    ("song", "music"),
    ("shout", "music"),
]


def _resolve_icon_id(name: str) -> str | None:
    """Map an action/spell name to an icon ID."""
    lower = name.lower().strip()
    # Exact match
    if lower in _EXACT_MAP:
        return _EXACT_MAP[lower]
    # Keyword fallback
    for keyword, icon_id in _KEYWORD_MAP:
        if keyword in lower:
            return icon_id
    return None


# ── Icon Rendering ──────────────────────────────────────────────────

# Icon colors — softer, parchment-compatible tones
_C = {
    "white": (240, 230, 210),
    "steel": (180, 190, 200),
    "gold": (212, 168, 71),
    "red": (196, 48, 48),
    "orange": (220, 140, 40),
    "blue": (80, 144, 208),
    "cyan": (100, 200, 220),
    "green": (70, 175, 80),
    "purple": (140, 100, 180),
    "dark": (60, 50, 40),
    "bone": (200, 190, 170),
    "brown": (140, 100, 60),
}


def _render_icon(icon_id: str, size: int) -> pygame.Surface | None:
    """Render a procedural icon. Returns None if icon_id is unknown."""
    renderer = _ICON_RENDERERS.get(icon_id)
    if renderer is None:
        return None
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    renderer(surf, size)
    return surf


# ── Individual icon drawing functions ───────────────────────────────
# Each takes (surface, size) and draws onto the surface.

def _draw_sword(s: pygame.Surface, sz: int) -> None:
    """Longsword / generic sword icon."""
    m = sz // 2
    # Blade
    pygame.draw.line(s, _C["steel"], (m, sz * 2 // 10), (m, sz * 8 // 10), max(2, sz // 10))
    # Crossguard
    pygame.draw.line(s, _C["gold"], (sz * 3 // 10, sz * 6 // 10), (sz * 7 // 10, sz * 6 // 10), max(2, sz // 12))
    # Pommel
    pygame.draw.circle(s, _C["gold"], (m, sz * 8 // 10 + sz // 12), max(2, sz // 10))


def _draw_sword_large(s: pygame.Surface, sz: int) -> None:
    """Greatsword icon — wider blade."""
    m = sz // 2
    w = max(3, sz // 7)
    pygame.draw.line(s, _C["steel"], (m, sz * 2 // 10), (m, sz * 8 // 10), w)
    pygame.draw.line(s, _C["gold"], (sz * 2 // 10, sz * 6 // 10), (sz * 8 // 10, sz * 6 // 10), max(2, sz // 10))
    pygame.draw.circle(s, _C["gold"], (m, sz * 85 // 100), max(2, sz // 10))


def _draw_dagger(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["steel"], (m, sz * 3 // 10), (m, sz * 7 // 10), max(1, sz // 12))
    pygame.draw.line(s, _C["gold"], (sz * 35 // 100, sz * 6 // 10), (sz * 65 // 100, sz * 6 // 10), max(1, sz // 14))


def _draw_axe(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Handle
    pygame.draw.line(s, _C["brown"], (m, sz * 2 // 10), (m, sz * 85 // 100), max(1, sz // 14))
    # Blade (curved triangle)
    pts = [(m - sz // 4, sz * 25 // 100), (m, sz * 2 // 10), (m, sz * 45 // 100)]
    pygame.draw.polygon(s, _C["steel"], pts)


def _draw_axe_large(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 15 // 100), (m, sz * 85 // 100), max(2, sz // 12))
    pts = [(m - sz * 3 // 10, sz * 2 // 10), (m, sz * 15 // 100), (m, sz * 5 // 10)]
    pygame.draw.polygon(s, _C["steel"], pts)


def _draw_hammer(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 3 // 10), (m, sz * 85 // 100), max(1, sz // 14))
    head = pygame.Rect(m - sz // 4, sz * 2 // 10, sz // 2, sz // 4)
    pygame.draw.rect(s, _C["steel"], head, border_radius=max(1, sz // 16))


def _draw_bow(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Arc
    r = sz * 35 // 100
    pygame.draw.arc(s, _C["brown"], (m - r, m - r, r * 2, r * 2), -math.pi / 3, math.pi / 3, max(2, sz // 12))
    # String
    pygame.draw.line(s, _C["bone"], (m + int(r * 0.5), m - int(r * 0.87)), (m + int(r * 0.5), m + int(r * 0.87)), 1)
    # Arrow
    pygame.draw.line(s, _C["steel"], (sz * 2 // 10, m), (sz * 75 // 100, m), max(1, sz // 16))
    # Arrowhead
    ax = sz * 2 // 10
    pygame.draw.polygon(s, _C["steel"], [(ax, m), (ax + sz // 10, m - sz // 14), (ax + sz // 10, m + sz // 14)])


def _draw_crossbow(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 3 // 10), (m, sz * 8 // 10), max(2, sz // 12))
    pygame.draw.line(s, _C["brown"], (sz * 2 // 10, sz * 35 // 100), (sz * 8 // 10, sz * 35 // 100), max(2, sz // 12))
    pygame.draw.line(s, _C["bone"], (sz * 2 // 10, sz * 35 // 100), (m, sz * 45 // 100), 1)
    pygame.draw.line(s, _C["bone"], (sz * 8 // 10, sz * 35 // 100), (m, sz * 45 // 100), 1)


def _draw_staff(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 15 // 100), (m, sz * 85 // 100), max(2, sz // 10))
    pygame.draw.circle(s, _C["purple"], (m, sz * 18 // 100), max(3, sz // 8))
    pygame.draw.circle(s, _C["white"], (m, sz * 18 // 100), max(1, sz // 12))


def _draw_polearm(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 15 // 100), (m, sz * 88 // 100), max(1, sz // 14))
    pts = [(m, sz * 1 // 10), (m - sz // 8, sz * 25 // 100), (m + sz // 8, sz * 25 // 100)]
    pygame.draw.polygon(s, _C["steel"], pts)


def _draw_fire(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Outer flame
    pts = [(m, sz * 15 // 100), (m + sz * 3 // 10, sz * 65 // 100),
           (m + sz // 6, sz * 82 // 100), (m, sz * 75 // 100),
           (m - sz // 6, sz * 82 // 100), (m - sz * 3 // 10, sz * 65 // 100)]
    pygame.draw.polygon(s, _C["orange"], pts)
    # Inner flame
    pts2 = [(m, sz * 3 // 10), (m + sz // 6, sz * 6 // 10),
            (m, sz * 7 // 10), (m - sz // 6, sz * 6 // 10)]
    pygame.draw.polygon(s, _C["gold"], pts2)


def _draw_frost(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    c = _C["cyan"]
    r = sz * 3 // 10
    for i in range(6):
        angle = math.pi / 3 * i
        ex = m + int(r * math.cos(angle))
        ey = m + int(r * math.sin(angle))
        pygame.draw.line(s, c, (m, m), (ex, ey), max(1, sz // 16))
    pygame.draw.circle(s, _C["blue"], (m, m), max(2, sz // 8))


def _draw_lightning(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pts = [(m + sz // 10, sz * 15 // 100), (m - sz // 8, sz * 45 // 100),
           (m + sz // 12, sz * 45 // 100), (m - sz // 6, sz * 85 // 100)]
    pygame.draw.lines(s, _C["gold"], False, pts, max(2, sz // 8))


def _draw_heal(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    t = max(2, sz // 5)
    h = sz * 3 // 10
    pygame.draw.rect(s, _C["green"], (m - t // 2, m - h, t, h * 2), border_radius=max(1, sz // 16))
    pygame.draw.rect(s, _C["green"], (m - h, m - t // 2, h * 2, t), border_radius=max(1, sz // 16))


def _draw_shield_magic(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pts = [(m, sz * 15 // 100), (sz * 75 // 100, sz * 3 // 10),
           (sz * 7 // 10, sz * 7 // 10), (m, sz * 85 // 100),
           (sz * 3 // 10, sz * 7 // 10), (sz * 25 // 100, sz * 3 // 10)]
    pygame.draw.polygon(s, _C["blue"], pts)
    pygame.draw.polygon(s, _C["white"], pts, max(1, sz // 14))


def _draw_radiant(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["gold"], (m, m), max(3, sz * 2 // 10))
    r = sz * 35 // 100
    for i in range(8):
        angle = math.pi / 4 * i
        sx = m + int(r * 0.5 * math.cos(angle))
        sy = m + int(r * 0.5 * math.sin(angle))
        ex = m + int(r * math.cos(angle))
        ey = m + int(r * math.sin(angle))
        pygame.draw.line(s, _C["gold"], (sx, sy), (ex, ey), max(1, sz // 14))


def _draw_necrotic(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["purple"], (m, m), max(3, sz * 25 // 100))
    pygame.draw.circle(s, _C["dark"], (m, m), max(2, sz * 15 // 100))


def _draw_skull(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Head
    pygame.draw.ellipse(s, _C["bone"], (m - sz * 2 // 10, sz * 15 // 100, sz * 4 // 10, sz * 45 // 100))
    # Jaw
    pygame.draw.ellipse(s, _C["bone"], (m - sz * 15 // 100, sz * 5 // 10, sz * 3 // 10, sz * 2 // 10))
    # Eyes
    eye_r = max(1, sz // 12)
    pygame.draw.circle(s, _C["dark"], (m - sz // 10, sz * 35 // 100), eye_r)
    pygame.draw.circle(s, _C["dark"], (m + sz // 10, sz * 35 // 100), eye_r)


def _draw_poison(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["green"], (m, m), max(4, sz * 25 // 100))
    # Bubbles
    pygame.draw.circle(s, _C["green"], (m + sz // 5, m - sz // 5), max(2, sz // 10))
    pygame.draw.circle(s, _C["green"], (m - sz // 6, m - sz * 3 // 10), max(1, sz // 14))


def _draw_acid(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Droplet shape
    pts = [(m, sz * 2 // 10), (m + sz // 4, sz * 6 // 10), (m, sz * 8 // 10), (m - sz // 4, sz * 6 // 10)]
    pygame.draw.polygon(s, _C["green"], pts)
    pygame.draw.polygon(s, (50, 140, 50), pts, max(1, sz // 14))


def _draw_charm(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["purple"], (m, m), max(4, sz * 25 // 100))
    # Swirl lines
    for i in range(3):
        angle = math.pi * 2 / 3 * i
        ex = m + int(sz * 0.3 * math.cos(angle))
        ey = m + int(sz * 0.3 * math.sin(angle))
        pygame.draw.line(s, _C["white"], (m, m), (ex, ey), max(1, sz // 16))


def _draw_sparkle(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    r1 = sz * 3 // 10
    r2 = sz // 8
    c = _C["gold"]
    for i in range(4):
        angle = math.pi / 2 * i
        ex = m + int(r1 * math.cos(angle))
        ey = m + int(r1 * math.sin(angle))
        pygame.draw.line(s, c, (m, m), (ex, ey), max(1, sz // 14))
    for i in range(4):
        angle = math.pi / 4 + math.pi / 2 * i
        ex = m + int(r2 * math.cos(angle))
        ey = m + int(r2 * math.sin(angle))
        pygame.draw.line(s, c, (m, m), (ex, ey), max(1, sz // 16))


def _draw_eye(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Eye shape
    pts = [(sz * 15 // 100, m), (m, m - sz // 4), (sz * 85 // 100, m), (m, m + sz // 4)]
    pygame.draw.polygon(s, _C["white"], pts)
    pygame.draw.polygon(s, _C["steel"], pts, max(1, sz // 16))
    pygame.draw.circle(s, _C["blue"], (m, m), max(2, sz // 8))
    pygame.draw.circle(s, _C["dark"], (m, m), max(1, sz // 14))


def _draw_music(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Note
    pygame.draw.circle(s, _C["gold"], (m - sz // 8, sz * 65 // 100), max(2, sz // 8))
    pygame.draw.line(s, _C["gold"], (m + sz // 12, sz * 65 // 100), (m + sz // 12, sz * 25 // 100), max(1, sz // 14))
    pygame.draw.circle(s, _C["gold"], (m + sz // 12 + sz // 10, sz * 25 // 100), max(1, sz // 10))


def _draw_teleport(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["purple"], (m, m), max(3, sz * 2 // 10), max(1, sz // 12))
    pygame.draw.circle(s, _C["purple"], (m, m), max(2, sz // 8), max(1, sz // 14))
    # Sparkle center
    pygame.draw.circle(s, _C["white"], (m, m), max(1, sz // 12))


def _draw_wind(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    c = _C["cyan"]
    for i, offset in enumerate([-sz // 6, 0, sz // 6]):
        y = m + offset
        pygame.draw.arc(s, c, (sz * 2 // 10, y - sz // 10, sz * 5 // 10, sz // 5), 0, math.pi, max(1, sz // 14))


def _draw_earth(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Rock shape
    pts = [(m, sz * 2 // 10), (sz * 7 // 10, sz * 4 // 10), (sz * 65 // 100, sz * 75 // 100),
           (sz * 35 // 100, sz * 75 // 100), (sz * 3 // 10, sz * 4 // 10)]
    pygame.draw.polygon(s, _C["brown"], pts)
    pygame.draw.polygon(s, _C["steel"], pts, max(1, sz // 14))


def _draw_water(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pts = [(m, sz * 2 // 10), (m + sz // 4, sz * 55 // 100), (m, sz * 8 // 10), (m - sz // 4, sz * 55 // 100)]
    pygame.draw.polygon(s, _C["blue"], pts)


def _draw_leaf(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pts = [(m, sz * 15 // 100), (sz * 7 // 10, m), (m, sz * 85 // 100), (sz * 3 // 10, m)]
    pygame.draw.polygon(s, _C["green"], pts)
    pygame.draw.line(s, (40, 130, 50), (m, sz * 2 // 10), (m, sz * 8 // 10), max(1, sz // 16))


def _draw_hand(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["blue"], (m, m + sz // 10), max(3, sz // 5))
    # Fingers
    for i in range(3):
        fx = m - sz // 8 + i * (sz // 8)
        pygame.draw.line(s, _C["blue"], (fx, m), (fx, m - sz // 4), max(1, sz // 14))


def _draw_thorns(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    c = _C["green"]
    # Vine
    pygame.draw.line(s, c, (m, sz * 15 // 100), (m, sz * 85 // 100), max(1, sz // 12))
    # Thorns
    for y_frac in (3, 5, 7):
        y = sz * y_frac // 10
        pygame.draw.line(s, c, (m, y), (m + sz // 6, y - sz // 10), max(1, sz // 16))
        pygame.draw.line(s, c, (m, y), (m - sz // 6, y + sz // 10), max(1, sz // 16))


def _draw_eldritch(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["purple"], (m, m), max(3, sz * 2 // 10))
    # Rays
    r = sz * 35 // 100
    for i in range(6):
        angle = math.pi / 3 * i + 0.3
        ex = m + int(r * math.cos(angle))
        ey = m + int(r * math.sin(angle))
        pygame.draw.line(s, _C["purple"], (m, m), (ex, ey), max(1, sz // 14))


# ── Monster natural weapons ─────────────────────────────────────────

def _draw_bite(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Upper jaw
    pts_u = [(sz * 2 // 10, m - sz // 10), (m, sz * 2 // 10), (sz * 8 // 10, m - sz // 10)]
    pygame.draw.lines(s, _C["bone"], False, pts_u, max(2, sz // 10))
    # Lower jaw
    pts_l = [(sz * 25 // 100, m + sz // 10), (m, sz * 8 // 10), (sz * 75 // 100, m + sz // 10)]
    pygame.draw.lines(s, _C["bone"], False, pts_l, max(2, sz // 10))
    # Fangs
    pygame.draw.line(s, _C["white"], (sz * 3 // 10, m - sz // 14), (sz * 35 // 100, m + sz // 8), max(1, sz // 16))
    pygame.draw.line(s, _C["white"], (sz * 7 // 10, m - sz // 14), (sz * 65 // 100, m + sz // 8), max(1, sz // 16))


def _draw_claw(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    for i, offset in enumerate([-sz // 6, 0, sz // 6]):
        sx = m + offset
        pygame.draw.line(s, _C["bone"], (sx, sz * 3 // 10), (sx - sz // 10, sz * 7 // 10), max(1, sz // 12))


def _draw_fist(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.circle(s, _C["brown"], (m, m), max(4, sz * 25 // 100))
    pygame.draw.circle(s, _C["bone"], (m, m), max(4, sz * 25 // 100), max(1, sz // 12))


def _draw_tail(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    r = sz * 3 // 10
    pygame.draw.arc(s, _C["green"], (m - r, m - r, r * 2, r * 2), 0, math.pi * 3 / 2, max(2, sz // 10))
    pygame.draw.circle(s, _C["green"], (m + r, m), max(2, sz // 10))


def _draw_horns(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["bone"], (m - sz // 4, sz * 7 // 10), (m - sz // 6, sz * 2 // 10), max(2, sz // 10))
    pygame.draw.line(s, _C["bone"], (m + sz // 4, sz * 7 // 10), (m + sz // 6, sz * 2 // 10), max(2, sz // 10))


def _draw_hooves(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    w = sz // 4
    pygame.draw.ellipse(s, _C["brown"], (m - w - sz // 10, sz * 4 // 10, w, sz * 35 // 100))
    pygame.draw.ellipse(s, _C["brown"], (m + sz // 10, sz * 4 // 10, w, sz * 35 // 100))


def _draw_sting(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pts = [(m, sz * 15 // 100), (m + sz // 5, sz * 5 // 10), (m, sz * 85 // 100), (m - sz // 5, sz * 5 // 10)]
    pygame.draw.polygon(s, _C["green"], pts)
    pygame.draw.polygon(s, _C["dark"], pts, max(1, sz // 14))


def _draw_tentacle(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    r = sz * 3 // 10
    pygame.draw.arc(s, _C["purple"], (sz // 5, sz * 15 // 100, r * 2, r * 2), 0, math.pi, max(2, sz // 10))
    pygame.draw.arc(s, _C["purple"], (sz * 2 // 5, sz * 4 // 10, r * 2, r), math.pi, math.pi * 2, max(2, sz // 10))


def _draw_multi(s: pygame.Surface, sz: int) -> None:
    """Multiattack — two crossing swords."""
    m = sz // 2
    o = sz // 5
    pygame.draw.line(s, _C["steel"], (m - o, sz * 2 // 10), (m + o, sz * 8 // 10), max(1, sz // 12))
    pygame.draw.line(s, _C["steel"], (m + o, sz * 2 // 10), (m - o, sz * 8 // 10), max(1, sz // 12))
    pygame.draw.line(s, _C["gold"], (m - sz // 4, sz * 55 // 100), (m + sz // 4, sz * 55 // 100), max(1, sz // 14))


# ── Special / misc ──────────────────────────────────────────────────

def _draw_flail(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 4 // 10), (m, sz * 85 // 100), max(1, sz // 14))
    pygame.draw.line(s, _C["steel"], (m, sz * 4 // 10), (m + sz // 8, sz * 2 // 10), max(1, sz // 16))
    pygame.draw.circle(s, _C["steel"], (m + sz // 8, sz * 18 // 100), max(3, sz // 7))


def _draw_trident(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["steel"], (m, sz * 15 // 100), (m, sz * 85 // 100), max(1, sz // 14))
    # Three prongs
    for offset in [-sz // 6, 0, sz // 6]:
        pygame.draw.line(s, _C["steel"], (m + offset, sz * 15 // 100), (m + offset, sz * 3 // 10), max(1, sz // 16))


def _draw_pick(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 3 // 10), (m, sz * 85 // 100), max(1, sz // 14))
    pygame.draw.line(s, _C["steel"], (m - sz // 4, sz * 25 // 100), (m + sz // 8, sz * 35 // 100), max(2, sz // 10))


def _draw_whip(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pts = [(m + sz // 4, sz * 8 // 10), (m, sz * 5 // 10), (m - sz // 6, sz * 3 // 10), (m + sz // 8, sz * 15 // 100)]
    pygame.draw.lines(s, _C["brown"], False, pts, max(1, sz // 12))


def _draw_club(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 2 // 10), (m, sz * 85 // 100), max(2, sz // 8))
    pygame.draw.circle(s, _C["brown"], (m, sz * 22 // 100), max(3, sz // 6))


def _draw_sickle(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.line(s, _C["brown"], (m, sz * 5 // 10), (m, sz * 85 // 100), max(1, sz // 14))
    r = sz * 25 // 100
    pygame.draw.arc(s, _C["steel"], (m - r, sz * 2 // 10, r * 2, r * 2), 0, math.pi, max(2, sz // 10))


def _draw_sling(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    pygame.draw.arc(s, _C["brown"], (sz * 2 // 10, sz * 3 // 10, sz * 6 // 10, sz * 4 // 10), 0, math.pi, max(2, sz // 10))
    pygame.draw.circle(s, _C["steel"], (m, sz * 3 // 10), max(2, sz // 10))


def _draw_net(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    c = _C["bone"]
    # Grid pattern
    for i in range(4):
        x = sz * (2 + i * 2) // 10
        pygame.draw.line(s, c, (x, sz * 2 // 10), (x, sz * 8 // 10), 1)
    for i in range(4):
        y = sz * (2 + i * 2) // 10
        pygame.draw.line(s, c, (sz * 2 // 10, y), (sz * 8 // 10, y), 1)


# Standard actions
def _draw_dash(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Two fast arrows
    c = _C["gold"]
    for offset in [-sz // 8, sz // 8]:
        pts = [(sz * 3 // 10, m + offset), (sz * 7 // 10, m + offset)]
        pygame.draw.line(s, c, pts[0], pts[1], max(1, sz // 12))
        # Arrowhead
        ax = sz * 7 // 10
        pygame.draw.polygon(s, c, [(ax, m + offset), (ax - sz // 10, m + offset - sz // 12), (ax - sz // 10, m + offset + sz // 12)])


def _draw_disengage(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Footprint + arrow away
    pygame.draw.circle(s, _C["bone"], (m - sz // 10, m + sz // 10), max(2, sz // 8))
    pygame.draw.line(s, _C["gold"], (m, m - sz // 10), (m + sz * 3 // 10, m - sz // 10), max(1, sz // 12))
    # Arrowhead
    ax = m + sz * 3 // 10
    ay = m - sz // 10
    pygame.draw.polygon(s, _C["gold"], [(ax, ay), (ax - sz // 12, ay - sz // 12), (ax - sz // 12, ay + sz // 12)])


def _draw_dodge(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Shield outline
    pts = [(m, sz * 18 // 100), (sz * 72 // 100, sz * 3 // 10),
           (sz * 68 // 100, sz * 65 // 100), (m, sz * 82 // 100),
           (sz * 32 // 100, sz * 65 // 100), (sz * 28 // 100, sz * 3 // 10)]
    pygame.draw.polygon(s, _C["steel"], pts, max(2, sz // 10))


def _draw_hide(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Eye with slash through it
    pts = [(sz * 2 // 10, m), (m, m - sz // 5), (sz * 8 // 10, m), (m, m + sz // 5)]
    pygame.draw.polygon(s, _C["steel"], pts, max(1, sz // 12))
    pygame.draw.circle(s, _C["dark"], (m, m), max(2, sz // 10))
    # Slash
    pygame.draw.line(s, _C["red"], (sz * 25 // 100, sz * 25 // 100), (sz * 75 // 100, sz * 75 // 100), max(2, sz // 10))


def _draw_help(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Two hands clasping
    pygame.draw.circle(s, _C["gold"], (m - sz // 8, m), max(3, sz // 6))
    pygame.draw.circle(s, _C["gold"], (m + sz // 8, m), max(3, sz // 6))


# ── Group/special radial slots ──────────────────────────────────────

def _draw_cantrip_group(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Small star/sparkle
    _draw_sparkle(s, sz)
    # C overlay
    pygame.draw.arc(s, _C["white"], (m - sz // 5, m - sz // 5, sz * 2 // 5, sz * 2 // 5), 0.5, 5.8, max(2, sz // 10))


def _draw_spell_group(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Book shape
    bw = sz * 4 // 10
    bh = sz * 5 // 10
    pygame.draw.rect(s, _C["purple"], (m - bw // 2, m - bh // 2, bw, bh), border_radius=max(1, sz // 16))
    pygame.draw.line(s, _C["gold"], (m, m - bh // 2 + 2), (m, m + bh // 2 - 2), max(1, sz // 16))
    # Star on cover
    pygame.draw.circle(s, _C["gold"], (m, m - sz // 10), max(1, sz // 10))


def _draw_tactics_group(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Chess knight silhouette (simplified)
    pts = [(m - sz // 6, sz * 75 // 100), (m - sz // 6, sz * 35 // 100),
           (m, sz * 2 // 10), (m + sz // 6, sz * 35 // 100),
           (m + sz // 6, sz * 75 // 100)]
    pygame.draw.polygon(s, _C["steel"], pts)
    pygame.draw.polygon(s, _C["white"], pts, max(1, sz // 14))


def _draw_end_turn(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Hourglass
    pts = [(m - sz // 5, sz * 2 // 10), (m + sz // 5, sz * 2 // 10),
           (m + sz // 10, m), (m + sz // 5, sz * 8 // 10),
           (m - sz // 5, sz * 8 // 10), (m - sz // 10, m)]
    pygame.draw.polygon(s, _C["gold"], pts, max(2, sz // 10))


def _draw_offhand(s: pygame.Surface, sz: int) -> None:
    m = sz // 2
    # Two small crossed swords
    o = sz // 6
    pygame.draw.line(s, _C["steel"], (m - o, sz * 25 // 100), (m + o, sz * 75 // 100), max(1, sz // 14))
    pygame.draw.line(s, _C["steel"], (m + o, sz * 25 // 100), (m - o, sz * 75 // 100), max(1, sz // 14))
    pygame.draw.line(s, _C["gold"], (m - sz // 4, m + sz // 10), (m + sz // 4, m + sz // 10), max(1, sz // 16))


# ── Renderer dispatch table ─────────────────────────────────────────

_ICON_RENDERERS: dict[str, callable] = {
    # Weapons — melee
    "sword": _draw_sword,
    "sword_large": _draw_sword_large,
    "dagger": _draw_dagger,
    "axe": _draw_axe,
    "axe_large": _draw_axe_large,
    "hammer": _draw_hammer,
    "flail": _draw_flail,
    "polearm": _draw_polearm,
    "staff": _draw_staff,
    "trident": _draw_trident,
    "pick": _draw_pick,
    "whip": _draw_whip,
    "club": _draw_club,
    "sickle": _draw_sickle,
    # Weapons — ranged
    "bow": _draw_bow,
    "crossbow": _draw_crossbow,
    "sling": _draw_sling,
    "net": _draw_net,
    # Natural weapons
    "bite": _draw_bite,
    "claw": _draw_claw,
    "fist": _draw_fist,
    "tail": _draw_tail,
    "horns": _draw_horns,
    "hooves": _draw_hooves,
    "sting": _draw_sting,
    "tentacle": _draw_tentacle,
    "multi": _draw_multi,
    # Spell effects
    "fire": _draw_fire,
    "frost": _draw_frost,
    "lightning": _draw_lightning,
    "heal": _draw_heal,
    "shield_magic": _draw_shield_magic,
    "radiant": _draw_radiant,
    "necrotic": _draw_necrotic,
    "skull": _draw_skull,
    "poison": _draw_poison,
    "acid": _draw_acid,
    "charm": _draw_charm,
    "sparkle": _draw_sparkle,
    "eye": _draw_eye,
    "music": _draw_music,
    "teleport": _draw_teleport,
    "wind": _draw_wind,
    "earth": _draw_earth,
    "water": _draw_water,
    "leaf": _draw_leaf,
    "hand": _draw_hand,
    "thorns": _draw_thorns,
    "eldritch": _draw_eldritch,
    # Standard actions
    "dash": _draw_dash,
    "disengage": _draw_disengage,
    "dodge": _draw_dodge,
    "hide": _draw_hide,
    "help": _draw_help,
    # Group / special radial slots
    "cantrip_group": _draw_cantrip_group,
    "spell_group": _draw_spell_group,
    "tactics_group": _draw_tactics_group,
    "end_turn": _draw_end_turn,
    "offhand": _draw_offhand,
}
