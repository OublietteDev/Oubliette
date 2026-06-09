"""The Arena bridge (combat Stage 2): pure data mapping between Oubliette's
state/content models and The Arena's tactical-engine models.

Two directions, no I/O and no live-loop wiring (that is Stage 3 — "flip the
switch"):

  OUT  Oubliette party (`Character`) + chosen enemies (bestiary `StatBlock`,
       ephemeral `CombatantTemplate`, or a persistent NPC `Character`) + an
       `EncounterRequest` → an Arena `Encounter` (inline `creature_data`, teams,
       starting hexes on a default grid keyed to terrain kind).

  BACK the Arena handoff result dict (`arena.handoff.build_result`) → an
       Oubliette `CombatResult` (absolute final HP per *persistent* entity,
       fallen-enemy XP + loot).

Fidelity is "basic-attack" (D-COMBAT-4): every combatant fields ONE basic attack
built from Oubliette's flat `attack_bonus` + `damage` dice spec. Real ability
scores are carried across faithfully; to reproduce the flat `attack_bonus`
exactly — the Arena rolls to-hit as ability_mod + proficiency_bonus — we solve
for a (carrier-ability, proficiency_bonus) pair that lands on it without
corrupting the real scores (see `_solve_to_hit`). Saves/skills/rich actions are
Stage 4.

The back-map needs a correspondence between Arena combatants (keyed by display
name in the result) and Oubliette entities; `build_encounter` returns an
`EncounterPlan` carrying that map, which `result_to_combat_result` consumes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    TargetType,
)
from arena.models.character import Creature, CreatureSize, CreatureType, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter, TerrainHex, TerrainType
from arena.models.monster import Monster

from ..content.schemas import StatBlock
from ..state.models import Character
from ..tools.schemas import ValueEntry
from .schemas import CombatResult, Outcome, TerrainSpec
from .templates import CombatantTemplate

# --- Defaults ------------------------------------------------------------

GRID_WIDTH = 20
GRID_HEIGHT = 15
_PLAYER_COL = 2
_ENEMY_COL = GRID_WIDTH - 3
DEFAULT_DAMAGE_TYPE = DamageType.SLASHING

_ABILITY_LONG = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
# Preference order for the to-hit carrier ability (natural attack stats first).
_CARRIER_ORDER = ["str", "dex", "con", "wis", "int", "cha"]


# --- Small pure helpers --------------------------------------------------

def _norm_abilities(abilities: dict) -> dict[str, int]:
    """Normalise an Oubliette abilities dict (keys may be the `Ability` enum or
    short strings like "str") to plain short-key ints, defaulting to 10."""
    out = {k: 10 for k in _ABILITY_LONG}
    for k, v in abilities.items():
        key = getattr(k, "value", k)
        if key in out:
            out[key] = int(v)
    return out


def _mod(score: int) -> int:
    """SRD ability modifier."""
    return (score - 10) // 2


def _ability_scores(short: dict[str, int]) -> AbilityScores:
    return AbilityScores(**{_ABILITY_LONG[k]: v for k, v in short.items()})


def _parse_damage(spec: str) -> tuple[str, int]:
    """Split an Oubliette dice spec ("2d6+1", "1d4-1", "1d6") into (dice, flat).
    Falls back to ("1d4", 0) on anything unparseable."""
    m = re.match(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$", spec or "")
    if not m:
        return "1d4", 0
    dice = f"{int(m.group(1))}d{int(m.group(2))}"
    flat = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    return dice, flat


def _solve_to_hit(short: dict[str, int], attack_bonus: int) -> tuple[str, int]:
    """Return (carrier_ability_long, proficiency_bonus) so that the Arena's
    to-hit (ability_mod(carrier) + proficiency_bonus) equals `attack_bonus`
    exactly, without altering the real ability scores.

    The Arena clamps proficiency_bonus to [2, 9]. For SRD monsters the natural
    attacking ability already satisfies this (attack_bonus = mod + prof by
    construction); otherwise we pick whichever real ability lets prof land in
    range. If no ability yields an in-range prof (very extreme inputs) we clamp
    and accept a residual on the to-hit only.
    """
    # (-mod, carrier_priority, ability, prof): prefer the highest real ability
    # modifier (the creature's natural attacking stat → the SRD decomposition,
    # e.g. a goblin lands on DEX+prof2), tie-broken by carrier preference.
    exact: list[tuple[int, int, str, int]] = []
    for i, key in enumerate(_CARRIER_ORDER):
        prof = attack_bonus - _mod(short[key])
        if 2 <= prof <= 9:
            exact.append((-_mod(short[key]), i, key, prof))
    if exact:
        _, _, key, prof = min(exact)
        return _ABILITY_LONG[key], prof
    # Unreachable target (very extreme inputs): pick the (carrier, clamped prof)
    # that minimises the to-hit residual. Damage and ability scores stay exact;
    # only the to-hit drifts by the unavoidable residual.
    best: tuple[int, int, str, int] | None = None  # (residual, priority, ability, prof)
    for i, key in enumerate(_CARRIER_ORDER):
        prof = min(9, max(2, attack_bonus - _mod(short[key])))
        residual = abs(attack_bonus - (_mod(short[key]) + prof))
        cand = (residual, i, key, prof)
        if best is None or cand < best:
            best = cand
    assert best is not None
    return _ABILITY_LONG[best[2]], best[3]


def _basic_attack(
    name: str,
    short: dict[str, int],
    attack_bonus: int,
    damage: str,
    damage_type: DamageType,
    proficiency_bonus: int,
    carrier_long: str,
) -> Action:
    """One melee basic-attack Action whose to-hit resolves to `attack_bonus`
    (via the solved carrier ability + proficiency_bonus) and whose damage is the
    literal dice spec with a flat bonus (no ability modifier, so it is exact)."""
    dice, flat = _parse_damage(damage)
    return Action(
        name=name,
        description=f"{name}: +{attack_bonus} to hit, reach 5 ft., one target.",
        action_type=ActionType.ACTION,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name=name,
            attack_type="melee_weapon",
            ability=carrier_long,
            reach=5,
            damage=[DamageRoll(dice=dice, damage_type=damage_type, bonus=flat)],
        ),
        ai_priority=6,
    )


def _size(value: str | None) -> CreatureSize:
    try:
        return CreatureSize((value or "medium").strip().lower())
    except ValueError:
        return CreatureSize.MEDIUM


def _creature_type(value: str | None) -> CreatureType:
    # StatBlock types look like "humanoid (goblinoid)" — take the leading word.
    head = (value or "humanoid").strip().lower().split(" ")[0].split("(")[0]
    try:
        return CreatureType(head)
    except ValueError:
        return CreatureType.HUMANOID


def _loot_to_value(entries) -> list[ValueEntry]:
    """Map content `LootEntry` (gold|item/qty) → boundary `ValueEntry`
    (gold|item_id/qty)."""
    out: list[ValueEntry] = []
    for e in entries:
        if getattr(e, "gold", None) is not None:
            out.append(ValueEntry(gold=e.gold))
        elif getattr(e, "item", None) is not None:
            out.append(ValueEntry(item_id=e.item, qty=getattr(e, "qty", 1)))
    return out


# --- OUT: Oubliette → Arena creatures ------------------------------------

def character_to_player(char: Character) -> PlayerCharacter:
    """Map a party member (`Character`, kind=pc) → an Arena `PlayerCharacter`."""
    short = _norm_abilities(char.abilities)
    carrier, prof = _solve_to_hit(short, char.attack_bonus)
    char_class = char.sheet.char_class if char.sheet else "Adventurer"
    race = char.sheet.race if char.sheet else "Human"
    return PlayerCharacter(
        name=char.name,
        size=_size(char.sheet.size if char.sheet else None),
        ability_scores=_ability_scores(short),
        armor_class=max(1, char.armor_class),
        max_hit_points=max(1, char.max_hp),
        current_hit_points=max(0, char.hp),
        proficiency_bonus=prof,
        character_class=char_class,
        level=char.level,
        race=race,
        is_player_controlled=True,
        actions=[
            _basic_attack(
                "Attack", short, char.attack_bonus, char.damage,
                DEFAULT_DAMAGE_TYPE, prof, carrier,
            )
        ],
    )


def statblock_to_monster(sb: StatBlock) -> Monster:
    """Map a bestiary `StatBlock` → an Arena `Monster`."""
    short = _norm_abilities(sb.abilities)
    carrier, prof = _solve_to_hit(short, sb.attack_bonus)
    dtype = DEFAULT_DAMAGE_TYPE
    if sb.actions and sb.actions[0].damage_type:
        try:
            dtype = DamageType(sb.actions[0].damage_type.strip().lower())
        except ValueError:
            dtype = DEFAULT_DAMAGE_TYPE
    return Monster(
        name=sb.name,
        size=_size(sb.size),
        creature_type=_creature_type(sb.type),
        alignment=sb.alignment,
        ability_scores=_ability_scores(short),
        armor_class=max(1, sb.armor_class),
        max_hit_points=max(1, sb.hp),
        proficiency_bonus=prof,
        damage_resistances=list(sb.damage_resistances),
        damage_immunities=list(sb.damage_immunities),
        damage_vulnerabilities=list(sb.damage_vulnerabilities),
        condition_immunities=list(sb.condition_immunities),
        challenge_rating=float(sb.cr) if sb.cr is not None else 0.0,
        experience_points=sb.xp,
        is_player_controlled=False,
        actions=[
            _basic_attack(
                sb.actions[0].name if sb.actions else "Attack",
                short, sb.attack_bonus, sb.damage, dtype, prof, carrier,
            )
        ],
    )


def template_to_monster(tmpl: CombatantTemplate) -> Monster:
    """Map an ephemeral `CombatantTemplate` → an Arena `Monster`. Templates carry
    no ability scores, so they default to 10s (mods 0) and the to-hit rides on
    proficiency_bonus alone."""
    short = {k: 10 for k in _ABILITY_LONG}
    carrier, prof = _solve_to_hit(short, tmpl.attack_bonus)
    return Monster(
        name=tmpl.name,
        ability_scores=_ability_scores(short),
        armor_class=max(1, tmpl.armor_class),
        max_hit_points=max(1, tmpl.hp),
        proficiency_bonus=prof,
        experience_points=tmpl.xp,
        is_player_controlled=False,
        actions=[
            _basic_attack(
                "Attack", short, tmpl.attack_bonus, tmpl.damage,
                DEFAULT_DAMAGE_TYPE, prof, carrier,
            )
        ],
    )


def character_to_monster(char: Character) -> Monster:
    """Map a persistent NPC (`Character`, kind=npc) used as an enemy → a (AI-
    controlled) Arena `Monster`."""
    short = _norm_abilities(char.abilities)
    carrier, prof = _solve_to_hit(short, char.attack_bonus)
    return Monster(
        name=char.name,
        ability_scores=_ability_scores(short),
        armor_class=max(1, char.armor_class),
        max_hit_points=max(1, char.max_hp),
        current_hit_points=max(0, char.hp),
        proficiency_bonus=prof,
        experience_points=char.xp,
        is_player_controlled=False,
        actions=[
            _basic_attack(
                "Attack", short, char.attack_bonus, char.damage,
                DEFAULT_DAMAGE_TYPE, prof, carrier,
            )
        ],
    )


# --- Enemy instances + encounter assembly --------------------------------

@dataclass
class EnemyInstance:
    """One resolved enemy ready to drop into an Arena encounter, plus the
    Oubliette bookkeeping the back-map needs.

    `entity_id` is set iff this enemy is a persistent entity (its final HP is
    written back); ephemeral template/bestiary spawns leave it None.
    """

    creature: Creature
    xp: int = 0
    loot: list[ValueEntry] = field(default_factory=list)
    entity_id: str | None = None


def enemy_from_statblock(sb: StatBlock) -> EnemyInstance:
    return EnemyInstance(
        creature=statblock_to_monster(sb), xp=sb.xp, loot=_loot_to_value(sb.loot)
    )


def enemy_from_template(tmpl: CombatantTemplate) -> EnemyInstance:
    return EnemyInstance(
        creature=template_to_monster(tmpl), xp=tmpl.xp, loot=list(tmpl.loot)
    )


def enemy_from_character(char: Character) -> EnemyInstance:
    # Persistent foes are written back but (mirroring the boundary) drop no loot.
    return EnemyInstance(
        creature=character_to_monster(char), xp=char.xp, loot=[], entity_id=char.id
    )


@dataclass
class EncounterPlan:
    """The assembled Arena encounter plus the correspondence the back-map needs.
    Arena keys result combatants by display name, so we pin a unique name per
    combatant and index our bookkeeping by it."""

    encounter: Encounter
    persistent_ids: dict[str, str] = field(default_factory=dict)  # name -> entity_id
    loot_by_name: dict[str, list[ValueEntry]] = field(default_factory=dict)


# Default terrain palettes, keyed to `TerrainSpec.kind`. A starting point —
# richer/authored terrain is a later concern.
def _terrain_for(kind: str) -> list[TerrainHex]:
    if kind == "chokepoint":
        gap = {6, 7, 8}
        return [
            TerrainHex(position=(GRID_WIDTH // 2, r), terrain_type=TerrainType.WALL)
            for r in range(GRID_HEIGHT)
            if r not in gap
        ]
    if kind == "ambush_cover":
        return [
            TerrainHex(position=p, terrain_type=TerrainType.COVER_HALF)
            for p in [(8, 4), (11, 9), (9, 11), (12, 5)]
        ]
    return []


def _column_positions(count: int, q: int) -> list[tuple[int, int]]:
    """Evenly distribute `count` tokens down column `q`, vertically centred."""
    if count <= 0:
        return []
    span = min(count, GRID_HEIGHT)
    start = max(0, (GRID_HEIGHT - span) // 2)
    return [(q, min(GRID_HEIGHT - 1, start + i)) for i in range(count)]


def _unique(name: str, used: set[str]) -> str:
    """A display name unique within the encounter ("Goblin", "Goblin 2", ...)."""
    if name not in used:
        used.add(name)
        return name
    i = 2
    while f"{name} {i}" in used:
        i += 1
    out = f"{name} {i}"
    used.add(out)
    return out


def build_encounter(
    party: list[Character],
    enemies: list[EnemyInstance],
    terrain: TerrainSpec,
    *,
    name: str = "Encounter",
) -> EncounterPlan:
    """Assemble an Arena `Encounter` from the live party + resolved enemies +
    terrain. Counts are pre-expanded (one `CombatantEntry` per individual, with
    a unique `name_override`) so the returned result is matchable by name."""
    used: set[str] = set()
    entries: list[CombatantEntry] = []
    persistent_ids: dict[str, str] = {}
    loot_by_name: dict[str, list[ValueEntry]] = {}

    party_pos = _column_positions(len(party), _PLAYER_COL)
    for char, pos in zip(party, party_pos):
        display = _unique(char.name, used)
        creature = character_to_player(char)
        creature.name = display
        entries.append(
            CombatantEntry(
                creature_id=f"pc/{char.id}",
                creature_data=creature,
                team="player",
                starting_position=pos,
                name_override=display,
            )
        )
        persistent_ids[display] = char.id  # PCs are always written back

    enemy_pos = _column_positions(len(enemies), _ENEMY_COL)
    for inst, pos in zip(enemies, enemy_pos):
        display = _unique(inst.creature.name, used)
        creature = inst.creature.model_copy(deep=True)
        creature.name = display
        entries.append(
            CombatantEntry(
                creature_id=f"enemy/{display}",
                creature_data=creature,
                team="enemy",
                starting_position=pos,
                name_override=display,
            )
        )
        if inst.entity_id:
            persistent_ids[display] = inst.entity_id
        if inst.loot:
            loot_by_name[display] = list(inst.loot)

    encounter = Encounter(
        name=name,
        grid_width=GRID_WIDTH,
        grid_height=GRID_HEIGHT,
        terrain=_terrain_for(terrain.kind),
        combatants=entries,
        use_ai_for_enemies=True,
        use_ai_for_allies=False,
    )
    return EncounterPlan(
        encounter=encounter,
        persistent_ids=persistent_ids,
        loot_by_name=loot_by_name,
    )


# --- BACK: Arena result dict → Oubliette CombatResult --------------------

_OUTCOME_MAP: dict[str, Outcome] = {"victory": "victory", "defeat": "defeat"}


def result_to_combat_result(handoff: dict, plan: EncounterPlan) -> CombatResult:
    """Map an Arena handoff result dict (`arena.handoff.build_result`) back into
    an Oubliette `CombatResult`.

    - Persistent combatants (PCs + persistent NPC foes) get absolute HP +
      conditions write-back; ephemeral spawns never appear (D7).
    - On victory, XP is summed from fallen enemies and loot dropped for those
      with a loot table.
    - A window closed mid-fight ("unresolved") maps to `flee`: no XP/loot, but
      the partial HP/conditions are still written back (you took your hits then
      broke away).
    """
    raw_outcome = handoff.get("outcome", "unresolved")
    outcome: Outcome = _OUTCOME_MAP.get(raw_outcome, "flee")

    combatants = handoff.get("combatants", [])
    hp_final: dict[str, int] = {}
    conditions_final: dict[str, list[str]] = {}
    loot: list[ValueEntry] = []
    xp_award = 0
    survivors: list[str] = []

    for c in combatants:
        cname = c.get("name", "")
        entity_id = plan.persistent_ids.get(cname)
        if entity_id is not None:
            hp_final[entity_id] = int(c.get("hp", 0))
            conditions_final[entity_id] = list(c.get("conditions", []))

        if c.get("team") == "enemy":
            fallen = not c.get("is_conscious", True)
            if fallen and outcome == "victory":
                xp_award += int(c.get("xp", 0) or 0)
                loot.extend(plan.loot_by_name.get(cname, []))
            elif not fallen and entity_id is None:
                survivors.append(cname)

    digest = _digest(outcome, combatants, xp_award, loot)
    return CombatResult(
        outcome=outcome,
        hp_final=hp_final,
        conditions_final=conditions_final,
        loot=loot,
        xp_award=xp_award,
        narrative_digest=digest,
        ephemeral_survivors=survivors,
    )


def _digest(outcome: Outcome, combatants: list[dict], xp: int, loot: list[ValueEntry]) -> str:
    fallen = [
        c.get("name", "?")
        for c in combatants
        if c.get("team") == "enemy" and not c.get("is_conscious", True)
    ]
    if outcome == "victory":
        from .boundary import loot_str
        tail = f" and {loot_str(loot)}." if loot else "."
        return (
            f"The fight ends in your favor. Fallen: {', '.join(fallen) or 'none'}. "
            f"You take {xp} XP{tail}"
        )
    if outcome == "defeat":
        return "You are beaten down and fall. The encounter is lost."
    return "You break off the fight and slip away before it is settled."
