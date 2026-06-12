"""C1 feature bridge: stage the sheet's class features into the Arena.

The Arena engine already carries declarative `Feature` machinery — extra
attacks, on-hit riders (smite/sneak/stun), auras, evasion, damage-reduction
reactions, forced rerolls, death prevention — all read from
``creature.features``, which the bridge never populated. This module is the
staging map: sheet `FeatureRef` names (set at chargen from the SRD ruleset,
so the names are stable keys) → engine `Feature` objects and curated
`Action`s, scaled to the character's CURRENT level.

Same bake philosophy as B3/B4: numbers are resolved here (sneak dice, rage
bonus, aura ranges), the engine just executes. Two deliberate exclusions:

  - Unarmored Defense is NOT staged — the story-side AC derivation already
    includes it, and staging it engine-side would double-count.
  - Fighting Style is NOT staged — chargen stores no style choice (the
    feature is prose-only in the ruleset data); a style picker is story-side
    work, not bridge work.

Cunning Action, Step of the Wind, and Vanish ride the engine's
``Action.standard_effect`` hook (C1): a data Action that routes to the
built-in Dash/Disengage/Hide logic under its own bonus-action economy and
resource cost. Deferred to Phase C4 primitives: Turn Undead (type-filtered
AoE + flee), Bardic Inspiration / Cutting Words (reaction-modify-roll),
Cleansing Touch (P-DISPEL), Sculpt Spells (AoE ally exemption).

Resource keys: the story side tracks pools under display names ("Ki",
"Lay on Hands"); engine presets and standard actions key snake_case names
("ki_points", "action_surge"). `engine_resource_key` is the one place that
mapping lives — the outbound staging and the result back-map both use it,
so story-side ops keep their display-name keys untouched.
"""

from __future__ import annotations

from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    TargetType,
)
from arena.models.character import Feature, OnHitRider, RiderTrigger
from arena.models.conditions import BuffEffect

from ..enums import Ability
from ..state.models import Character

# --- Resource-name normalization ------------------------------------------

# Display name (lowercased, underscored) → engine key, where they differ.
_RESOURCE_ALIASES = {"ki": "ki_points"}


def engine_resource_key(display_name: str) -> str:
    """The Arena-side class_resources key for a story-side pool name.
    "Ki" → "ki_points", "Lay on Hands" → "lay_on_hands", "Action Surge" →
    "action_surge" — the snake_case keys the engine's presets and standard
    actions expect."""
    base = display_name.strip().lower().replace(":", "").replace(" ", "_")
    return _RESOURCE_ALIASES.get(base, base)


# --- Level-scaling helpers (SRD progression tables) ------------------------

def _aura_range(level: int) -> int:
    return 30 if level >= 18 else 10


def _sneak_dice(level: int) -> str:
    return f"{(level + 1) // 2}d6"


def _martial_die(level: int) -> str:
    if level >= 17:
        return "1d10"
    if level >= 11:
        return "1d8"
    if level >= 5:
        return "1d6"
    return "1d4"


def _unarmored_movement(level: int) -> int:
    for threshold, bonus in ((18, 30), (14, 25), (10, 20), (6, 15)):
        if level >= threshold:
            return bonus
    return 10


def _rage_bonus(level: int) -> int:
    if level >= 16:
        return 4
    if level >= 9:
        return 3
    return 2


def _brutal_dice(level: int) -> int:
    return 1 + (1 if level >= 13 else 0) + (1 if level >= 17 else 0)


def _extra_attacks(char_class: str, level: int) -> int:
    if char_class == "fighter":
        if level >= 20:
            return 4
        if level >= 11:
            return 3
    return 2


# --- Engine Features (passive machinery the engine reads) ------------------

def features_for(char: Character) -> list[Feature]:
    """The engine `Feature` objects for a sheet's class features, scaled to
    the character's current level. Names the map doesn't know are simply not
    staged — they stay story-side prose, the deliberate success state."""
    sheet = char.sheet
    if sheet is None:
        return []
    level = char.level
    char_class = (sheet.char_class or "").strip().lower()
    out: list[Feature] = []

    for ref in sheet.features:
        name = ref.name.strip().lower()
        desc = ref.text or ref.name
        f: Feature | None = None

        if name == "extra attack":
            f = Feature(name=ref.name, description=desc,
                        extra_attack_count=_extra_attacks(char_class, level))
        elif name == "divine smite":
            # The engine auto-populates the smite rider for this exact name.
            f = Feature(name="Divine Smite", description=desc)
        elif name == "improved divine smite":
            f = Feature(name=ref.name, description=desc, on_hit_rider=OnHitRider(
                trigger=RiderTrigger.AUTOMATIC, damage_dice="1d8",
                damage_type="radiant", requires_melee=True, requires_weapon=True,
            ))
        elif name == "sneak attack":
            # Engine approximation: fires on every hit, once per turn (the
            # advantage / ally-adjacency gate isn't modeled).
            f = Feature(name=ref.name, description=desc, on_hit_rider=OnHitRider(
                trigger=RiderTrigger.AUTOMATIC, once_per_turn=True,
                damage_dice=_sneak_dice(level), damage_type="piercing",
                requires_weapon=True,
            ))
        elif name == "stunning strike":
            f = Feature(name=ref.name, description=desc, on_hit_rider=OnHitRider(
                trigger=RiderTrigger.POST_HIT, resource_type="ki_points",
                resource_cost=1, save_ability="constitution",
                save_dc_ability="wisdom", condition_on_fail="stunned",
                condition_duration="end_of_turn", condition_save_to_end=False,
                requires_melee=True,
            ))
        elif name == "divine strike":
            f = Feature(name=ref.name, description=desc, on_hit_rider=OnHitRider(
                trigger=RiderTrigger.AUTOMATIC, once_per_turn=True,
                damage_dice="2d8" if level >= 14 else "1d8",
                damage_type="radiant", requires_weapon=True,
            ))
        elif name == "brutal critical":
            f = Feature(name=ref.name, description=desc,
                        bonus_crit_dice=_brutal_dice(level))
        elif name == "improved critical":
            f = Feature(name=ref.name, description=desc, crit_range_reduction=1)
        elif name == "evasion":
            f = Feature(name=ref.name, description=desc, has_evasion=True)
        elif name == "uncanny dodge":
            f = Feature(name=ref.name, description=desc,
                        damage_reduction_flat_half=True)
        elif name == "deflect missiles":
            f = Feature(name=ref.name, description=desc,
                        damage_reduction_dice=f"1d10+{level}",
                        damage_reduction_bonus="dexterity",
                        damage_reduction_type="ranged_only")
        elif name == "indomitable":
            f = Feature(name=ref.name, description=desc,
                        forced_reroll_saves=True,
                        forced_reroll_resource="indomitable")
        elif name == "diamond soul":
            f = Feature(name=ref.name, description=desc,
                        grants_saving_throw_proficiencies=[
                            "strength", "dexterity", "constitution",
                            "intelligence", "wisdom", "charisma"],
                        forced_reroll_saves=True,
                        forced_reroll_resource="ki_points")
        elif name == "aura of protection":
            f = Feature(name=ref.name, description=desc,
                        aura_range=_aura_range(level),
                        aura_save_bonus_ability="charisma")
        elif name == "aura of courage":
            f = Feature(name=ref.name, description=desc,
                        aura_range=_aura_range(level),
                        aura_condition_immunity=["frightened"])
        elif name == "aura of devotion":
            f = Feature(name=ref.name, description=desc,
                        aura_range=_aura_range(level),
                        aura_condition_immunity=["charmed"])
        elif name == "fast movement":
            f = Feature(name=ref.name, description=desc, bonus_speed=10)
        elif name == "unarmored movement":
            f = Feature(name=ref.name, description=desc,
                        bonus_speed=_unarmored_movement(level))
        elif name in ("purity of body", "nature's ward"):
            f = Feature(name=ref.name, description=desc,
                        grants_damage_immunities=["poison"],
                        grants_condition_immunities=["poisoned"])
        elif name == "slippery mind":
            f = Feature(name=ref.name, description=desc,
                        grants_saving_throw_proficiencies=["wisdom"])
        elif name == "jack of all trades":
            f = Feature(name=ref.name, description=desc,
                        bonus_initiative=char.proficiency_bonus // 2)
        elif name == "relentless rage":
            f = Feature(name=ref.name, description=desc,
                        death_prevention=True,
                        death_prevention_save_ability="constitution",
                        death_prevention_save_dc=10,
                        death_prevention_dc_increment=5)

        if f is not None:
            out.append(f)
    return out


def _standard_bonus(name: str, desc: str, effect: str,
                    resource_cost: dict[str, int] | None = None) -> Action:
    """A bonus action routing to built-in standard-action logic (the
    Cunning Action shape — see Action.standard_effect)."""
    return Action(
        name=name,
        description=desc,
        action_type=ActionType.BONUS_ACTION,
        target_type=TargetType.SELF,
        range=0,
        standard_effect=effect,
        resource_cost=resource_cost or {},
        ai_priority=4,
    )


# --- Curated feature Actions (active abilities) ----------------------------

def _unarmed_strike(name: str, desc: str, carrier_long: str, level: int,
                    *, action_type: ActionType,
                    resource_cost: dict[str, int] | None = None,
                    target_count: int = 1) -> Action:
    """A monk unarmed strike: the martial-arts die + DEX damage, to-hit on the
    same solved carrier as the sheet's basic attack (so the roll lands on the
    sheet's attack bonus). Ki-Empowered Strikes (L6) makes it magical."""
    return Action(
        name=name,
        description=desc,
        action_type=action_type,
        target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name=name,
            attack_type="melee_weapon",
            ability=carrier_long,
            reach=5,
            damage=[DamageRoll(dice=_martial_die(level),
                               damage_type=DamageType.BLUDGEONING,
                               ability_modifier="dexterity")],
            magical=level >= 6,
        ),
        resource_cost=resource_cost or {},
        target_count=target_count,
        ai_priority=5,
    )


def feature_actions(
    char: Character, carrier_long: str
) -> tuple[list[Action], list[Action]]:
    """(actions, bonus_actions) for the sheet's ACTIVE class features —
    Second Wind, Rage, Flurry of Blows, Lay on Hands and friends — expressed
    entirely in existing engine primitives. Bonus actions are returned
    separately because the radial menu lists `creature.bonus_actions` as
    individual slots."""
    sheet = char.sheet
    if sheet is None:
        return [], []
    level = char.level
    names = {ref.name.strip().lower(): (ref.text or ref.name)
             for ref in sheet.features}
    actions: list[Action] = []
    bonus: list[Action] = []

    if "second wind" in names:
        bonus.append(Action(
            name="Second Wind",
            description=f"Regain 1d10+{level} hit points (bonus action, "
                        "1/short rest).",
            action_type=ActionType.BONUS_ACTION,
            target_type=TargetType.SELF,
            range=0,
            healing=f"1d10+{level}",
            resource_cost={"second_wind": 1},
            ai_priority=4,
        ))

    if "rage" in names:
        dmg = _rage_bonus(level)
        bonus.append(Action(
            name="Rage",
            description=(f"Enter a rage: resistance to bludgeoning, piercing "
                         f"and slashing damage, +{dmg} melee damage, and "
                         "advantage on Strength saves (1 minute)."),
            action_type=ActionType.BONUS_ACTION,
            target_type=TargetType.SELF,
            range=0,
            buff_effects=[
                BuffEffect(stat="damage_resistance", modifier_type="resistance",
                           value="bludgeoning"),
                BuffEffect(stat="damage_resistance", modifier_type="resistance",
                           value="piercing"),
                BuffEffect(stat="damage_resistance", modifier_type="resistance",
                           value="slashing"),
                BuffEffect(stat="damage_rolls", modifier_type="flat_bonus",
                           value=dmg, scope="melee"),
                BuffEffect(stat="saving_throws", modifier_type="advantage",
                           scope="strength"),
            ],
            buff_duration_rounds=10,
            resource_cost={"rage": 1},
            ai_priority=7,
        ))

    if "reckless attack" in names:
        # RAW this is free when you attack; the data approximation costs the
        # bonus action. The drawback is real: attackers get advantage back.
        bonus.append(Action(
            name="Reckless Attack",
            description=("Attack with abandon this round: advantage on your "
                         "melee attacks, but attacks against you also have "
                         "advantage."),
            action_type=ActionType.BONUS_ACTION,
            target_type=TargetType.SELF,
            range=0,
            buff_effects=[
                BuffEffect(stat="attack_rolls", modifier_type="advantage",
                           scope="melee"),
                BuffEffect(stat="attack_rolls", modifier_type="advantage",
                           target_grants_to_attacker=True),
            ],
            buff_duration_rounds=1,
            ai_priority=5,
        ))

    if "martial arts" in names:
        bonus.append(_unarmed_strike(
            "Martial Arts Strike",
            f"Bonus-action unarmed strike ({_martial_die(level)}+DEX).",
            carrier_long, level, action_type=ActionType.BONUS_ACTION,
        ))
        if level >= 2:
            bonus.append(_unarmed_strike(
                "Flurry of Blows",
                f"Two unarmed strikes ({_martial_die(level)}+DEX each) "
                "against a target (bonus action, 1 ki).",
                carrier_long, level, action_type=ActionType.BONUS_ACTION,
                resource_cost={"ki_points": 1}, target_count=2,
            ))
            bonus.append(Action(
                name="Patient Defense",
                description="Dodge as a bonus action (1 ki): attacks against "
                            "you have disadvantage until your next turn.",
                action_type=ActionType.BONUS_ACTION,
                target_type=TargetType.SELF,
                range=0,
                conditions_applied=["dodging"],
                condition_duration_type="rounds",
                condition_duration_rounds=1,
                resource_cost={"ki_points": 1},
                ai_priority=4,
            ))

    if "cunning action" in names:
        bonus.extend([
            _standard_bonus("Cunning Action: Dash",
                            "Dash as a bonus action.", "dash"),
            _standard_bonus("Cunning Action: Disengage",
                            "Disengage as a bonus action.", "disengage"),
            _standard_bonus("Cunning Action: Hide",
                            "Hide as a bonus action (Stealth check rolls).",
                            "hide"),
        ])

    if "martial arts" in names and level >= 2:
        bonus.extend([
            _standard_bonus("Step of the Wind: Dash",
                            "Dash as a bonus action (1 ki).", "dash",
                            {"ki_points": 1}),
            _standard_bonus("Step of the Wind: Disengage",
                            "Disengage as a bonus action (1 ki).", "disengage",
                            {"ki_points": 1}),
        ])

    if "vanish" in names:
        bonus.append(_standard_bonus(
            "Vanish", "Hide as a bonus action (Stealth check rolls).", "hide"))

    if "stillness of mind" in names:
        actions.append(Action(
            name="Stillness of Mind",
            description="End one effect on yourself causing you to be "
                        "charmed or frightened.",
            action_type=ActionType.ACTION,
            target_type=TargetType.SELF,
            range=0,
            conditions_removed=["charmed", "frightened"],
            ai_priority=3,
        ))

    if "wholeness of body" in names:
        # uses_per_rest doesn't round-trip to the story side (no source_item),
        # so this resets each fight — a known, mild approximation.
        actions.append(Action(
            name="Wholeness of Body",
            description=f"Regain {3 * level} hit points (1/long rest).",
            action_type=ActionType.ACTION,
            target_type=TargetType.SELF,
            range=0,
            healing=str(3 * level),
            uses_per_rest=1,
            rest_type="long",
            ai_priority=4,
        ))

    if "empty body" in names:
        actions.append(Action(
            name="Empty Body",
            description="Spend 4 ki to become invisible for 1 minute.",
            action_type=ActionType.ACTION,
            target_type=TargetType.SELF,
            range=0,
            conditions_applied=["invisible"],
            condition_duration_type="rounds",
            condition_duration_rounds=10,
            resource_cost={"ki_points": 4},
            ai_priority=4,
        ))

    if "lay on hands" in names:
        actions.append(Action(
            name="Lay on Hands",
            description="Touch a creature to restore 5 hit points from your "
                        "healing pool (spend 5 from the pool; repeatable "
                        "while the pool lasts).",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=5,
            healing="5",
            resource_cost={"lay_on_hands": 5},
            ai_priority=4,
        ))

    if "channel divinity: sacred weapon" in names:
        cha = max(1, char.ability_mod(Ability.CHA))
        actions.append(Action(
            name="Sacred Weapon",
            description=f"Channel Divinity: +{cha} to your attack rolls for "
                        "1 minute.",
            action_type=ActionType.ACTION,
            target_type=TargetType.SELF,
            range=0,
            buff_effects=[BuffEffect(stat="attack_rolls",
                                     modifier_type="flat_bonus", value=cha)],
            buff_duration_rounds=10,
            resource_cost={"channel_divinity": 1},
            ai_priority=5,
        ))

    if "channel divinity: preserve life" in names:
        # RAW splits 5×level among targets, capped at half max HP each; the
        # approximation heals one target for the full pool.
        actions.append(Action(
            name="Preserve Life",
            description=f"Channel Divinity: restore {5 * level} hit points "
                        "to a creature within 30 feet.",
            action_type=ActionType.ACTION,
            target_type=TargetType.ONE_CREATURE,
            range=30,
            healing=str(5 * level),
            resource_cost={"channel_divinity": 1},
            ai_priority=5,
        ))

    return actions, bonus
