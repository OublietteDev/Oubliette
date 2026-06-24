"""Action resolution for combat — attack rolls, damage, and effects."""

from dataclasses import dataclass, field
from enum import Enum, auto

from arena.models.character import Creature, CreatureSize
from arena.models.actions import Action, Attack, DamageRoll
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.util.dice import (
    roll_die, roll_with_advantage, roll_with_disadvantage, roll_expression,
)
from arena.combat.damage import (
    roll_damage,
    apply_damage,
    apply_healing,
    attack_is_magical,
    DamagePacket,
    halve_packets,
    zero_packets,
    reduce_packets_flat,
)
from arena.combat.concentration import (
    check_concentration,
    start_concentrating,
    add_concentration_link,
    add_concentration_buff_link,
)
from arena.combat.events import CombatEvent, CombatEventType
from arena.combat.conditions import apply_condition, remove_condition, has_condition
from arena.models.conditions import Condition
from arena.combat.condition_effects import (
    get_attack_advantage,
    is_auto_crit,
    get_save_advantage,
    is_auto_fail_save,
)
from arena.grid.line_of_sight import has_line_of_sight, get_cover
from arena.combat.stat_modifiers import (
    get_effective_armor_class,
    get_effective_ability_modifier,
    get_effective_saving_throw_proficiencies,
    get_weapon_attack_bonus,
    get_effective_crit_range,
    get_bonus_crit_dice,
    has_evasion as has_evasion_feature,
)
from arena.combat.buff_effects import (
    consume_buff_charge,
    get_buff_attack_modifiers,
    get_buff_damage_bonus,
    get_buff_on_hit_riders,
    get_buff_save_modifiers,
    apply_buff,
    remove_buff,
)
from arena.combat.cantrip_scaling import (
    get_caster_level,
    scale_cantrip_damage,
)
from arena.combat.creature_type_bonus import check_creature_type_bonus
from arena.models.conditions import ActiveBuff


def get_effective_target_count(action: Action, cast_level: int | None = None) -> int:
    """Get the number of targets for this action, including upcast scaling.

    Args:
        action: The action being used.
        cast_level: If upcasting, the slot level used.

    Returns:
        Total number of targets.
    """
    base = action.target_count
    if cast_level is not None and action.spell_level is not None and action.upcast_target_count > 0:
        extra_levels = max(0, cast_level - action.spell_level)
        base += extra_levels * action.upcast_target_count
    return base


def _compute_condition_save_dc(user: Creature, action: Action) -> int | None:
    """Compute the save DC for condition save-to-end from an action.

    If action.condition_save_to_end_dc is set, use it directly.
    Otherwise, compute from the caster's spell save DC (8 + prof + spellcasting mod).
    For non-PC creatures, falls back to the action's saving_throw.dc if available.

    Returns None if no DC can be determined.
    """
    if action.condition_save_to_end_dc is not None:
        return action.condition_save_to_end_dc
    # Try to compute spell save DC from caster
    spellcasting_ability = getattr(user, "spellcasting_ability", None)
    if spellcasting_ability:
        return 8 + user.proficiency_bonus + get_effective_ability_modifier(user, spellcasting_ability)
    # Fallback: use saving throw DC from the action
    if action.saving_throw and action.saving_throw.dc:
        return action.saving_throw.dc
    return None


def _scale_cantrip_damage_rolls(
    damage_rolls: list[DamageRoll], caster_level: int,
) -> list[DamageRoll]:
    """Return a copy of damage_rolls with dice scaled for cantrip level."""
    scaled = []
    for dr in damage_rolls:
        scaled_dice = scale_cantrip_damage(dr.dice, caster_level)
        scaled.append(DamageRoll(
            dice=scaled_dice,
            damage_type=dr.damage_type,
            bonus=dr.bonus,
            ability_modifier=dr.ability_modifier,
        ))
    return scaled


class AttackResult(Enum):
    """Outcome of an attack roll."""

    HIT = auto()
    MISS = auto()
    CRITICAL_HIT = auto()
    CRITICAL_MISS = auto()


@dataclass
class ActionResult:
    """Result of resolving an action."""

    events: list[CombatEvent]
    success: bool


@dataclass
class AttackHitResult:
    """Intermediate result after hit determination, before damage.

    Used to allow triggered abilities (like Divine Smite) to be
    offered to the player between the hit roll and damage roll.
    """

    hit: bool
    critical: bool
    natural_roll: int
    modifier: int
    total_roll: int
    target_ac: int
    effective_advantage: int
    events: list[CombatEvent] = field(default_factory=list)
    # Context needed to complete the attack in resolve_attack_damage()
    attacker: Creature | None = None
    attacker_id: str = ""
    target: Creature | None = None
    target_id: str = ""
    action: Action | None = None
    attack: Attack | None = None
    combatants: dict | None = None
    cast_level: int | None = None  # Actual slot level used (for upcast)


def check_resource_cost(
    creature: Creature, action: Action, cast_level: int | None = None,
) -> tuple[bool, str]:
    """Check if a creature has enough class resources to use an action.

    Args:
        creature: The creature attempting the action.
        action: The action with potential resource_cost requirements.
        cast_level: If set, substitute spell slot key for upcast level.

    Returns:
        (can_use, reason): can_use is True if affordable, reason explains why not.
    """
    if not action.resource_cost:
        return True, ""

    if cast_level is not None:
        from arena.combat.upcast import make_upcast_resource_cost
        cost_dict = make_upcast_resource_cost(action, cast_level)
    else:
        cost_dict = action.resource_cost

    class_resources = getattr(creature, "class_resources", {})
    for resource_name, cost in cost_dict.items():
        available = class_resources.get(resource_name, 0)
        if available < cost:
            return False, (
                f"{creature.name} doesn't have enough {resource_name} "
                f"({available}/{cost} needed) for {action.name}"
            )
    return True, ""


def deduct_resource_cost(
    creature: Creature, action: Action, cast_level: int | None = None,
) -> None:
    """Subtract resource costs from a creature's class_resources.

    Should only be called after check_resource_cost() returns True.

    Args:
        creature: The creature whose resources to deduct.
        action: The action with resource_cost requirements.
        cast_level: If set, substitute spell slot key for upcast level.
    """
    if not action.resource_cost:
        return

    if cast_level is not None:
        from arena.combat.upcast import make_upcast_resource_cost
        cost_dict = make_upcast_resource_cost(action, cast_level)
    else:
        cost_dict = action.resource_cost

    class_resources = getattr(creature, "class_resources", {})
    for resource_name, cost in cost_dict.items():
        if resource_name in class_resources:
            class_resources[resource_name] = max(0, class_resources[resource_name] - cost)


def get_attack_modifier(
    attacker: Creature,
    attack: Attack,
    action: Action | None = None,
) -> int:
    """Calculate total attack roll modifier.

    Returns ability modifier + proficiency bonus + weapon magic bonus.

    Args:
        attacker: The creature making the attack.
        attack: The Attack sub-object with ability and type info.
        action: The parent Action (optional). When provided, the weapon's
            magic_bonus is looked up via action.source_item and added
            to the modifier. Defaults to None for backward compatibility.
    """
    ability_mod = get_effective_ability_modifier(attacker, attack.ability)
    base = ability_mod + attacker.proficiency_bonus
    # Add magic weapon bonus if this attack comes from an equipment action
    source_item = action.source_item if action else None
    base += get_weapon_attack_bonus(attacker, source_item)
    return base


def _has_los_multi(
    origin_pos: HexCoord,
    origin_size: CreatureSize,
    target_pos: HexCoord,
    target_size: CreatureSize,
    grid: HexGrid,
    los_blocked_hexes: set[tuple[int, int]] | None = None,
) -> bool:
    """Check line of sight between two potentially multi-hex creatures.

    Returns True if ANY hex of the origin has LOS to ANY hex of the target.
    """
    from arena.grid.footprint import get_occupied_hexes, get_footprint_hex_count

    if get_footprint_hex_count(origin_size) == 1 and get_footprint_hex_count(target_size) == 1:
        return has_line_of_sight(origin_pos, target_pos, grid, los_blocked_hexes=los_blocked_hexes)

    for oh in get_occupied_hexes(origin_pos, origin_size):
        for th in get_occupied_hexes(target_pos, target_size):
            if has_line_of_sight(oh, th, grid, los_blocked_hexes=los_blocked_hexes):
                return True
    return False


def _get_cover_multi(
    attacker_pos: HexCoord,
    attacker_size: CreatureSize,
    target_pos: HexCoord,
    target_size: CreatureSize,
    grid: HexGrid,
) -> int:
    """Get the minimum cover bonus between two multi-hex creatures.

    Returns the BEST (lowest) cover across all hex-pair combinations.
    """
    from arena.grid.footprint import get_occupied_hexes, get_footprint_hex_count

    if get_footprint_hex_count(attacker_size) == 1 and get_footprint_hex_count(target_size) == 1:
        return get_cover(attacker_pos, target_pos, grid)

    min_cover = 5  # Start with max
    for ah in get_occupied_hexes(attacker_pos, attacker_size):
        for th in get_occupied_hexes(target_pos, target_size):
            cover = get_cover(ah, th, grid)
            min_cover = min(min_cover, cover)
            if min_cover == 0:
                return 0
    return min_cover


def is_in_range(
    attacker_pos: HexCoord,
    target_pos: HexCoord,
    action: Action,
    attacker_size: CreatureSize = CreatureSize.MEDIUM,
    target_size: CreatureSize = CreatureSize.MEDIUM,
) -> bool:
    """Check if target is within range of the action.

    For multi-hex creatures, uses the minimum distance between any
    hex of the attacker's footprint and any hex of the target's footprint.
    1 hex = 5 feet. For melee, uses reach. For ranged, uses range_normal.
    """
    from arena.grid.footprint import min_distance_between, get_footprint_hex_count

    if (
        get_footprint_hex_count(attacker_size) == 1
        and get_footprint_hex_count(target_size) == 1
    ):
        distance_hexes = attacker_pos.distance_to(target_pos)
    else:
        distance_hexes = min_distance_between(
            attacker_pos, attacker_size, target_pos, target_size
        )
    distance_feet = distance_hexes * 5

    if action.attack:
        if action.attack.attack_type.startswith("melee"):
            return distance_feet <= action.attack.reach
        else:
            # Ranged attack
            normal_range = action.attack.range_normal or action.range
            return distance_feet <= normal_range
    return distance_feet <= action.range


def _sanctuary_dc(creature: Creature) -> int | None:
    """The save DC of a Sanctuary-style ward on this creature, or None.

    The DC rides the buff modifier's value (the bridge bakes the caster's
    spell DC over the generator's "DC" token); non-numeric values fall
    back to 13 (a mid-tier caster) so native content still works.
    """
    for buff in creature.active_buffs:
        for mod in buff.modifiers:
            if mod.stat == "sanctuary_ward":
                return mod.value if isinstance(mod.value, int) else 13
    return None


def _decoy_buff(creature: Creature):
    """The creature's Mirror Image-style decoy buff, if any remain."""
    for buff in creature.active_buffs:
        if any(m.stat == "decoy_images" for m in buff.modifiers):
            return buff
    return None


def resolve_attack_hit(
    attacker: Creature,
    attacker_id: str,
    target: Creature,
    target_id: str,
    action: Action,
    grid: HexGrid,
    advantage: int = 0,
    combatants: dict | None = None,
    attacker_pos: HexCoord | None = None,
    target_pos: HexCoord | None = None,
    cast_level: int | None = None,
    obscured_hexes: set[tuple[int, int]] | None = None,
) -> AttackHitResult:
    """Phase 1 of attack resolution: roll to hit, determine hit/miss/crit.

    Does NOT roll damage. Returns an intermediate AttackHitResult that
    can be passed to resolve_attack_damage() to complete the attack.

    This split allows the GUI to offer triggered abilities (Divine Smite)
    between hit determination and damage rolling.
    """
    events: list[CombatEvent] = []

    # Check resource cost (ki points, spell slots — adjusted for upcast)
    can_use, reason = check_resource_cost(attacker, action, cast_level)
    if not can_use:
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=reason,
            source_id=attacker_id,
        ))
        return AttackHitResult(
            hit=False, critical=False, natural_roll=0, modifier=0,
            total_roll=0, target_ac=0, effective_advantage=0,
            events=events,
        )
    # Use tracking (mirrors resolve_effect) — attack-shaped limited actions
    # (a thrown javelin, a Scorching Ray scroll) spend a use per cast; multi-
    # dart volleys blank uses_per_rest after the first dart, so one cast =
    # one use. An exhausted action refuses outright (no 5th javelin from a
    # stack of 2).
    if action.uses_per_rest is not None:
        if action.current_uses is None:
            action.current_uses = action.uses_per_rest
        if action.current_uses <= 0:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"No uses of {action.name} remaining.",
                source_id=attacker_id,
            ))
            return AttackHitResult(
                hit=False, critical=False, natural_roll=0, modifier=0,
                total_roll=0, target_ac=0, effective_advantage=0,
                events=events,
            )
        action.current_uses -= 1
    deduct_resource_cost(attacker, action, cast_level)

    attack = action.attack
    if attack is None:
        return AttackHitResult(
            hit=False, critical=False, natural_roll=0, modifier=0,
            total_roll=0, target_ac=0, effective_advantage=0,
        )

    # Check range
    if attacker_pos is None:
        attacker_pos = grid.find_creature(attacker_id)
    if target_pos is None:
        target_pos = grid.find_creature(target_id)
    if attacker_pos is None or target_pos is None:
        return AttackHitResult(
            hit=False, critical=False, natural_roll=0, modifier=0,
            total_roll=0, target_ac=0, effective_advantage=0,
        )

    if not is_in_range(
        attacker_pos, target_pos, action, attacker.size, target.size
    ):
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{target.name} is out of range for {action.name}",
            source_id=attacker_id,
        ))
        return AttackHitResult(
            hit=False, critical=False, natural_roll=0, modifier=0,
            total_roll=0, target_ac=0, effective_advantage=0,
            events=events,
        )

    # Check line of sight
    if not _has_los_multi(attacker_pos, attacker.size, target_pos, target.size, grid):
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{target.name} is not visible (no line of sight)",
            source_id=attacker_id,
        ))
        return AttackHitResult(
            hit=False, critical=False, natural_roll=0, modifier=0,
            total_roll=0, target_ac=0, effective_advantage=0,
            events=events,
        )

    # Determine melee vs ranged
    is_melee = attack.attack_type.startswith("melee")

    # ── Sanctuary (C4 decoy tier) ────────────────────────────────────
    # Attacking breaks the attacker's OWN ward (RAW: the spell ends if
    # the warded creature attacks).
    own_wards = [b for b in attacker.active_buffs
                 if any(m.stat == "sanctuary_ward" for m in b.modifiers)]
    for ward in own_wards:
        attacker.active_buffs.remove(ward)
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"{attacker.name}'s {ward.name} ends — they attacked!",
            source_id=attacker_id,
            details={"buff_removed": ward.name},
        ))
    # A ward on the TARGET: WIS save before the attack can be made; on a
    # failure the attack is lost (approx of RAW's choose-a-new-target —
    # the engine resolves one declared attack, so the swing simply fails).
    ward_dc = _sanctuary_dc(target)
    if ward_dc is not None:
        saved, save_event = resolve_saving_throw(
            attacker, attacker_id, "wisdom", ward_dc,
        )
        save_event.message = f"Sanctuary: {save_event.message}"
        events.append(save_event)
        if not saved:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=(
                    f"{attacker.name} cannot bring themselves to strike "
                    f"{target.name} — the attack is lost!"
                ),
                source_id=attacker_id,
                target_id=target_id,
                details={"sanctuary_blocked": True},
            ))
            return AttackHitResult(
                hit=False, critical=False, natural_roll=1, modifier=0,
                total_roll=0, target_ac=get_effective_armor_class(target),
                effective_advantage=0,
                events=events,
                attacker=attacker, attacker_id=attacker_id,
                target=target, target_id=target_id,
                action=action, attack=attack, combatants=combatants,
                cast_level=cast_level,
            )

    # Auto-hit attacks (Magic Missile darts): no roll, no crit — range and
    # LOS were already checked above, so the dart simply strikes.
    if attack.auto_hit:
        events.append(CombatEvent(
            event_type=CombatEventType.ATTACK_ROLL,
            message=(
                f"{attacker.name} strikes {target.name} with {action.name} "
                f"- automatic hit!"
            ),
            source_id=attacker_id,
            target_id=target_id,
            details={
                "auto_hit": True,
                "hit": True,
                "critical": False,
                "action_name": action.name,
                "animation": action.animation,
                "attack_type": attack.attack_type,
            },
        ))
        return AttackHitResult(
            hit=True, critical=False, natural_roll=0, modifier=0,
            total_roll=0, target_ac=get_effective_armor_class(target),
            effective_advantage=0,
            events=events,
            attacker=attacker, attacker_id=attacker_id,
            target=target, target_id=target_id,
            action=action, attack=attack, combatants=combatants,
            cast_level=cast_level,
        )

    # Advantage calculation (incl. pairwise vision: fog/darkness obscurement)
    attacker_sees_target = True
    target_sees_attacker = True
    if obscured_hexes:
        from arena.grid.vision import can_see
        attacker_sees_target = can_see(
            attacker_pos, target_pos, obscured_hexes,
            truesight_ft=attacker.senses.get("truesight", 0),
            blindsight_ft=attacker.senses.get("blindsight", 0),
        )
        target_sees_attacker = can_see(
            target_pos, attacker_pos, obscured_hexes,
            truesight_ft=target.senses.get("truesight", 0),
            blindsight_ft=target.senses.get("blindsight", 0),
        )
    condition_adv = get_attack_advantage(
        attacker, target, is_melee=is_melee,
        attacker_sees_target=attacker_sees_target,
        target_sees_attacker=target_sees_attacker,
    )
    if has_condition(attacker, Condition.HELPED):
        remove_condition(attacker, attacker_id, Condition.HELPED)

    total_adv_sources = max(advantage, 0) + max(condition_adv, 0)
    total_dis_sources = abs(min(advantage, 0)) + abs(min(condition_adv, 0))
    if total_adv_sources > 0 and total_dis_sources > 0:
        effective_advantage = 0
    elif total_adv_sources > 0:
        effective_advantage = 1
    elif total_dis_sources > 0:
        effective_advantage = -1
    else:
        effective_advantage = 0

    # Roll to hit
    roll_detail = ""
    if effective_advantage > 0:
        natural_roll, r1, r2 = roll_with_advantage()
        roll_detail = f" [adv: {r1},{r2}]"
    elif effective_advantage < 0:
        natural_roll, r1, r2 = roll_with_disadvantage()
        roll_detail = f" [dis: {r1},{r2}]"
    else:
        natural_roll = roll_die(20)

    modifier = get_attack_modifier(attacker, attack, action)
    # Add buff bonuses to attack roll (Bless +1d4, etc.)
    buff_flat, buff_dice = get_buff_attack_modifiers(attacker)
    modifier += buff_flat
    buff_roll_detail = ""
    for expr in buff_dice:
        bonus, _rolls = roll_expression(expr)
        modifier += bonus
        buff_roll_detail += f" [buff: {expr}={bonus}]"
    total_roll = natural_roll + modifier

    cover_bonus = _get_cover_multi(
        attacker_pos, attacker.size, target_pos, target.size, grid
    )
    target_ac = get_effective_armor_class(target) + cover_bonus

    # ── Mirror Image (C4 decoy tier) ─────────────────────────────────
    # A d20 decides whether the swing finds a duplicate instead of the
    # caster (3 images: 6+, 2: 8+, 1: 11+). A redirected attack resolves
    # vs the duplicate's AC (10 + DEX): clearing it shatters one image
    # (the buff's trigger charges ARE the duplicates); either way the
    # real target is untouched. Approx: even a natural 20 only pops an
    # image; blindsight/truesight exemptions not modeled.
    decoy = _decoy_buff(target)
    if decoy is not None and (decoy.charges or 0) > 0:
        threshold = 6 if decoy.charges >= 3 else (8 if decoy.charges == 2 else 11)
        redirect_roll = roll_die(20)
        if redirect_roll >= threshold:
            decoy_ac = 10 + target.ability_scores.get_modifier("dexterity")
            shattered = total_roll >= decoy_ac
            events.append(CombatEvent(
                event_type=CombatEventType.ATTACK_ROLL,
                message=(
                    f"{attacker.name}'s {action.name} strikes at a duplicate "
                    f"({redirect_roll} vs {threshold}+): {total_roll} "
                    f"({natural_roll}+{modifier}) vs AC {decoy_ac} - "
                    + ("the image SHATTERS!" if shattered
                       else "even the image evades!")
                ),
                source_id=attacker_id,
                target_id=target_id,
                details={
                    "roll": total_roll, "natural": natural_roll,
                    "modifier": modifier, "target_ac": decoy_ac,
                    "hit": False, "critical": False,
                    "advantage": effective_advantage,
                    "action_name": action.name,
                    "animation": action.animation,
                    "attack_type": attack.attack_type,
                    "mirror_image_redirect": True,
                },
            ))
            if shattered:
                spent = consume_buff_charge(target, target_id, decoy)
                if spent:
                    events.append(spent)
                elif decoy.charges:
                    events.append(CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=(
                            f"{decoy.charges} duplicate"
                            f"{'s' if decoy.charges != 1 else ''} of "
                            f"{target.name} remain{'s' if decoy.charges == 1 else ''}."
                        ),
                        source_id=target_id,
                        target_id=target_id,
                    ))
            return AttackHitResult(
                hit=False, critical=False, natural_roll=natural_roll,
                modifier=modifier, total_roll=total_roll,
                target_ac=decoy_ac, effective_advantage=effective_advantage,
                events=events,
                attacker=attacker, attacker_id=attacker_id,
                target=target, target_id=target_id,
                action=action, attack=attack, combatants=combatants,
                cast_level=cast_level,
            )

    # Determine result (crit range may be expanded by features/feats)
    crit_threshold = get_effective_crit_range(attacker)
    if natural_roll >= crit_threshold:
        result = AttackResult.CRITICAL_HIT
    elif natural_roll == 1:
        result = AttackResult.CRITICAL_MISS
    elif total_roll >= target_ac:
        result = AttackResult.HIT
    else:
        result = AttackResult.MISS

    if result == AttackResult.HIT and is_auto_crit(target, is_melee=is_melee):
        result = AttackResult.CRITICAL_HIT

    hit = result in (AttackResult.HIT, AttackResult.CRITICAL_HIT)

    # Build attack roll message
    crit_text = " (CRITICAL!)" if result == AttackResult.CRITICAL_HIT else ""
    miss_text = " (Critical Miss!)" if result == AttackResult.CRITICAL_MISS else ""
    hit_miss = "HIT" if hit else "MISS"

    events.append(
        CombatEvent(
            event_type=CombatEventType.ATTACK_ROLL,
            message=(
                f"{attacker.name} attacks {target.name} with {action.name}: "
                f"{total_roll} ({natural_roll}+{modifier}) vs AC {target_ac} "
                f"- {hit_miss}{crit_text}{miss_text}{roll_detail}{buff_roll_detail}"
            ),
            source_id=attacker_id,
            target_id=target_id,
            details={
                "roll": total_roll,
                "natural": natural_roll,
                "modifier": modifier,
                "target_ac": target_ac,
                "hit": hit,
                "critical": result == AttackResult.CRITICAL_HIT,
                "advantage": effective_advantage,
                "action_name": action.name,
                "animation": action.animation,
                "attack_type": attack.attack_type,
            },
        )
    )

    return AttackHitResult(
        hit=hit,
        critical=(result == AttackResult.CRITICAL_HIT),
        natural_roll=natural_roll,
        modifier=modifier,
        total_roll=total_roll,
        target_ac=target_ac,
        effective_advantage=effective_advantage,
        events=events,
        attacker=attacker,
        attacker_id=attacker_id,
        target=target,
        target_id=target_id,
        action=action,
        attack=attack,
        combatants=combatants,
        cast_level=cast_level,
    )


def resolve_attack_damage(
    hit_result: AttackHitResult,
    bonus_damage: list[DamageRoll] | None = None,
    damage_reduction: int = 0,
) -> ActionResult:
    """Phase 2 of attack resolution: roll damage and apply.

    Args:
        hit_result: The intermediate result from resolve_attack_hit().
        bonus_damage: Optional extra damage rolls to add (e.g., Divine Smite).
            These are rolled and added to the total damage on a hit.
        damage_reduction: Flat damage reduction from reactions (Parry, Uncanny
            Dodge, Deflect Missiles).  Applied after all damage dice are totalled
            but before ``apply_damage`` (resistance/temp-HP).  A value of ``-1``
            means *halve* the total (Uncanny Dodge).

    Returns:
        ActionResult with all events (including the hit events from phase 1).
    """
    events = list(hit_result.events)

    if hit_result.hit and hit_result.attack is not None:
        is_crit = hit_result.critical
        damage_rolls = hit_result.attack.damage
        # Scale cantrip damage dice by caster level
        if hit_result.action and hit_result.action.cantrip_scaling:
            caster_level = get_caster_level(hit_result.attacker)
            damage_rolls = _scale_cantrip_damage_rolls(damage_rolls, caster_level)
        packets = roll_damage(
            damage_rolls, hit_result.attacker, is_critical=is_crit
        )

        # Flat damage-roll bonuses from active buffs (Rage +2 melee, etc.) —
        # folded into the first packet so the bonus shares the weapon's damage
        # type and magical tag; flat bonuses don't double on crits.
        buff_dmg = get_buff_damage_bonus(
            hit_result.attacker, hit_result.attack.attack_type
        )
        if buff_dmg and packets:
            packets[0].amount += buff_dmg

        # Apply bonus crit dice (Brutal Critical) — extra weapon dice on crit
        if is_crit and damage_rolls:
            extra_dice_count = get_bonus_crit_dice(hit_result.attacker)
            if extra_dice_count > 0:
                # Extract die type from the first damage roll (e.g., "1d12" → "d12")
                first_dice = damage_rolls[0].dice
                parts = first_dice.lower().split("d")
                if len(parts) == 2:
                    die_size = parts[1]
                    bonus_expr = f"{extra_dice_count}d{die_size}"
                    bc_total, bc_rolls = roll_expression(bonus_expr)
                    packets.append(DamagePacket(
                        amount=max(0, bc_total),
                        dtype=damage_rolls[0].damage_type.value,
                        source="Brutal Critical",
                        breakdown={
                            "dice": bonus_expr,
                            "rolls": bc_rolls,
                            "bonus": 0,
                            "ability_bonus": 0,
                        },
                    ))

        # Apply upcast bonus damage
        if hit_result.cast_level is not None and hit_result.action:
            from arena.combat.upcast import calculate_upcast_bonus_damage
            upcast_bonus = calculate_upcast_bonus_damage(
                hit_result.action, hit_result.cast_level,
            )
            if upcast_bonus:
                packets.extend(roll_damage(
                    upcast_bonus, hit_result.attacker, is_critical=is_crit,
                ))

        # Apply bonus damage (e.g., Divine Smite)
        if bonus_damage:
            packets.extend(roll_damage(
                bonus_damage, hit_result.attacker, is_critical=is_crit,
            ))

        # Apply creature-type bonus damage (e.g., Divine Smite +1d8 vs undead)
        if hit_result.action and hit_result.target:
            ct_bonus_dice = check_creature_type_bonus(
                hit_result.action, hit_result.target,
            )
            if ct_bonus_dice:
                ct_total, ct_rolls = roll_expression(ct_bonus_dice)
                if is_crit:
                    ct_crit, ct_crit_rolls = roll_expression(ct_bonus_dice)
                    ct_total += ct_crit
                    ct_rolls = ct_rolls + ct_crit_rolls
                ct_type = (
                    hit_result.attack.damage[0].damage_type.value
                    if hit_result.attack.damage else "untyped"
                )
                packets.append(DamagePacket(
                    amount=max(0, ct_total),
                    dtype=ct_type,
                    source="creature_type_bonus",
                    breakdown={"dice": ct_bonus_dice, "rolls": ct_rolls},
                ))
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=(
                        f"{hit_result.action.name} deals {ct_total} bonus "
                        f"damage vs {hit_result.target.creature_type.value}!"
                    ),
                    source_id=hit_result.attacker_id,
                    target_id=hit_result.target_id,
                ))

        # Spell-granted on-hit riders from active buffs (C4: Divine Favor,
        # Hunter's Mark, Branding Smite). Dice double on crit like any
        # rolled damage; packets are tagged magical (the rider IS a spell
        # effect, whatever weapon delivered it). Charged buffs (Branding
        # Smite's next-hit) are spent as they fire.
        for owner, buff, mod in get_buff_on_hit_riders(
            hit_result.attacker, hit_result.attacker_id,
            hit_result.target, hit_result.attack.attack_type,
        ):
            r_total, r_rolls = roll_expression(mod.value)
            if is_crit:
                r_crit, r_crit_rolls = roll_expression(mod.value)
                r_total += r_crit
                r_rolls = r_rolls + r_crit_rolls
            r_type = mod.damage_type or (
                hit_result.attack.damage[0].damage_type.value
                if hit_result.attack.damage else "untyped"
            )
            packets.append(DamagePacket(
                amount=max(0, r_total),
                dtype=r_type,
                source=buff.name,
                tags={"magical"},
                breakdown={"dice": mod.value, "rolls": r_rolls},
            ))
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=(
                    f"{buff.name} adds {r_total} {r_type} damage!"
                ),
                source_id=hit_result.attacker_id,
                target_id=hit_result.target_id,
            ))
            owner_id = (
                hit_result.attacker_id if owner is hit_result.attacker
                else hit_result.target_id
            )
            spent_event = consume_buff_charge(owner, owner_id, buff)
            if spent_event:
                events.append(spent_event)

        # Magic weapons / spell attacks overcome "nonmagical" defenses: tag every
        # packet of this attack so the per-packet defense check sees it.
        if attack_is_magical(hit_result.attacker, hit_result.action, hit_result.attack):
            for p in packets:
                p.tags.add("magical")

        # Apply damage reduction from reactions (Parry, Uncanny Dodge, etc.)
        # damage_reduction == -1 is the "halve" sentinel (Uncanny Dodge).
        if damage_reduction == -1:
            halve_packets(packets)
        elif damage_reduction > 0:
            reduce_packets_flat(packets, damage_reduction)

        roll_details = [p.to_detail() for p in packets]
        dmg_event, dp_events = apply_damage(
            hit_result.target, packets,
            creature_id=hit_result.target_id,
        )
        dmg_event.source_id = hit_result.attacker_id
        dmg_event.target_id = hit_result.target_id
        dmg_event.message = f"{hit_result.target.name} " + dmg_event.message
        dmg_event.details["roll_details"] = roll_details
        events.append(dmg_event)
        events.extend(dp_events)

        # Apply conditions from the attack action (e.g., poisoned on hit)
        if hit_result.action and hit_result.action.conditions_applied:
            act = hit_result.action
            # Compute condition duration/save params from the action
            cond_dur_type = act.condition_duration_type
            cond_dur_rounds = act.condition_duration_rounds
            cond_save_to_end = act.condition_save_to_end
            cond_save_dc = None
            if cond_save_to_end:
                cond_save_dc = _compute_condition_save_dc(
                    hit_result.attacker, act,
                )
            for cond_name in act.conditions_applied:
                try:
                    cond = Condition(cond_name)
                except ValueError:
                    continue
                if cond == Condition.GRAPPLED:
                    # Grapples have no re-save: they last until escaped
                    # (execute_escape_grapple, vs the stored escape DC) or
                    # the grappler goes down (_reconcile_grapples).
                    cond_event = apply_condition(
                        hit_result.target, hit_result.target_id, cond,
                        source=hit_result.attacker.name,
                        extra_data=(
                            {"escape_dc": act.grapple_escape_dc}
                            if act.grapple_escape_dc is not None else None
                        ),
                    )
                else:
                    cond_event = apply_condition(
                        hit_result.target, hit_result.target_id, cond,
                        source=hit_result.attacker.name,
                        duration_type=cond_dur_type,
                        duration_rounds=cond_dur_rounds,
                        save_to_end=cond_save_to_end,
                        save_dc=cond_save_dc,
                    )
                if cond_event:
                    events.append(cond_event)

        # Check concentration
        conc_events = check_concentration(
            hit_result.target, hit_result.target_id,
            dmg_event.details["damage"],
            combatants=hit_result.combatants,
        )
        events.extend(conc_events)

        # Check KO
        if not hit_result.target.is_conscious:
            events.append(CombatEvent(
                event_type=CombatEventType.CREATURE_DOWNED,
                message=f"{hit_result.target.name} has been knocked unconscious!",
                source_id=hit_result.attacker_id,
                target_id=hit_result.target_id,
            ))

    # ── Forced movement on hit ────────────────────────────────────
    if hit_result.hit and hit_result.action:
        action = hit_result.action
        if action.forced_movement_type and action.forced_movement_distance > 0:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message="",
                details={
                    "pending_forced_movement": True,
                    "fm_type": action.forced_movement_type,
                    "fm_distance": action.forced_movement_distance,
                    "fm_prone": action.forced_movement_prone,
                    "fm_target_id": hit_result.target_id,
                },
            ))

    return ActionResult(events=events, success=True)


def resolve_attack(
    attacker: Creature,
    attacker_id: str,
    target: Creature,
    target_id: str,
    action: Action,
    grid: HexGrid,
    advantage: int = 0,
    combatants: dict | None = None,
    attacker_pos: HexCoord | None = None,
    target_pos: HexCoord | None = None,
    cast_level: int | None = None,
    damage_reduction: int = 0,
    obscured_hexes: set[tuple[int, int]] | None = None,
) -> ActionResult:
    """Resolve a basic attack action (convenience wrapper).

    Calls resolve_attack_hit() then resolve_attack_damage() in sequence.
    Used by AI, reactions, and opportunity attacks where no user interaction
    is needed between hit and damage.
    """
    hit_result = resolve_attack_hit(
        attacker, attacker_id, target, target_id, action, grid,
        advantage=advantage, combatants=combatants,
        attacker_pos=attacker_pos, target_pos=target_pos,
        cast_level=cast_level, obscured_hexes=obscured_hexes,
    )
    # If the hit check itself failed (out of range, no LOS, no resources)
    if not hit_result.hit and not hit_result.events:
        return ActionResult(events=[], success=False)
    # If there are events but it was a failed resource check
    if hit_result.events and not hit_result.hit and hit_result.natural_roll == 0:
        return ActionResult(events=hit_result.events, success=False)
    return resolve_attack_damage(hit_result, damage_reduction=damage_reduction)


def resolve_saving_throw(
    creature: Creature,
    creature_id: str,
    ability: str,
    dc: int,
    advantage: int = 0,
    combatants: dict | None = None,
    positions: dict | None = None,
) -> tuple[bool, CombatEvent]:
    """Roll a saving throw for a creature.

    Args:
        creature: The creature making the save.
        creature_id: Unique ID for event logging.
        ability: The ability to save with (e.g., "dexterity").
        dc: The difficulty class to beat.
        advantage: > 0 = advantage, < 0 = disadvantage, 0 = normal.

    Returns:
        (success, event) tuple. success is True if the save passed.
    """
    # Check for auto-fail conditions (stunned/paralyzed auto-fail STR/DEX)
    if is_auto_fail_save(creature, ability):
        event = CombatEvent(
            event_type=CombatEventType.SAVING_THROW,
            message=(
                f"{creature.name} automatically fails the {ability.upper()} "
                f"saving throw (incapacitated)!"
            ),
            source_id=creature_id,
            details={
                "ability": ability,
                "roll": 0,
                "natural": 0,
                "modifier": 0,
                "dc": dc,
                "success": False,
                "advantage": 0,
                "auto_fail": True,
            },
        )
        return False, event

    # Use effective ability modifier (accounts for equipment + feat bonuses)
    modifier = get_effective_ability_modifier(creature, ability)
    if ability.lower() in get_effective_saving_throw_proficiencies(creature):
        modifier += creature.proficiency_bonus

    # Add buff bonuses to saving throw (Bless +1d4, etc.)
    buff_flat, buff_dice = get_buff_save_modifiers(creature, ability)
    modifier += buff_flat
    buff_roll_detail = ""
    for expr in buff_dice:
        bonus, _rolls = roll_expression(expr)
        modifier += bonus
        buff_roll_detail += f" [buff: {expr}={bonus}]"

    # Aura save bonuses (Paladin Aura of Protection, etc.)
    if combatants is not None and positions is not None:
        from arena.combat.auras import get_aura_save_bonus

        aura_bonus = get_aura_save_bonus(
            creature, creature_id, combatants, positions, ability,
        )
        if aura_bonus > 0:
            modifier += aura_bonus
            buff_roll_detail += f" [aura: +{aura_bonus}]"

    # Merge condition-based advantage with explicit parameter
    condition_adv = get_save_advantage(creature, ability)
    total_adv = max(advantage, 0) + max(condition_adv, 0)
    total_dis = abs(min(advantage, 0)) + abs(min(condition_adv, 0))
    if total_adv > 0 and total_dis > 0:
        effective_advantage = 0
    elif total_adv > 0:
        effective_advantage = 1
    elif total_dis > 0:
        effective_advantage = -1
    else:
        effective_advantage = 0

    if effective_advantage > 0:
        natural_roll, r1, r2 = roll_with_advantage()
        roll_detail = f" [adv: {r1},{r2}]"
    elif effective_advantage < 0:
        natural_roll, r1, r2 = roll_with_disadvantage()
        roll_detail = f" [dis: {r1},{r2}]"
    else:
        natural_roll = roll_die(20)
        roll_detail = ""

    total = natural_roll + modifier
    success = total >= dc

    result_text = "SUCCESS" if success else "FAILURE"

    event = CombatEvent(
        event_type=CombatEventType.SAVING_THROW,
        message=(
            f"{creature.name} makes a {ability.upper()} saving throw: "
            f"{total} ({natural_roll}+{modifier}) vs DC {dc} "
            f"- {result_text}{roll_detail}{buff_roll_detail}"
        ),
        source_id=creature_id,
        details={
            "ability": ability,
            "roll": total,
            "natural": natural_roll,
            "modifier": modifier,
            "dc": dc,
            "success": success,
            "advantage": effective_advantage,
        },
    )

    return success, event


def _resolve_dispel(
    user: Creature,
    user_id: str,
    target: Creature,
    target_id: str,
    action: Action,
    cast_level: int | None,
) -> list[CombatEvent]:
    """Dispel Magic (P-DISPEL): strip spell effects from the target.

    Buffs and conditions carrying a spell_level tag are spell effects;
    those at or below the cast slot end automatically, higher ones need
    d20 + the caster's spellcasting modifier vs DC 10 + effect level
    (RAW). Untagged effects — class features, potions, monster abilities
    — are not spells and can't be dispelled.
    """
    events: list[CombatEvent] = []
    dispel_level = (cast_level if cast_level is not None
                    else (action.spell_level or 3))
    mod = 0
    ability = getattr(user, "spellcasting_ability", None)
    if ability:
        mod = get_effective_ability_modifier(user, ability)

    def attempt(effect_level: int, label: str) -> bool:
        if effect_level <= dispel_level:
            return True
        dc = 10 + effect_level
        roll = roll_die(20)
        total = roll + mod
        success = total >= dc
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=(
                f"Dispel check vs {label} (level {effect_level}): "
                f"{total} ({roll}+{mod}) vs DC {dc} - "
                f"{'SUCCESS' if success else 'FAILURE'}"
            ),
            source_id=user_id,
            target_id=target_id,
        ))
        return success

    removed = 0
    for buff in list(target.active_buffs):
        if buff.spell_level is None:
            continue
        if attempt(buff.spell_level, buff.name):
            rm_event = remove_buff(target, target_id, buff.name)
            if rm_event:
                events.append(rm_event)
                removed += 1
    for ac in list(target.active_conditions):
        if ac.spell_level is None:
            continue
        if attempt(ac.spell_level, f"{ac.source}'s {ac.condition.value}"):
            rm_event = remove_condition(
                target, target_id, ac.condition, source=ac.source,
            )
            if rm_event:
                events.append(rm_event)
                removed += 1

    if removed == 0:
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"No spell effects on {target.name} were dispelled.",
            source_id=user_id,
            target_id=target_id,
        ))
    return events


def resolve_effect(
    user: Creature,
    user_id: str,
    target: Creature,
    target_id: str,
    action: Action,
    grid: HexGrid,
    combatants: dict | None = None,
    user_pos: HexCoord | None = None,
    target_pos: HexCoord | None = None,
    cast_level: int | None = None,
) -> ActionResult:
    """Resolve a non-attack action (healing, saving throws, conditions).

    Handles potions, scrolls, and any action that has no attack roll
    but applies healing, saving throws, conditions, or combinations.

    Args:
        user_pos: Canonical anchor position of the user. Falls back to
            grid.find_creature() if None.
        target_pos: Canonical anchor position of the target.

    Returns:
        ActionResult with all events produced.
    """
    events: list[CombatEvent] = []

    # An exhausted limited action refuses outright (mirror of the attack
    # path) — the actual decrement stays in the use-tracking block below.
    if (action.uses_per_rest is not None and action.current_uses is not None
            and action.current_uses <= 0):
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=f"No uses of {action.name} remaining.",
            source_id=user_id,
        ))
        return ActionResult(events=events, success=False)

    # Check resource cost (ki points, spell slots — adjusted for upcast)
    can_use, reason = check_resource_cost(user, action, cast_level)
    if not can_use:
        events.append(CombatEvent(
            event_type=CombatEventType.INFO,
            message=reason,
            source_id=user_id,
        ))
        return ActionResult(events=events, success=False)
    deduct_resource_cost(user, action, cast_level)

    # Range check (self-targeting always passes; AoE targets are already
    # filtered by hex distance in _resolve_effect_targets / _at_hex, so
    # skip the per-creature range check for area spells)
    is_aoe = action.target_type.value.startswith("area_")
    if user_id != target_id and not is_aoe:
        _user_pos = user_pos or grid.find_creature(user_id)
        _target_pos = target_pos or grid.find_creature(target_id)
        if _user_pos is None or _target_pos is None:
            return ActionResult(events=[], success=False)
        if not is_in_range(_user_pos, _target_pos, action, user.size, target.size):
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=f"{target.name} is out of range for {action.name}",
                source_id=user_id,
            ))
            return ActionResult(events=events, success=False)

    # Log action usage
    events.append(CombatEvent(
        event_type=CombatEventType.INFO,
        message=f"{user.name} uses {action.name} on {target.name}.",
        source_id=user_id,
        target_id=target_id,
        details={
            "action_name": action.name,
            "animation": action.animation,
            "target_type": action.target_type.value,
            "is_effect_use": True,
        },
    ))

    # --- Dispel Magic (P-DISPEL) ---
    if action.dispel:
        events.extend(_resolve_dispel(
            user, user_id, target, target_id, action, cast_level,
        ))

    # --- Healing ---
    if action.healing:
        total, _rolls = roll_expression(action.healing)

        # Upcast bonus healing
        if cast_level is not None:
            from arena.combat.upcast import calculate_upcast_bonus_healing
            bonus_expr = calculate_upcast_bonus_healing(action, cast_level)
            if bonus_expr:
                bonus_heal, _bonus_rolls = roll_expression(bonus_expr)
                total += bonus_heal

        heal_event = apply_healing(target, total)
        heal_event.source_id = user_id
        heal_event.target_id = target_id
        heal_event.message = f"{target.name} {heal_event.message}"
        events.append(heal_event)

    # --- Temporary HP ---
    if action.grants_temporary_hp:
        temp_total, _temp_rolls = roll_expression(action.grants_temporary_hp)
        old_temp = target.temporary_hit_points
        # 5e rule: temp HP doesn't stack — keep the higher value
        if temp_total > old_temp:
            target.temporary_hit_points = temp_total
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=(
                    f"{target.name} gains {temp_total} temporary hit points!"
                ),
                source_id=user_id,
                target_id=target_id,
                details={"temp_hp_granted": temp_total},
            ))
        else:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=(
                    f"{target.name} already has {old_temp} temporary HP "
                    f"(higher than {temp_total})."
                ),
                source_id=user_id,
                target_id=target_id,
            ))

    # --- HP threshold instant effects (Power Word Kill, Power Word Stun) ---
    from arena.combat.hp_threshold import (
        check_hp_threshold, check_damaged_threshold, get_threshold_alt_dice,
    )
    threshold_effect = check_hp_threshold(action, target)
    if threshold_effect == "kill":
        # Instant kill — set HP to 0
        old_hp = target.current_hit_points or 0
        target.current_hit_points = 0
        events.append(CombatEvent(
            event_type=CombatEventType.DAMAGE,
            message=f"{target.name} is slain by {action.name}!",
            source_id=user_id, target_id=target_id,
            details={"damage": old_hp, "new_hp": 0, "knocked_out": True},
        ))
        events.append(CombatEvent(
            event_type=CombatEventType.CREATURE_DOWNED,
            message=f"{target.name} has been killed!",
            source_id=user_id, target_id=target_id,
        ))
        return ActionResult(events=events, success=True)
    elif threshold_effect == "condition" and action.hp_threshold_condition:
        cond = Condition(action.hp_threshold_condition)
        cond_event = apply_condition(target, target_id, cond, source=user.name)
        if cond_event:
            events.append(cond_event)
        # Don't return — continue with rest of effect resolution
    elif action.hp_threshold is not None and action.hp_threshold_effect in ("kill", "condition"):
        current_hp = target.current_hit_points or 0
        if current_hp > action.hp_threshold:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message=(
                    f"{action.name} has no effect — {target.name}'s HP "
                    f"({current_hp}) is above {action.hp_threshold}."
                ),
                source_id=user_id, target_id=target_id,
            ))
            return ActionResult(events=events, success=True)

    # Effect-origin tag (P-DISPEL): conditions/buffs applied by a spell
    # remember the slot level they were cast at, so Dispel Magic can find
    # them. None for non-spell actions (monster abilities, features, items).
    effect_spell_level = (cast_level if cast_level is not None
                          else action.spell_level)

    # --- Saving throw ---
    save_success = None  # Track for forced movement integration
    if action.saving_throw:
        save = action.saving_throw
        dc = save.dc or 10
        save_success, save_event = resolve_saving_throw(
            target, target_id, save.ability, dc,
        )
        events.append(save_event)

        # Damage on fail (or half on success)
        if save.damage_on_fail:
            save_damage_rolls = save.damage_on_fail
            # Scale cantrip damage dice by caster level
            if action.cantrip_scaling:
                caster_level = get_caster_level(user)
                save_damage_rolls = _scale_cantrip_damage_rolls(
                    save_damage_rolls, caster_level,
                )
            # HP threshold alt dice (Toll the Dead: d8 → d12 if damaged)
            if check_damaged_threshold(action, target):
                alt_dice = get_threshold_alt_dice(action)
                if alt_dice:
                    save_damage_rolls = [
                        DamageRoll(
                            dice=alt_dice,
                            damage_type=save_damage_rolls[0].damage_type,
                            bonus=save_damage_rolls[0].bonus,
                            ability_modifier=save_damage_rolls[0].ability_modifier,
                        )
                    ]

            packets = roll_damage(
                save_damage_rolls, user, is_critical=False,
            )

            # Upcast bonus damage
            if cast_level is not None:
                from arena.combat.upcast import calculate_upcast_bonus_damage
                upcast_bonus = calculate_upcast_bonus_damage(action, cast_level)
                if upcast_bonus:
                    packets.extend(roll_damage(
                        upcast_bonus, user, is_critical=False,
                    ))

            # Creature-type bonus damage (e.g., Sunbeam +damage vs undead)
            ct_bonus_dice = check_creature_type_bonus(action, target)
            if ct_bonus_dice:
                ct_total, ct_rolls = roll_expression(ct_bonus_dice)
                ct_type = save.damage_on_fail[0].damage_type.value
                packets.append(DamagePacket(
                    amount=max(0, ct_total),
                    dtype=ct_type,
                    source="creature_type_bonus",
                    breakdown={"dice": ct_bonus_dice, "rolls": ct_rolls},
                ))
                events.append(CombatEvent(
                    event_type=CombatEventType.INFO,
                    message=(
                        f"{action.name} deals {ct_total} bonus "
                        f"damage vs {target.creature_type.value}!"
                    ),
                    source_id=user_id,
                    target_id=target_id,
                ))

            # Spell save damage (Fireball, breath weapons from spells, ...)
            # overcomes "nonmagical" defenses, same as the attack path.
            if attack_is_magical(user, action, None):
                for p in packets:
                    p.tags.add("magical")

            if save_success:
                if save.damage_on_success == "half":
                    halve_packets(packets)
                elif save.damage_on_success == "none":
                    zero_packets(packets)
                # "full" means full damage even on success

            # Evasion: DEX saves → success=0 damage, fail=half damage
            if save.ability.lower() == "dexterity" and has_evasion_feature(target):
                if save_success:
                    zero_packets(packets)
                    events.append(CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=f"{target.name}'s Evasion negates all damage!",
                        source_id=user_id,
                        target_id=target_id,
                    ))
                else:
                    halve_packets(packets)
                    events.append(CombatEvent(
                        event_type=CombatEventType.INFO,
                        message=f"{target.name}'s Evasion halves the damage!",
                        source_id=user_id,
                        target_id=target_id,
                    ))

            if sum(p.amount for p in packets) > 0:
                roll_details = [p.to_detail() for p in packets]
                dmg_event, dp_events = apply_damage(
                    target, packets,
                    creature_id=target_id,
                )
                dmg_event.source_id = user_id
                dmg_event.target_id = target_id
                dmg_event.message = f"{target.name} {dmg_event.message}"
                dmg_event.details["roll_details"] = roll_details
                events.append(dmg_event)
                events.extend(dp_events)

                # Concentration check
                conc_events = check_concentration(
                    target, target_id, dmg_event.details["damage"],
                    combatants=combatants,
                )
                events.extend(conc_events)

        # Conditions on fail / success
        # Track which conditions are actually applied (for concentration links)
        applied_conditions: list[tuple[str, str]] = []

        if not save_success and save.conditions_on_fail:
            for cond_name in save.conditions_on_fail:
                try:
                    cond = Condition(cond_name)
                except ValueError:
                    continue
                if save.conditions_no_resave:
                    # No re-save escape (RAW Banishment / Resilient Sphere):
                    # the condition only ends with concentration or an
                    # explicit removal.
                    cond_event = apply_condition(
                        target, target_id, cond,
                        source=user.name,
                        spell_level=effect_spell_level,
                    )
                else:
                    cond_event = apply_condition(
                        target, target_id, cond,
                        source=user.name,
                        duration_type="end_of_turn",
                        save_to_end=save.ability,
                        save_dc=dc,
                        spell_level=effect_spell_level,
                    )
                if cond_event:
                    events.append(cond_event)
                    applied_conditions.append((target_id, cond_name))

        if save_success and save.conditions_on_success:
            for cond_name in save.conditions_on_success:
                try:
                    cond = Condition(cond_name)
                except ValueError:
                    continue
                cond_event = apply_condition(
                    target, target_id, cond,
                    source=user.name,
                )
                if cond_event:
                    events.append(cond_event)
                    applied_conditions.append((target_id, cond_name))

    # --- Direct conditions (no save) ---
    applied_conditions_direct: list[tuple[str, str]] = []
    if action.conditions_applied and not action.saving_throw:
        # Compute condition duration/save params from the action
        cond_dur_type = action.condition_duration_type
        cond_dur_rounds = action.condition_duration_rounds
        cond_save_to_end = action.condition_save_to_end
        cond_save_dc = None
        if cond_save_to_end:
            cond_save_dc = _compute_condition_save_dc(user, action)
        for cond_name in action.conditions_applied:
            try:
                cond = Condition(cond_name)
            except ValueError:
                continue
            cond_event = apply_condition(
                target, target_id, cond,
                source=user.name,
                duration_type=cond_dur_type,
                duration_rounds=cond_dur_rounds,
                save_to_end=cond_save_to_end,
                save_dc=cond_save_dc,
                spell_level=effect_spell_level,
            )
            if cond_event:
                events.append(cond_event)
                applied_conditions_direct.append((target_id, cond_name))

    if action.conditions_removed:
        for cond_name in action.conditions_removed:
            try:
                cond = Condition(cond_name)
            except ValueError:
                continue
            rm_event = remove_condition(target, target_id, cond)
            if rm_event:
                events.append(rm_event)

    # --- Buff/Debuff effects ---
    applied_buffs: list[tuple[str, str]] = []  # (target_id, buff_name) for conc linking
    if action.buff_effects:
        should_apply_buff = True
        # Debuffs with a saving throw only apply on failed save
        if action.saving_throw and save_success:
            should_apply_buff = False
        if should_apply_buff:
            dur_type = "indefinite"
            dur_rounds = None
            if action.buff_duration_rounds is not None:
                dur_type = "rounds"
                dur_rounds = action.buff_duration_rounds
            buff = ActiveBuff(
                name=action.name,
                source_id=user_id,
                modifiers=list(action.buff_effects),
                duration_type=dur_type,
                duration_rounds=dur_rounds,
                charges=action.buff_charges,
                spell_level=effect_spell_level,
            )
            # For save-based debuffs with save-to-end (Bane, Slow)
            if action.saving_throw and not save_success:
                buff.duration_type = "end_of_turn"
                buff.save_to_end = action.saving_throw.ability
                buff.save_dc = action.saving_throw.dc or 10
            buff_event = apply_buff(target, target_id, buff)
            events.append(buff_event)
            applied_buffs.append((target_id, action.name))

    # --- Use tracking ---
    if action.uses_per_rest is not None:
        if action.current_uses is None:
            action.current_uses = action.uses_per_rest
        if action.current_uses > 0:
            action.current_uses -= 1

    # --- Concentration ---
    if action.requires_concentration:
        # Collect all conditions that were applied by this spell
        all_applied = (
            (applied_conditions if action.saving_throw else [])
            + applied_conditions_direct
        )
        # Start concentrating if the spell had any effect:
        # - Applied conditions to targets (Hold Person, etc.)
        # - Dealt damage via saving throw (Spirit Guardians, etc.)
        # - Applied healing
        # - Applied buffs/debuffs
        spell_had_effect = bool(all_applied) or bool(applied_buffs)
        if action.saving_throw and action.saving_throw.damage_on_fail:
            spell_had_effect = True
        if action.healing:
            spell_had_effect = True
        if spell_had_effect:
            # Only start concentration once (AoE spells call resolve_effect
            # per target — don't restart concentration on every target)
            already_concentrating_on_this = (
                has_condition(user, Condition.CONCENTRATING)
                and any(
                    ac.extra_data.get("spell") == action.name
                    for ac in user.active_conditions
                    if ac.condition == Condition.CONCENTRATING
                )
            )
            if not already_concentrating_on_this:
                conc_events = start_concentrating(
                    user, user_id, action.name, combatants=combatants,
                )
                events.extend(conc_events)
            # Register links so ending concentration cleans up targets
            for tid, cname in all_applied:
                add_concentration_link(user, tid, cname)
            # Register buff links so ending concentration removes buffs
            for tid, bname in applied_buffs:
                add_concentration_buff_link(user, tid, bname)

    # Check if target was knocked out
    if not target.is_conscious:
        events.append(CombatEvent(
            event_type=CombatEventType.CREATURE_DOWNED,
            message=f"{target.name} has been knocked unconscious!",
            source_id=user_id,
            target_id=target_id,
        ))

    # ── Forced movement on failed save (or no save required) ──────
    if action.forced_movement_type and action.forced_movement_distance > 0:
        should_push = (save_success is None) or (save_success is False)
        if should_push and target.is_conscious:
            events.append(CombatEvent(
                event_type=CombatEventType.INFO,
                message="",
                details={
                    "pending_forced_movement": True,
                    "fm_type": action.forced_movement_type,
                    "fm_distance": action.forced_movement_distance,
                    "fm_prone": action.forced_movement_prone,
                    "fm_target_id": target_id,
                },
            ))

    return ActionResult(events=events, success=True)
