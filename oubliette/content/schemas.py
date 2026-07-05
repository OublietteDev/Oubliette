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
    branches: list[QuestBranch] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _source(self) -> "AuthoredQuest":
        if (self.giver_npc is not None) == (self.giver_place is not None):
            raise ValueError("a quest sets exactly one of {giver_npc, giver_place}")
        if self.giver_place is not None and not self.discovery.strip():
            raise ValueError("a place-given quest needs a `discovery` note (how it's found)")
        if self.giver_npc is not None and self.discovery.strip():
            raise ValueError("`discovery` only applies to a place-given quest")
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
