"""Game constants and configuration."""

from arena.models.encounter import TerrainType

# Hex grid settings
HEX_SIZE = 40  # Pixel size of hexes
TOKEN_RADIUS = 18  # Pixel radius of tokens

# Color scheme — dark fantasy / parchment & leather aesthetic
COLORS = {
    # Background — dark weathered wood tones
    "bg_dark": "#1a1410",
    "bg_medium": "#2a2018",
    "bg_light": "#3d2e20",
    # Hex grid — dark earth with warm borders
    "hex_fill": "#1e1812",
    "hex_border": "#5a4a38",
    "hex_hover": "#3a3025",
    "hex_selected": "#6b5530",
    "hex_move_range": "#2d5a27",
    "hex_attack_range": "#6a2222",
    "hex_ranged_normal": "#6a4422",
    "hex_ranged_long": "#4a3020",
    # Terrain
    "terrain_difficult": "#4a3a2a",
    "terrain_water": "#1a3a5a",
    "terrain_hazard": "#5a2a1a",
    # Teams
    "team_player": "#4CAF50",
    "team_ally": "#5090d0",
    "team_enemy": "#c43030",
    "team_neutral": "#9E9E9E",
    # UI — parchment text with gold accents
    "text_primary": "#f0e6d2",
    "text_secondary": "#a89880",
    "text_gold": "#d4a847",
    "button_normal": "#3d3028",
    "button_hover": "#554535",
    "button_active": "#6b5a45",
    "border_accent": "#6b5530",
    "border_light": "#8a7050",
    # Health
    "hp_full": "#4CAF50",
    "hp_bloodied": "#d4a030",
    "hp_critical": "#c43030",
    "hp_temp": "#42a5c4",
    # Terrain (additional)
    "terrain_pit": "#0a0a08",
    "terrain_wall": "#5a5040",
    "terrain_cover_half": "#3a4a3a",
    "terrain_cover_three_quarters": "#2a3a2a",
    "terrain_cover_full": "#4a4a3a",
    # Conditions
    "condition_debuff": "#c43030",
    "condition_buff": "#4CAF50",
    "condition_neutral": "#5090d0",
    # AI
    "ai_thinking": "#9070b0",
    # Radial menu — warm muted tones
    "radial_slot_attack": "#3a4a30",
    "radial_slot_cantrip": "#2a3a50",
    "radial_slot_spells": "#4a2a50",
    "radial_slot_tactics": "#2a4040",
    "radial_slot_bonus": "#4a4a28",
    "radial_slot_items": "#4a3a28",
    "radial_slot_end_turn": "#4a2828",
    "radial_slot_hover": "#6b5a45",
    "radial_slot_disabled": "#252018",
    "radial_arrow": "#a89880",
    # Persistent AoE zone overlays
    "hex_zone_friendly": "#3070a0",
    "hex_zone_enemy": "#803060",
    # AoE placement preview
    "hex_aoe_preview": "#d4a847",
}

# Terrain type to COLORS key mapping
TERRAIN_COLORS: dict[str, str] = {
    "normal": "hex_fill",
    "difficult": "terrain_difficult",
    "hazard": "terrain_hazard",
    "water": "terrain_water",
    "pit": "terrain_pit",
    "wall": "terrain_wall",
    "cover_half": "terrain_cover_half",
    "cover_three_quarters": "terrain_cover_three_quarters",
    "cover_full": "terrain_cover_full",
}

# Terrain display names (used for tooltips and UI labels)
TERRAIN_NAMES: dict[TerrainType, str] = {
    TerrainType.NORMAL: "Normal",
    TerrainType.DIFFICULT: "Difficult Terrain",
    TerrainType.HAZARD: "Hazard",
    TerrainType.WATER: "Water",
    TerrainType.PIT: "Pit",
    TerrainType.WALL: "Wall",
    TerrainType.COVER_HALF: "Half Cover",
    TerrainType.COVER_THREE_QUARTERS: "3/4 Cover",
    TerrainType.COVER_FULL: "Full Cover",
}

# Typography scale — semantic names for every font size the GUI uses.
# Pair with a style: get_font(FONT_SIZES["title"], "heading") for display
# text, get_font(FONT_SIZES["content"]) for readable body text.
FONT_SIZES = {
    "tiny": 10,     # badges, pagination icons
    "small": 11,    # filter tabs, secondary labels
    "body": 12,     # action-bar labels, tooltips, small stats
    "content": 13,  # popup entries, log lines (the workhorse size)
    "label": 14,    # popup titles, section headers
    "list": 15,     # initiative entries
    "title": 18,    # panel titles
}

# Layout scale — every load-bearing pixel number in one place. The GUI was
# built against a 1280x720 window; these names make that layout auditable
# instead of scattering magic numbers across fifteen files.
LAYOUT = {
    "screen_width": 1280,
    "screen_height": 720,
    # Screen-edge margin popups clamp to
    "popup_margin": 4,
    # Right-hand column (initiative + creature info) and bottom log strip
    "side_panel_width": 260,
    "initiative_height": 280,
    "log_height": 120,
    # Action bar buttons
    "action_button_width": 80,
    "action_button_height": 28,
    "action_small_button_width": 70,
    "action_bar_padding": 4,
    # Panel text rhythm
    "initiative_line_height": 22,
    "log_line_height": 16,
    "panel_title_pad": 6,
    # Radial menu geometry
    "radial_inner_radius": 40,
    "radial_outer_radius": 90,
    "radial_slot_radius": 22,
    "radial_arrow_radius": 12,
    # Popup shared metrics (per-popup WIDTH/row constants stay class-level;
    # these are the recipes every popup shares)
    "popup_padding": 6,
    "popup_row_height": 30,
    "popup_title_height": 34,
    "popup_button_height": 32,
    "popup_border_width": 2,
}

# Interaction constants
DRAG_THRESHOLD = 5  # Pixels of movement before drag activates
ZOOM_FACTOR = 1.1  # Multiplier per scroll tick


def parse_color(hex_color: str) -> tuple[int, int, int]:
    """Parse a hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


# Skill to ability mapping
SKILL_ABILITIES = {
    "acrobatics": "dexterity",
    "animal_handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}

# Challenge rating to XP mapping
CR_TO_XP = {
    0: 10,
    0.125: 25,
    0.25: 50,
    0.5: 100,
    1: 200,
    2: 450,
    3: 700,
    4: 1100,
    5: 1800,
    6: 2300,
    7: 2900,
    8: 3900,
    9: 5000,
    10: 5900,
    11: 7200,
    12: 8400,
    13: 10000,
    14: 11500,
    15: 13000,
    16: 15000,
    17: 18000,
    18: 20000,
    19: 22000,
    20: 25000,
    21: 33000,
    22: 41000,
    23: 50000,
    24: 62000,
    25: 75000,
    26: 90000,
    27: 105000,
    28: 120000,
    29: 135000,
    30: 155000,
}

# Proficiency bonus by level/CR
# Condition display metadata: (abbreviation, color_category)
CONDITION_DISPLAY: dict[str, tuple[str, str]] = {
    "blinded": ("BL", "condition_debuff"),
    "charmed": ("CH", "condition_debuff"),
    "deafened": ("DE", "condition_neutral"),
    "exhaustion": ("EX", "condition_debuff"),
    "frightened": ("FR", "condition_debuff"),
    "grappled": ("GR", "condition_debuff"),
    "incapacitated": ("IN", "condition_debuff"),
    "invisible": ("IV", "condition_neutral"),
    "paralyzed": ("PA", "condition_debuff"),
    "petrified": ("PE", "condition_debuff"),
    "poisoned": ("PO", "condition_debuff"),
    "prone": ("PR", "condition_debuff"),
    "restrained": ("RE", "condition_debuff"),
    "stunned": ("ST", "condition_debuff"),
    "unconscious": ("UN", "condition_debuff"),
    "concentrating": ("CO", "condition_neutral"),
    "dodging": ("DO", "condition_buff"),
    "helped": ("HE", "condition_buff"),
    "hidden": ("HI", "condition_buff"),
    "banished": ("BA", "condition_debuff"),
    "dominated": ("DM", "condition_debuff"),
    "compelled": ("CP", "condition_debuff"),
    "reckless": ("RK", "condition_neutral"),  # double-edged: adv on its melee, but attackers gain adv vs it
    "confused": ("CF", "condition_debuff"),
    "slowed": ("SL", "condition_debuff"),
}

PROFICIENCY_BY_LEVEL = {
    1: 2,
    2: 2,
    3: 2,
    4: 2,
    5: 3,
    6: 3,
    7: 3,
    8: 3,
    9: 4,
    10: 4,
    11: 4,
    12: 4,
    13: 5,
    14: 5,
    15: 5,
    16: 5,
    17: 6,
    18: 6,
    19: 6,
    20: 6,
}
