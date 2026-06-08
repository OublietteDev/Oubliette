"""Strict, versioned schemas for authored content (design doc §3).

Every model forbids unknown fields (`extra="forbid"`) so a typo in a pack file is
a load error, not a silent drop. Ids are stable, unique-within-type slugs. These
are the *authoring* shapes; the loader projects them onto the engine's runtime
models (`state.Item`, `state.Character`) — see `loader.py`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump when a breaking change to these shapes ships; packs carry their own
# `schema_version` so the loader can refuse / migrate incompatible packs later.
SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- pack manifest -----------------------------------------------------------
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


# --- items -------------------------------------------------------------------
class WeaponProfile(_Strict):
    attack_bonus: int = 0
    damage: str                      # dice spec, e.g. "1d6+1"
    properties: list[str] = Field(default_factory=list)  # finesse, light, ...


class ArmorProfile(_Strict):
    base_ac: int
    type: Literal["light", "medium", "heavy", "shield"]
    dex_cap: int | None = None       # reserved for the eventual AC computation


class Item(_Strict):
    id: str
    name: str
    category: Literal["weapon", "armor", "gear", "consumable", "treasure", "misc"] = "misc"
    description: str = ""
    base_value: int | None = None    # advisory price hint only (spec §11)
    tags: list[str] = Field(default_factory=list)
    slot: str | None = None          # equip slot: main_hand/off_hand/body/feet/...
    weapon: WeaponProfile | None = None
    armor: ArmorProfile | None = None


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


class StatBlock(_Strict):
    id: str
    name: str
    kind: Literal["monster", "npc"] = "monster"
    abilities: dict[str, int] = Field(default_factory=dict)   # str..cha
    hp: int
    armor_class: int
    attack_bonus: int = 0
    damage: str = "1d4"
    xp: int = 0
    skills: list[str] = Field(default_factory=list)           # proficient SRD skills
    traits: list[str] = Field(default_factory=list)           # special abilities (prose)
    loot: list[LootEntry] = Field(default_factory=list)
    description: str = ""
    srd_ref: str | None = None


# --- NPCs --------------------------------------------------------------------
class InvEntry(_Strict):
    item: str
    qty: int = 1


class NPC(_Strict):
    id: str
    name: str
    stat_block: str | None = None    # -> StatBlock id (combat stats live there)
    disposition: str = ""            # feeds the DM's DC-setting (D8)
    description: str = ""
    role: str = ""                   # "merchant", "quest_giver", ... (advisory)
    home_location: str | None = None  # -> Place id (where they're present)
    gold: int = 0
    inventory: list[InvEntry] = Field(default_factory=list)
    price_list: dict[str, int] = Field(default_factory=dict)  # asking prices -> Item ids


# --- places (a graph; map-ready) ---------------------------------------------
class Exit(_Strict):
    to: str                          # -> Place id
    label: str = ""                  # prose ("north toward the gate")


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


# --- lore (authored world history/legend the DM can draw on) ----------------
class Lore(_Strict):
    id: str
    title: str
    text: str                        # the lore itself — concentrated, the DM weaves it in
    subjects: list[str] = Field(default_factory=list)  # free-form "about" names/topics
                                     # (Brightvale, Silverfin Bay, Alden, Seraphel) — they
                                     # need NOT be real entities; used to surface the lore
    tags: list[str] = Field(default_factory=list)


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
