"""Encounter configuration and setup."""

from enum import Enum

from pydantic import BaseModel, Field

from .actions import Action
from .character import Creature


class TerrainType(str, Enum):
    """Types of terrain that can modify hexes."""

    NORMAL = "normal"
    DIFFICULT = "difficult"
    HAZARD = "hazard"
    WATER = "water"
    PIT = "pit"
    WALL = "wall"
    COVER_HALF = "cover_half"
    COVER_THREE_QUARTERS = "cover_three_quarters"
    COVER_FULL = "cover_full"


class TerrainHex(BaseModel):
    """Terrain modification for a hex."""

    position: tuple[int, int]
    terrain_type: TerrainType
    extra_data: dict = Field(default_factory=dict)  # e.g., {"damage": "1d6 fire"}


class HouseRules(BaseModel):
    """Per-world rule variants, delivered with the encounter — the first
    table-level settings to cross the story→Arena boundary. Authored in the
    Forge; every default is by-the-book, so an encounter file without this
    block plays exactly as before."""

    initiative: str = "standard"  # "standard" | "side" (one d20 per side) |
                                  # "reroll" (everyone re-rolls each round)
    flanking: bool = False        # melee advantage from an ally on the opposite side
    crit_range_19: bool = False   # everyone crits on 19–20
    brutal_crits: bool = False    # crit dice are MAXIMIZED instead of re-rolled


class CombatantEntry(BaseModel):
    """A creature placed in an encounter."""

    creature_id: str  # Reference to character/monster file
    creature_data: Creature | None = None  # Inline data (alternative to ID)
    team: str = "enemy"  # "player", "ally", "enemy", "neutral"
    starting_position: tuple[int, int] | None = None  # Hex coordinates
    count: int = 1  # For multiple identical creatures
    name_override: str | None = None  # e.g., "Goblin 1"


class Encounter(BaseModel):
    """A complete encounter setup."""

    name: str
    description: str | None = None

    # Grid
    grid_width: int = 20
    grid_height: int = 15
    terrain: list[TerrainHex] = Field(default_factory=list)

    # Combatants
    combatants: list[CombatantEntry] = Field(default_factory=list)

    # Settings
    use_ai_for_enemies: bool = True
    use_ai_for_allies: bool = False
    auto_roll_initiative: bool = True
    house_rules: HouseRules = Field(default_factory=HouseRules)

    # Lair actions (encounter-level, not creature-level)
    has_lair: bool = False
    lair_actions: list[Action] = Field(default_factory=list)

    # Environment
    lighting: str = "bright"  # "bright", "dim", "dark"
    environmental_effects: list[str] = Field(default_factory=list)

    # Music
    music_track: str | None = None  # Filename in assets/music/, e.g. "highdifficulty_encounter_1.mp3"

    # Background
    background_image: str | None = None  # Filename in assets/ui/encounter backgrounds/
    background_offset: tuple[float, float] = (0.0, 0.0)  # World-space offset
    background_scale: float = 1.0  # Scale multiplier (1.0 = fill grid bounds)
