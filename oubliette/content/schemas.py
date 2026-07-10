"""Strict, versioned schemas for authored content (design doc §3).

Every model forbids unknown fields (`extra="forbid"`) so a typo in a pack file is
a load error, not a silent drop. Ids are stable, unique-within-type slugs. These
are the *authoring* shapes; the loader projects them onto the engine's runtime
models (`state.Item`, `state.Character`) — see `loader.py`.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump when a breaking change to these shapes ships; packs carry their own
# `schema_version` so the loader can refuse / migrate incompatible packs later.
SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- pack manifest -----------------------------------------------------------
class BestiaryGate(_Strict):
    """Per-world knowledge cutoff for the bestiary. When `enabled`, a creature whose
    challenge rating is ABOVE `max_known_cr` stays redacted ("????") until the party
    encounters it in combat; creatures at or below the threshold are always known
    (the rats everyone has seen). Set `max_known_cr` below 0 to gate *everything*
    unencountered. Applies to both the world's own creatures and the SRD library."""
    enabled: bool = False
    max_known_cr: float = 0.0        # CR ≤ this is always known; above it is gated


class TravelScale(_Strict):
    """Two-pin travel calibration (living-world W3): the author picks two pinned
    places on ONE map and states the days of travel between them — every other
    distance on that same map derives from it. Journeys on the calibrated map
    cost time (quantized to half-days); moves on uncalibrated maps (inside a
    town, an unmeasured region) cost nothing. No calibration = travel is free
    and the world clock still runs on rests."""

    a: str                           # -> Place id (pinned)
    b: str                           # -> Place id (pinned, sibling of a)
    days: float = Field(gt=0, le=365)  # travel days between the two pins


class PackManifest(_Strict):
    id: str
    schema_version: int              # this doc defines version 1
    name: str
    version: str                     # semver; a bump mints a new immutable pack
    author: str = ""
    description: str = ""
    entry_scenario: str              # which Scenario a new campaign starts in
    world_map: str | None = None     # background image (in images/) for the top-level
                                     # map — the whole world, e.g. Atria; pins sit on it
    bestiary_gate: BestiaryGate = Field(default_factory=BestiaryGate)
    recommended_difficulty: str | None = None   # the author's suggested preset
                                     # ("story"/"adventure"/"challenge"/"hardcore");
                                     # pre-selected at New Game, never binding
    travel_scale: TravelScale | None = None   # two-pin travel-time calibration (W3);
                                     # None = journeys cost no time


# --- items -------------------------------------------------------------------
class WeaponProfile(_Strict):
    attack_bonus: int = 0
    damage: str                      # dice spec, e.g. "1d6+1"
    properties: list[str] = Field(default_factory=list)  # finesse, light, ...


class ArmorProfile(_Strict):
    base_ac: int
    type: Literal["light", "medium", "heavy", "shield"]
    dex_cap: int | None = None       # reserved for the eventual AC computation


# --- the magic-item contract (Phase A freeze; shared by pack items + SRD gear) --
# These shapes were designed once for the SRD equipment catalog (`srd_schemas.
# SrdEquipment`) and are consumed by the Arena bridge (equipped +X bonuses, drink
# actions) and the `use_item` tool. The Forge module-kit arc gives pack-authored
# items the SAME contract, so they live here — the shared root — and srd_schemas
# imports them. `item_type` says what a magic item *is*: "mundane" = the base SRD
# gear chapter; the rest are the magic-item chapter families.
ItemType = Literal[
    "mundane", "weapon", "armor", "ammunition",
    "potion", "scroll", "wand", "ring", "rod", "staff", "wondrous", "poison",
]

# item_type families that are worn/wielded — the only ones magic_bonus applies to
# (a +N weapon boosts the attack; everything else equippable boosts AC).
_EQUIPPABLE_MAGIC = ("weapon", "armor", "ammunition", "ring", "rod", "staff",
                     "wand", "wondrous")


class ConsumableMechanics(_Strict):
    """Structured, bridge-readable mechanics for a consumable's effect. For SRD
    items these are extracted from prose by the deterministic generator; for pack
    items they are authored directly in the Forge. The Arena bridge maps these
    fields onto engine effects (drink actions, B1) and `use_item` rolls `healing`
    out of combat; anything not expressible here rides as prose only and leaves
    this None (see `mechanics == "none"`)."""

    healing: str | None = None              # dice string, e.g. "2d4+2" (Potion of Healing tiers)
    ability_set: dict[str, int] | None = None  # set a score, e.g. {"str": 21} (Giant Strength)
    grants_resistance: str | None = None    # damage type, e.g. "fire" (Potion of Resistance)
    casts_spell_level: int | None = None    # spell scrolls (0 = cantrip); casting deferred (F3)
    duration: str | None = None             # e.g. "1 hour" (buff potions)
    action: str = "action"                  # how it's consumed (action / bonus action)


class PoisonMechanics(_Strict):
    """Structured, bridge-readable mechanics for a poison. Unlike
    `ConsumableMechanics` (a buff the user drinks), a poison targets ANOTHER creature
    with a saving throw, so it gets its own shape: the Arena bridge (Phase B) can let
    a PC coat a blade with an injury poison and force the save on a hit. All 14 SRD
    poisons use a Constitution save; `damage` and/or `conditions` carry the failure
    effect. Designed once (A2, alongside the Phase-A freeze); pack items author it
    directly in the Forge."""

    poison_type: Literal["contact", "ingested", "inhaled", "injury"]
    save_dc: int
    save_ability: str = "con"                # every SRD poison saves vs Constitution
    damage: str | None = None               # dice on a failed save, e.g. "3d6" (None = no damage)
    damage_type: str = "poison"
    conditions: list[str] = Field(default_factory=list)  # SRD condition ids imposed (e.g. "poisoned")
    duration: str | None = None             # how long the conditions last, e.g. "1 hour"


# --- the spell-chassis contract (module-kit S3; shared by pack spells) ---------
# A pack spell is the standard chargen `Spell` shape plus a `chassis`: structured
# combat data constrained to the four action shapes the Arena already executes
# natively (the scoping frame: spells are nearly all "Arena half", so custom
# spells are priced by CONSTRAINING them to proven shapes). The bridge projects
# a chassis into an Arena Action at fight time — no sidecar files, one source of
# truth, exactly like `_project_mechanics` for items. Freeform effects, summons,
# walls and teleports are explicitly v2.0.
ChassisKind = Literal["bolt", "blast", "heal", "hex"]

# Mirrors of the Arena's vocabularies, kept here so `content/` stays free of
# arena imports; a drift-guard test asserts these against the arena enums.
CHASSIS_DAMAGE_TYPES = frozenset({
    "acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic",
    "piercing", "poison", "psychic", "radiant", "slashing", "thunder",
})
# The curated author-facing condition set — each one is applied-and-resolved by
# SRD spells the Arena already runs (Hold Person, Charm Person, Blindness...).
CHASSIS_CONDITIONS = frozenset({
    "blinded", "charmed", "deafened", "frightened", "paralyzed", "poisoned",
    "restrained", "stunned",
})
SaveAbility = Literal["strength", "dexterity", "constitution",
                      "intelligence", "wisdom", "charisma"]

_DAMAGE_DICE_RE = re.compile(r"^\d+d\d+(\+\d+)?$")   # "2d8", "2d6+1"
_PLAIN_DICE_RE = re.compile(r"^\d+d\d+$")            # no flat riders (heal adds MOD)


class SpellChassis(_Strict):
    """The structured half of a pack spell — the author picks a shape and fills
    in numbers. `bolt` = spell attack roll → damage; `blast` = save-or-take AoE;
    `heal` = restore dice + the caster's modifier; `hex` = save vs condition(s)
    held by concentration. Per-kind field rules are enforced whole (aggregated
    into one error) so the Forge can show everything wrong at once."""

    kind: ChassisKind
    range_ft: int = 60                    # 5 = touch; blasts may be 0 (burst from self)
    action_type: Literal["action", "bonus_action"] = "action"
    # bolt / blast
    damage: str | None = None             # dice, e.g. "2d8" or "2d6+1"
    damage_type: str | None = None        # one of CHASSIS_DAMAGE_TYPES
    # blast / hex
    save: SaveAbility | None = None
    # blast
    shape: Literal["sphere", "cone", "line", "cube"] | None = None
    size_ft: int | None = None            # radius / cone-cube size / line length
    on_save: Literal["half", "none"] = "half"
    # heal
    healing: str | None = None            # plain dice; the caster's modifier is added
    # hex
    conditions: list[str] = Field(default_factory=list)  # from CHASSIS_CONDITIONS
    save_ends: bool = True                # target re-saves at the end of its turns
    # upcasting (leveled spells; cantrips scale automatically at 5/11/17)
    upcast_dice: str | None = None        # bolt/blast: +damage dice; heal: +healing dice
    upcast_targets: int = 0               # hex: extra targets per slot level above base

    @model_validator(mode="after")
    def _kind_rules(self) -> "SpellChassis":
        errs: list[str] = []
        k = self.kind

        def forbid(value, name: str, kinds: str) -> None:
            if value:
                errs.append(f"{name} only belongs on a {kinds} chassis")

        if k in ("bolt", "blast"):
            if not (self.damage and _DAMAGE_DICE_RE.match(self.damage)):
                errs.append("damage must be dice like '2d8' or '2d6+1'")
            if self.damage_type not in CHASSIS_DAMAGE_TYPES:
                errs.append(f"damage_type must be one of: "
                            f"{', '.join(sorted(CHASSIS_DAMAGE_TYPES))}")
        else:
            forbid(self.damage, "damage", "bolt or blast")
            forbid(self.damage_type, "damage_type", "bolt or blast")
        if k in ("blast", "hex"):
            if self.save is None:
                errs.append("a save ability is required")
        else:
            forbid(self.save, "save", "blast or hex")
        if k == "blast":
            if self.shape is None:
                errs.append("a blast needs a shape (sphere/cone/line/cube)")
            if not self.size_ft or self.size_ft <= 0:
                errs.append("a blast needs a positive size_ft")
        else:
            forbid(self.shape, "shape", "blast")
            forbid(self.size_ft, "size_ft", "blast")
        if k == "heal":
            if not (self.healing and _PLAIN_DICE_RE.match(self.healing)):
                errs.append("healing must be plain dice like '1d8' "
                            "(the caster's modifier is added automatically)")
        else:
            forbid(self.healing, "healing", "heal")
        if k == "hex":
            if not self.conditions:
                errs.append("a hex needs at least one condition")
            for c in self.conditions:
                if c not in CHASSIS_CONDITIONS:
                    errs.append(f"unknown condition {c!r} — pick from: "
                                f"{', '.join(sorted(CHASSIS_CONDITIONS))}")
        else:
            forbid(self.conditions, "conditions", "hex")
            if self.upcast_targets:
                errs.append("upcast_targets only belongs on a hex chassis")
        if k == "hex" and self.upcast_dice:
            errs.append("upcast_dice does not apply to a hex (use upcast_targets)")
        if self.upcast_dice and not _PLAIN_DICE_RE.match(self.upcast_dice):
            errs.append("upcast_dice must be plain dice like '1d6'")
        if self.upcast_targets < 0:
            errs.append("upcast_targets cannot be negative")
        if self.range_ft < 0:
            errs.append("range_ft cannot be negative")
        if k != "blast" and self.range_ft < 5:
            errs.append("range_ft must be at least 5 (touch)")
        if errs:
            raise ValueError("; ".join(errs))
        return self


class Item(_Strict):
    id: str
    name: str
    category: Literal["weapon", "armor", "gear", "consumable", "treasure", "misc"] = "misc"
    description: str = ""
    # Advisory price hint only (spec §11). A plain int means GOLD pieces (every
    # existing pack stays right); a string names its unit: "5 sp", "3 cp", "1 gp 5 sp".
    base_value: int | str | None = None
    tags: list[str] = Field(default_factory=list)
    slot: str | None = None          # equip slot: main_hand/off_hand/body/feet/...
    weapon: WeaponProfile | None = None
    armor: ArmorProfile | None = None
    # --- magic-item contract (module-kit S1) — same fields as SrdEquipment, so a
    #     pack's Flametongue enters the SAME mechanics catalog the SRD set uses ---
    item_type: ItemType = "mundane"
    rarity: str | None = None        # common / uncommon / rare / very rare / legendary / artifact
    magic_bonus: int | None = None   # +N to attack&damage (weapon) or AC (armor/shield/ring)
    requires_attunement: bool = False  # recorded, NOT enforced (attunement mechanics deferred)
    mechanics: Literal["none", "structured"] = "none"  # does `consumable`/`poison` carry combat data?
    consumable: ConsumableMechanics | None = None
    poison: PoisonMechanics | None = None
    # Worn boons (module-kit S1.5): damage types this item wards WHILE EQUIPPED
    # (Armor of Fire Resistance, a Ring of Poison Immunity). The bridge folds
    # them into the PC's Arena resistances/immunities alongside racial ones.
    grants_resistances: list[str] = Field(default_factory=list)
    grants_immunities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _magic_shape(self) -> "Item":
        """Authoring traps the Forge should catch at save time, not mid-session:
        mechanics payloads must be declared structured (and vice versa), a +N bonus
        only means something on worn/wielded families, and a potion/scroll that
        isn't category 'consumable' could never be drunk (`use_item` refuses it)."""
        payloads = [p for p in (self.consumable, self.poison) if p is not None]
        if len(payloads) > 1:
            raise ValueError("an item carries at most one of {consumable, poison} mechanics")
        if self.mechanics == "structured" and not payloads:
            raise ValueError("mechanics is 'structured' but no consumable/poison payload is set")
        if self.mechanics == "none" and payloads:
            raise ValueError("a consumable/poison payload requires mechanics='structured'")
        if self.magic_bonus is not None and self.item_type not in _EQUIPPABLE_MAGIC:
            raise ValueError(f"magic_bonus needs an equippable item_type "
                             f"({'/'.join(_EQUIPPABLE_MAGIC)}), not {self.item_type!r}")
        if ((self.grants_resistances or self.grants_immunities)
                and self.item_type not in _EQUIPPABLE_MAGIC):
            raise ValueError("worn resistances/immunities need an equippable item_type "
                             "(they apply while the item is equipped) — for a drinkable "
                             "effect use the consumable's grants_resistance instead")
        if self.item_type in ("potion", "scroll") and self.category != "consumable":
            raise ValueError(f"a {self.item_type} must have category 'consumable' "
                             "so it can actually be used up (use_item)")
        return self


# --- stat blocks (bestiary + NPC combat) -------------------------------------
class LootEntry(_Strict):
    """One drop: gold XOR an item stack (mirrors tools.ValueEntry)."""

    gold: int | None = None
    item: str | None = None
    qty: int = 1

    @model_validator(mode="after")
    def _exactly_one(self) -> "LootEntry":
        if (self.gold is not None) == (self.item is not None):
            raise ValueError("LootEntry must set exactly one of {gold, item}")
        if self.gold is not None and self.gold <= 0:
            raise ValueError("loot gold must be positive")
        if self.item is not None and self.qty <= 0:
            raise ValueError("loot qty must be positive")
        return self


class Action(_Strict):
    """One monster action — an attack, a Multiattack instruction, or a special
    move. The combat seam reads the StatBlock's top-level `attack_bonus`/`damage`
    (the primary attack); these entries carry full-SRD fidelity for the panel and
    the eventual tactical resolver. `desc` always holds the verbatim SRD prose, so
    nothing is lost even when an action has no clean structured form."""

    name: str
    desc: str = ""                   # verbatim SRD text (multiattack rules, riders)
    attack_bonus: int | None = None  # set for attack actions ("+5 to hit")
    reach: str | None = None         # "5 ft.", "10 ft.", "30/120 ft." (ranged)
    target: str | None = None        # "one target", "one creature"
    damage: str | None = None        # primary damage dice, e.g. "2d6+3"
    damage_type: str | None = None   # "slashing", "fire", ...


class GrowthStage(_Strict):
    """One authored growth step for a creature companion (companions S2)."""
    to: str                          # the StatBlock id of the next form
    at_party_level: int = 1          # unlocked when the strongest HERO reaches this level


class StatBlock(_Strict):
    id: str
    name: str
    kind: Literal["monster", "npc"] = "monster"

    # --- identity / descriptors (full-SRD fidelity; all optional so the minimal
    #     hand-authored pack blocks still validate) ---------------------------
    size: str | None = None          # Tiny | Small | Medium | Large | Huge | Gargantuan
    type: str | None = None          # "beast", "dragon", "humanoid (goblinoid)", ...
    alignment: str | None = None     # "chaotic evil", "unaligned", ...
    cr: float | None = None          # challenge rating (0.125 = 1/8, 0.25, 0.5, 1, ...)

    # --- core combat numbers -----------------------------------------------
    abilities: dict[str, int] = Field(default_factory=dict)   # str..cha
    hp: int
    hit_dice: str | None = None      # "4d8+8" (HP formula, for display)
    armor_class: int
    ac_desc: str | None = None       # "natural armor", "chain shirt, shield"
    speed: dict[str, str] = Field(default_factory=dict)       # {"walk": "30 ft.", "fly": "60 ft."}

    # --- combat-seam primary attack (the auto-resolver reads THESE) ---------
    attack_bonus: int = 0
    damage: str = "1d4"

    # --- proficiencies & defenses ------------------------------------------
    saves: dict[str, int] = Field(default_factory=dict)       # {"dex": 5, "con": 7}
    skills: list[str] = Field(default_factory=list)           # proficient SRD skills
    skill_bonuses: dict[str, int] = Field(default_factory=dict)  # {"perception": 4} (display)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    senses: dict[str, str] = Field(default_factory=dict)      # {"darkvision": "60 ft.", "passive_perception": "12"}
    languages: str = ""              # "Common, Draconic" or "—"

    # --- prose & actions ----------------------------------------------------
    xp: int = 0
    traits: list[str] = Field(default_factory=list)           # special abilities (prose)
    actions: list[Action] = Field(default_factory=list)
    legendary_actions: list[Action] = Field(default_factory=list)
    reactions: list[Action] = Field(default_factory=list)
    loot: list[LootEntry] = Field(default_factory=list)
    description: str = ""
    srd_ref: str | None = None
    portrait: str | None = None      # image filename in the source's portraits/ dir;
                                     # falls back to "<id>.png", then a silhouette

    # --- AI behavior -------------------------------------------------------
    # Which personality this creature fights with: a built-in preset
    # ("berserker", "coward", ...) or the id of a pack-authored AiProfile. None =
    # "default_monster". Resolved to an AIProfile by the Arena bridge.
    ai_profile: str | None = None

    # --- allegiance (living-world W2) ----------------------------------------
    faction: str | None = None       # -> Faction id this creature belongs to

    # --- authored growth (companions S2) ------------------------------------
    # The next form(s) this creature can grow INTO when kept as a companion —
    # "pseudodragon → adolescent → drake". Each stage names another StatBlock and
    # the party level that unlocks it; chains live one hop per form (the adolescent
    # block carries the drake stage). Unauthored creatures never grow — a loyal
    # pet, not a scaling asset.
    growth: list[GrowthStage] = Field(default_factory=list)


# --- AI personalities --------------------------------------------------------
class AiProfile(_Strict):
    """A reusable monster personality authored in the Forge — *how* a creature
    fights (brave/cowardly, who it targets, melee/ranged, protects allies). The
    bridge maps these fields 1:1 onto the Arena's `AIProfile`; a StatBlock points
    at one by `id`. Mechanical *competence* (multiattack, spells, breath) is
    automatic from the stat block and is NOT configured here."""

    id: str
    name: str

    # Temperament (0.0–2.0; 1.0 = neutral)
    aggression: float = Field(default=1.0, ge=0.0, le=2.0)
    self_preservation: float = Field(default=1.0, ge=0.0, le=2.0)

    # Who it goes after
    target_priority: Literal["nearest", "weakest", "strongest", "random", "threatening"] = "nearest"
    focuses_spellcasters: bool = False

    # How it fights / positions
    prefers_melee: bool = True
    uses_area_attacks: bool = True
    maintains_distance: int = Field(default=0, ge=0, le=120)  # preferred ft from foes (0 = melee)
    flanks_when_possible: bool = True
    avoids_opportunity_attacks: bool = True
    protects_allies: bool = False

    # Resources & nerve
    uses_limited_abilities: float = Field(default=0.5, ge=0.0, le=1.0)  # 0 = hoard, 1 = freely
    retreat_threshold: float = Field(default=0.25, ge=0.0, le=1.0)      # HP% to consider fleeing
    will_flee: bool = False


# --- NPCs --------------------------------------------------------------------
class InvEntry(_Strict):
    item: str
    qty: int = 1


class NPC(_Strict):
    id: str
    name: str
    # How this NPC fights (Forge Phase 4). "none" = today's behaviour: no combat,
    # or a *generic* SRD stat block via `stat_block` (commoner, guard). "creature"
    # = a fully Forge-authored monster (rich `monsters/<id>.json` kit; Seraphel the
    # dragon) — still via `stat_block`, but the editor opens the Phase 3 monster
    # editor. "person" = built with the player chargen/level-up engine, snapshot in
    # `characters/<id>.json` (Phase 4b). The default keeps every legacy NPC valid &
    # in the simple lane; "creature"/"person" are only ever set by explicit choice.
    combat_kind: Literal["none", "creature", "person"] = "none"
    stat_block: str | None = None    # -> StatBlock id (combat stats live there)
    disposition: str = ""            # feeds the DM's DC-setting (D8)
    description: str = ""
    role: str = ""                   # "merchant", "quest_giver", ... (advisory)
    faction: str | None = None       # -> Faction id (living-world W2): the DM plays
                                     # them loyal, and their tier colors the scene
    home_location: str | None = None  # -> Place id (where they're present)
    gold: int | str = 0              # pocket money: int = gp, a string names its unit ("5 sp")
    inventory: list[InvEntry] = Field(default_factory=list)
    # Asking prices by Item id. int = GOLD pieces; a string names its unit ("5 sp").
    price_list: dict[str, int | str] = Field(default_factory=dict)


# --- places (a graph; map-ready) ---------------------------------------------
class Exit(_Strict):
    to: str                          # -> Place id
    label: str = ""                  # prose ("north toward the gate")


# --- audio cues (the location-driven soundscape; design oubliette-audio-mixer) -
# The full authoring shape lands now so later phases add *behaviour*, not schema
# churn (spec §14 — build through the seams). S1 only plays beds; category/scope/
# time/weather/gaps are read by S2/S3/S5 as those phases ship.
class AudioCue(_Strict):
    file: str                        # filename in the pack's audio/ folder
    kind: Literal["bed", "oneshot"] = "bed"            # continuous loop vs sparse one-shot
    category: Literal["music", "sfx"] = "sfx"          # which player volume slider owns it
    scope: Literal["passed_down", "local"] = "local"   # inherited by children, or this place only (S2)
    time: Literal["any", "day", "night"] = "any"       # when it's active (S5)
    weather: Literal["any", "clear", "rain", "storm", "wind"] = "any"  # (S5)
    gain: float = 1.0                # 0..1 layer volume
    min_gap: float | None = None     # one-shot interval seconds (S3)
    max_gap: float | None = None


# --- battle maps (location-battles arc: fights look/sound/play like WHERE they
# happen). The block is authored per Place; the combat bridge reads it at fight
# time and fills the Arena Encounter fields that already exist. No block → the
# generic gray battlefield, exactly as before.
class BattleTerrain(_Strict):
    """One authored battlefield hex. `terrain_type` mirrors the Arena's
    TerrainType enum values — the bridge converts, skipping anything it doesn't
    recognise, so a newer pack degrades instead of crashing an older engine."""

    position: tuple[int, int]        # (q, r) hex coordinate on the battle grid
    terrain_type: Literal[
        "normal", "difficult", "hazard", "water", "pit", "wall",
        "cover_half", "cover_three_quarters", "cover_full",
    ]
    extra_data: dict = Field(default_factory=dict)  # e.g. {"damage": "1d6 fire"}


class BattleMap(_Strict):
    """A Place's battlefield: what a fight staged HERE looks and sounds like.
    Assets live in the pack's existing folders (images/, audio/) so the Forge's
    upload endpoints and world-export zips handle them unchanged."""

    background_image: str | None = None   # filename in the pack's images/ folder
    background_offset: tuple[float, float] = (0.0, 0.0)  # world-space pan (editor-set)
    background_scale: float = 1.0         # 1.0 = image fills the grid bounds
    music_track: str | None = None        # filename in the pack's audio/ folder
    grid_width: int = Field(default=20, ge=5, le=40)
    grid_height: int = Field(default=15, ge=5, le=40)
    terrain: list[BattleTerrain] = Field(default_factory=list)


# --- factions (living-world W2) -----------------------------------------------
class Faction(_Strict):
    """An organized power in the world — a watch, a guild, a cult. The party holds
    a CODE-OWNED standing score with each faction (event-sourced; the DM only
    nudges it, authored quests make the big moves), spoken everywhere in five
    tiers: hostile / unfriendly / neutral / friendly / allied. `agenda` is
    DM-secret fuel; players see name, description, and tier — and nothing at all
    until the faction is KNOWN."""

    id: str
    name: str
    description: str = ""            # player-facing: who they are, as commonly known
    agenda: str = ""                 # DM-ONLY secret: what they actually want
    default_standing: int = Field(default=0, ge=-50, le=50)
    known_from_start: bool = False   # in the party's Factions panel from turn one;
                                     # otherwise ??? until standing first moves


# --- keyed encounters (living-world W1: authored fights bound to a place) ----
# The CODE decides a keyed encounter fires — the DM only narrates the approach —
# and staging is budget-exempt: authored intent outranks the table's
# improvisation caps (min_party_level is the author's own gate).
class KeyedEnemy(_Strict):
    ref: str                         # stat block id/name (pack or SRD) or a pack NPC id
    count: int = Field(default=1, ge=1, le=20)


class KeyedTrigger(_Strict):
    """When a keyed encounter fires. `when` picks the visit rule; the other
    fields are extra conditions ANDed on top. One predicate per field, so later
    arcs (quest state, faction standing) add fields here — not surgery.

    `when: "event"` (living-world W4) makes the encounter DORMANT: it never
    fires on its own — only after a world event ARMS it (the event names this
    place + encounter). The armed fight waits for the party's next visit, and
    time/level conditions are skipped: the event outranks them."""

    when: Literal["first_visit", "every_visit", "event"] = "every_visit"
    time_of_day: Literal["any", "day", "night"] = "any"
    min_party_level: int | None = Field(default=None, ge=1, le=20)


class KeyedEncounter(_Strict):
    id: str
    enemies: list[KeyedEnemy] = Field(min_length=1)
    trigger: KeyedTrigger = Field(default_factory=KeyedTrigger)
    once: bool = True                # fire at most once per campaign; False re-arms
                                     # each new visit (night wolves you dodged by day)
    briefing: str = ""               # DM-secret staging text ("they drop from the rafters")


class Place(_Strict):
    id: str
    name: str
    description: str                 # becomes the SCENE when the party is here
    parent: str | None = None        # -> Place id this is a sublocation OF (Atria >
                                     # Brightvale > Marketplace; dungeon > rooms)
    image: str | None = None         # illustration filename in the pack's images/ folder
                                     # (used for quest cards; top-level areas mainly)
    map_image: str | None = None     # background map image (in images/) shown when you
                                     # drill INTO this place — its children's sub-map
    tags: list[str] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)           # the map's edges
    position: dict | None = None     # {x,y} percent — this place's PIN on its parent's map
    sounds: list[AudioCue] = Field(default_factory=list)      # the place's soundscape cues
    battle: BattleMap | None = None  # what a fight HERE looks/sounds like (Arena)
    encounters: list[KeyedEncounter] = Field(default_factory=list)  # authored fights
                                     # bound to this place (living-world W1)
    safe_haven: bool = False         # a truly safe overnight spot (an inn, a temple):
                                     # long rests here cost lodging coin and are never
                                     # interrupted; unflagged places follow wilderness
                                     # rules — rations, and risk on dangerous tables (S3)


# --- lore (authored world history/legend the DM can draw on) ----------------
class Lore(_Strict):
    id: str
    title: str
    text: str                        # the lore itself — concentrated, the DM weaves it in
    subjects: list[str] = Field(default_factory=list)  # free-form "about" names/topics
                                     # (Brightvale, Silverfin Bay, Alden, Seraphel) — they
                                     # need NOT be real entities; used to surface the lore
    tags: list[str] = Field(default_factory=list)


# --- authored quests ---------------------------------------------------------
class QuestReward(_Strict):
    """A quest's reward. ADVISORY only — it's surfaced to the DM, who hands it over with
    the ordinary give/transact tools (so the player can even renegotiate). The engine never
    auto-grants it. Like LootEntry, at most one of {gold, item}; a purely narrative reward
    (a title, a favor owed) is fine as a `note` with neither."""

    gold: int | None = None
    item: str | None = None          # -> Item id
    qty: int = 1
    note: str = ""                   # free advisory text ("plus the captain's gratitude")

    @model_validator(mode="after")
    def _shape(self) -> "QuestReward":
        if self.gold is not None and self.item is not None:
            raise ValueError("a reward sets at most one of {gold, item}")
        if self.gold is not None and self.gold <= 0:
            raise ValueError("reward gold must be positive")
        if self.item is not None and self.qty <= 0:
            raise ValueError("reward qty must be positive")
        if self.gold is None and self.item is None and not self.note.strip():
            raise ValueError("a reward needs gold, an item, or a note")
        return self


class QuestTrinket(_Strict):
    """A keepsake the quest leaves in the party's hands — a torn map corner, a note
    from a noble — offered to the PLAYER (never the DM) to tape into their journal.
    Purely cosmetic: no stats, no inventory entry, never in the DM's context. The
    engine surfaces it when its moment arrives; the journal does the rest."""

    id: str                          # stable within the quest (the Forge autofills)
    image: str                       # filename in the pack's images/ folder
    caption: str = ""                # the words under the taped-in thing
    when: Literal["accepted", "completed"] = "completed"
    outcome: str = ""                # completion-only filter: granted only when this
                                     # outcome was reported ("" = any ending)

    @model_validator(mode="after")
    def _shape(self) -> "QuestTrinket":
        if not self.image.strip():
            raise ValueError("a trinket needs an image")
        if self.outcome and self.when != "completed":
            raise ValueError("an outcome filter only applies to a completion trinket")
        return self


class QuestStanding(_Strict):
    """A standing consequence the quest carries (living-world W2): taking it up
    or completing it moves the party's standing with a faction. These are the
    BIG, authored moves — the DM's adjust_standing tool only nudges. Completion
    deltas can filter on an outcome, like trinkets."""

    faction: str                     # -> Faction id
    delta: int = Field(ge=-50, le=50)  # raw standing points (a tier is 20 wide)
    when: Literal["accepted", "completed"] = "completed"
    outcome: str = ""                # completion-only filter ("" = any ending)

    @model_validator(mode="after")
    def _shape(self) -> "QuestStanding":
        if self.delta == 0:
            raise ValueError("a standing consequence needs a non-zero delta")
        if self.outcome and self.when != "completed":
            raise ValueError("an outcome filter only applies to a completion delta")
        return self


class MinStanding(_Strict):
    """A quest gate (living-world W2): hidden until the party's standing with
    `faction` has reached `tier` — the reputation sibling of min_party_level."""

    faction: str                     # -> Faction id
    tier: Literal["hostile", "unfriendly", "neutral", "friendly", "allied"] = "friendly"


class QuestBranch(_Strict):
    """One outcome -> next-quest edge of a branching chain. At completion the DM reports an
    `outcome` label (from the quest's OUTCOMES shown in context); the matching branch unlocks
    its `to` quest as a new offer."""

    outcome: str                     # the label the DM picks, e.g. "spared", "killed"
    to: str                          # -> AuthoredQuest id this outcome unlocks


class AuthoredQuest(_Strict):
    """A pre-written quest shipped in a pack (designed in The Forge). It is OFFERED during
    play — never auto-started — and tied to exactly one source: a quest-giver NPC, or a place
    (found there, e.g. on a notice board). Standalone one-shots have no branches; a branching
    chain links quests by outcome. Chains are implicit: a quest is reachable if it's a `root`
    or named in some other quest's `branches[].to` (the `chain` label is for display only)."""

    id: str
    title: str
    hook: str = ""                   # PLAYER-FACING: the offer as the party hears it (at source)
    rumor: str = ""                  # optional region-wide breadcrumb the DM may drop as ambient
                                     # gossip ("dockworkers whisper of missing cargo")
    briefing: str = ""               # DM-ONLY secret: the real situation / twist / intended end
    giver_npc: str | None = None     # -> NPC id      } exactly one source
    giver_place: str | None = None   # -> Place id    }
    discovery: str = ""              # required iff giver_place; how it's found ("a notice board")
    reward: QuestReward | None = None
    chain: str = ""                  # optional grouping/label for an arc (Forge display only)
    root: bool = False               # offerable from the start (no prior quest needed to unlock)
    min_party_level: int | None = None  # gate: hidden until the party reaches this level
                                     # ("starts at party level 3+"); None = no gate. The DM
                                     # never sees a gated quest until the party qualifies, so
                                     # it can't leak it early and the context stays lean (S2).
    branches: list[QuestBranch] = Field(default_factory=list)
    trinkets: list[QuestTrinket] = Field(default_factory=list)
    standing: list[QuestStanding] = Field(default_factory=list)  # faction consequences (W2)
    min_standing: MinStanding | None = None  # gate: hidden until the party's standing
                                     # with a faction reaches a tier (W2); None = no gate
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _source(self) -> "AuthoredQuest":
        if (self.giver_npc is not None) == (self.giver_place is not None):
            raise ValueError("a quest sets exactly one of {giver_npc, giver_place}")
        if self.giver_place is not None and not self.discovery.strip():
            raise ValueError("a place-given quest needs a `discovery` note (how it's found)")
        if self.giver_npc is not None and self.discovery.strip():
            raise ValueError("`discovery` only applies to a place-given quest")
        ids = [t.id for t in self.trinkets]
        if len(ids) != len(set(ids)):
            raise ValueError("trinket ids must be unique within a quest")
        labels = {b.outcome for b in self.branches}
        for t in self.trinkets:
            if t.outcome and t.outcome not in labels:
                raise ValueError(
                    f"trinket {t.id!r} filters on outcome {t.outcome!r}, "
                    "which is not one of this quest's branch outcomes")
        for st in self.standing:
            if st.outcome and st.outcome not in labels:
                raise ValueError(
                    f"a standing delta for {st.faction!r} filters on outcome "
                    f"{st.outcome!r}, which is not one of this quest's branch outcomes")
        return self


# --- timed world events (living-world W4) -------------------------------------
class EventStanding(_Strict):
    """A standing shift a world event carries. Unlike quest deltas, an event's
    shift does NOT reveal the faction — the world can turn against the party
    in the dark (reveal it with the DM's delta-0 when the story surfaces it)."""

    faction: str                     # -> Faction id
    delta: int = Field(ge=-50, le=50)

    @model_validator(mode="after")
    def _nonzero(self) -> "EventStanding":
        if self.delta == 0:
            raise ValueError("an event standing shift needs a non-zero delta")
        return self


class EventEncounter(_Strict):
    """ARM a keyed encounter: after the event fires, the named fight triggers
    on the party's next visit to its place (immediately if they stand there).
    Pair it with a `when: "event"` encounter for a fight that exists ONLY
    because this event happened."""

    place: str                       # -> Place id
    encounter: str                   # -> KeyedEncounter id at that place


class EventEnvironment(_Strict):
    time_of_day: Literal["day", "night"] | None = None
    weather: Literal["clear", "rain", "storm", "wind"] | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "EventEnvironment":
        if self.time_of_day is None and self.weather is None:
            raise ValueError("an environment change must set time_of_day and/or weather")
        return self


class WorldEvent(_Strict):
    """A scheduled happening — the world moving whether the party attends or
    not. The CODE decides it fires (against the campaign clock + conditions);
    the DM narrates it live if the party is at its place, or lets the news
    arrive as rumor if they're elsewhere. At most ONE event fires per turn;
    an overdue backlog trickles in turn by turn."""

    id: str
    title: str = ""                  # Forge display label
    # -- when (at least one of on_day / every_days) ---------------------------
    on_day: int | None = Field(default=None, ge=1, le=10_000)   # first (or only) firing day
    every_days: int | None = Field(default=None, ge=1, le=1000)  # repeat interval; with no
                                     # on_day the first firing lands after one interval
    quest_done: str | None = None    # condition: this authored quest is completed
    min_standing: MinStanding | None = None   # condition: party tier with a faction
    # -- where (presentation only — the event fires regardless) ---------------
    place: str | None = None         # venue; party present = seen live, absent = rumor
    # -- what (at least one) ---------------------------------------------------
    announce: str = ""               # what the world learns — the DM conveys this
    briefing: str = ""               # DM-secret truth behind it
    standing: list[EventStanding] = Field(default_factory=list)
    encounter: EventEncounter | None = None
    environment: EventEnvironment | None = None
    unlock_quest: str | None = None  # make an authored quest offerable (even a non-root)
    retire_quest: str | None = None  # withdraw an authored quest from offer

    @model_validator(mode="after")
    def _shape(self) -> "WorldEvent":
        if self.on_day is None and self.every_days is None:
            raise ValueError("an event needs a schedule: on_day and/or every_days")
        if not (self.announce.strip() or self.briefing.strip() or self.standing
                or self.encounter or self.environment
                or self.unlock_quest or self.retire_quest):
            raise ValueError("an event needs something to say or do "
                             "(announce/briefing, or an effect)")
        if self.unlock_quest is not None and self.unlock_quest == self.retire_quest:
            raise ValueError("an event cannot unlock and retire the same quest")
        return self


# --- scenarios ---------------------------------------------------------------
class Scenario(_Strict):
    id: str
    name: str
    start_location: str              # -> Place id
    scene_override: str | None = None  # optional: override the opening scene text
    party_source: Literal["creator", "default"] = "creator"
    # STOPGAP until character creation lands: a full PC definition (state.Character
    # shape) the app can start with so a pack is playable now. Once chargen ships,
    # the normal path is party_source "creator" and this is only a demo/test party.
    default_party: list[dict] = Field(default_factory=list)
