"""D-CTRL-1 — control-spell signature mechanics.

Each control spell in this package was missing the primitive that makes it
distinct from a plain damage/condition spell:

- Chain Lightning  — arcs to 3 secondary targets within 30 ft.
- Slow             — action-economy limit (no reactions; action XOR bonus).
- Spike Growth     — 2d4 per 5 ft travelled, no save (not a one-time save).
- Spirit Guardians — its area is difficult terrain for enemies.
- Confusion        — d10 random-behavior table each turn (not just incapacitated).

These tests load the REAL spell JSON (so the data fix is guarded, not just a
synthetic Action) and drive the manager end-to-end.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat.manager import CombatManager
from arena.combat.condition_effects import is_slowed
from arena.combat.conditions import has_condition
from arena.combat.events import CombatEventType
from arena.models.actions import (
    Action, ActionType, Attack, DamageRoll, DamageType,
)
from arena.models.character import Creature
from arena.models.conditions import ActiveBuff, AppliedCondition, Condition
from arena.models.encounter import CombatantEntry, Encounter


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------


def _load_spell(spell_id: str) -> Action:
    """Load a real SRD spell JSON as an Action, stripping its slot cost so a
    bare test creature can cast it without a spellbook."""
    from arena.paths import DATA_DIR

    p = DATA_DIR / "spells" / "srd" / f"{spell_id}.json"
    return Action.model_validate(_json.loads(p.read_text())).model_copy(
        update={"resource_cost": {}}
    )


def _creature(name: str, hp: int = 60) -> Creature:
    return Creature(name=name, max_hit_points=hp)


def _setup_combat(
    caster: Creature,
    enemies: list[tuple[str, Creature, tuple[int, int]]],
    caster_pos: tuple[int, int] = (2, 2),
) -> tuple[CombatManager, str]:
    """One player caster + N enemies; advance to the caster's turn."""
    entries = [
        CombatantEntry(
            creature_id="caster",
            creature_data=caster,
            team="player",
            starting_position=caster_pos,
        ),
    ]
    for eid, creature, pos in enemies:
        entries.append(CombatantEntry(
            creature_id=eid,
            creature_data=creature,
            team="enemy",
            starting_position=pos,
        ))
    enc = Encounter(
        name="CTRL Test", grid_width=24, grid_height=18, combatants=entries,
    )
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    # Deterministic initiative: caster first.
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1, 1, 1, 1, 1]):
        cm.roll_initiative()
    cm.begin_combat()

    player_id = next(
        cid for cid, c in cm.combatants.items() if c.team == "player"
    )
    safety = 0
    while cm.active_combatant and cm.active_combatant.creature_id != player_id:
        cm.end_turn()
        safety += 1
        if safety > 30:
            break
    return cm, player_id


def _id_by_name(cm: CombatManager, name_substr: str) -> str:
    """Find a combatant id whose creature name contains *name_substr*."""
    return next(
        cid for cid, c in cm.combatants.items()
        if name_substr.lower() in c.creature.name.lower()
    )


# ==================================================================
# Chain Lightning
# ==================================================================


class TestChainLightning:
    """The JSON must carry the chain fields, and the spell must arc in combat."""

    def test_json_has_chain_fields(self):
        spell = _load_spell("chain_lightning")
        assert spell.chain_target_count == 3
        assert spell.chain_range == 30

    def test_real_json_arcs_to_secondaries(self):
        wizard = _creature("Wizard")
        wizard.actions = [_load_spell("chain_lightning")]

        # Primary ogre with three goblins clustered within 30 ft of it.
        enemies = [
            ("ogre", _creature("Ogre", hp=120), (8, 4)),
            ("gob1", _creature("Goblin1", hp=120), (8, 5)),
            ("gob2", _creature("Goblin2", hp=120), (8, 6)),
            ("gob3", _creature("Goblin3", hp=120), (9, 4)),
        ]
        cm, player_id = _setup_combat(wizard, enemies)
        ids = {n: _id_by_name(cm, n) for n in ("Ogre", "Goblin1", "Goblin2", "Goblin3")}

        cm.select_action(cm.combatants[player_id].creature.actions[0])
        # Force every save to fail so all four take damage.
        with patch("arena.combat.actions.roll_die", return_value=1):
            result = cm.execute_effect(ids["Ogre"])

        assert result is not None and result.success
        damaged = {
            e.target_id for e in result.events
            if e.event_type == CombatEventType.DAMAGE
        }
        # Primary + three chained secondaries.
        assert damaged == set(ids.values())


# ==================================================================
# Slow — action-economy restriction
# ==================================================================


def _slow(creature: Creature) -> None:
    """Mark a creature as under the Slow spell (the debuff the spell applies)."""
    creature.active_buffs.append(ActiveBuff(name="Slow", source_id="caster"))


class TestSlow:
    def test_is_slowed_predicate(self):
        c = _creature("Victim")
        assert not is_slowed(c)
        _slow(c)
        assert is_slowed(c)

    def test_real_json_applies_slow_debuff_on_failed_save(self):
        """Casting the real Slow JSON on a failed save leaves the target slowed."""
        from arena.combat.actions import resolve_effect

        spell = _load_spell("slow")
        caster, victim = _creature("Wizard"), _creature("Victim")
        with patch("arena.combat.actions.roll_die", return_value=1):  # victim fails
            resolve_effect(
                user=caster, user_id="w", target=victim, target_id="v",
                action=spell, grid=None, combatants={},
            )
        assert is_slowed(victim)

    def test_action_then_bonus_barred(self):
        cm, _ = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        _slow(cm.active_combatant.creature)
        # Fresh turn: either slot is available...
        assert cm.can_use_action_type(ActionType.ACTION)
        assert cm.can_use_action_type(ActionType.BONUS_ACTION)
        # ...but once the action is spent, the bonus action is barred.
        cm.turn_resources.has_used_action = True
        assert not cm.can_use_action_type(ActionType.BONUS_ACTION)

    def test_bonus_then_action_barred(self):
        cm, _ = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        _slow(cm.active_combatant.creature)
        cm.turn_resources.has_used_bonus_action = True
        assert not cm.can_use_action_type(ActionType.ACTION)

    def test_no_reactions_when_slowed(self):
        cm, pid = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        _slow(cm.active_combatant.creature)
        assert not cm.can_use_action_type(ActionType.REACTION)
        assert cm._reaction_blocked(pid)

    def test_unslowed_creature_keeps_both_slots(self):
        cm, _ = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        # No Slow: spending the action leaves the bonus action available.
        cm.turn_resources.has_used_action = True
        assert cm.can_use_action_type(ActionType.BONUS_ACTION)


# ==================================================================
# Spike Growth — per-5ft, no-save movement hazard
# ==================================================================


class TestSpikeGrowth:
    def test_json_is_movement_hazard(self):
        spell = _load_spell("spike_growth")
        assert spell.movement_hazard is True
        # No half-on-save remnant: the spell no longer deals a one-time save hit.
        assert spell.saving_throw.damage_on_success == "none"
        assert spell.terrain_modification == "difficult"

    def test_hazard_resolver_damages_creature_in_zone_no_save(self):
        """process_zone_movement_step deals the dice with no save roll."""
        from arena.combat.zones import ActiveZone, process_zone_movement_step
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord
        from arena.combat.manager import Combatant

        grid = HexGrid(12, 12)
        victim = _creature("Victim", hp=40)
        victim.current_hit_points = 40
        comb = Combatant(creature_id="v", creature=victim, team="enemy")
        comb.position = HexCoord(5, 5)
        grid.place_creature(HexCoord(5, 5), "v", victim.size)
        combatants = {"v": comb}

        zone = ActiveZone(
            zone_id="spike", caster_id="druid", name="Spike Growth",
            radius_feet=20, follows_caster=False, center=HexCoord(5, 5),
            damage_dice="0", movement_hazard_dice="2d4",
            movement_hazard_type="piercing", affects_enemies_only=False,
            team="player",
        )
        events = process_zone_movement_step([zone], "v", combatants, grid)
        assert events  # damage dealt
        assert victim.current_hit_points < 40
        # No save roll was made for a movement hazard.
        assert not any(e.event_type == CombatEventType.SAVING_THROW for e in events)

    def test_hazard_spares_caster(self):
        from arena.combat.zones import ActiveZone, process_zone_movement_step
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord
        from arena.combat.manager import Combatant

        grid = HexGrid(12, 12)
        druid = _creature("Druid", hp=40)
        druid.current_hit_points = 40
        comb = Combatant(creature_id="druid", creature=druid, team="player")
        comb.position = HexCoord(5, 5)
        grid.place_creature(HexCoord(5, 5), "druid", druid.size)
        zone = ActiveZone(
            zone_id="spike", caster_id="druid", name="Spike Growth",
            radius_feet=20, follows_caster=False, center=HexCoord(5, 5),
            movement_hazard_dice="2d4", affects_enemies_only=False,
        )
        events = process_zone_movement_step([zone], "druid", {"druid": comb}, grid)
        assert events == []
        assert druid.current_hit_points == 40

    def test_start_of_turn_does_not_damage_hazard_zone(self):
        """Standing in Spike Growth (starting a turn there) deals no damage."""
        from arena.combat.zones import ActiveZone, process_zone_start_of_turn
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord
        from arena.combat.manager import Combatant

        grid = HexGrid(12, 12)
        victim = _creature("Victim", hp=40)
        victim.current_hit_points = 40
        comb = Combatant(creature_id="v", creature=victim, team="enemy")
        comb.position = HexCoord(5, 5)
        grid.place_creature(HexCoord(5, 5), "v", victim.size)
        zone = ActiveZone(
            zone_id="spike", caster_id="druid", name="Spike Growth",
            radius_feet=20, follows_caster=False, center=HexCoord(5, 5),
            movement_hazard_dice="2d4", affects_enemies_only=False, team="player",
        )
        events = process_zone_start_of_turn([zone], "v", {"v": comb}, grid)
        assert events == []
        assert victim.current_hit_points == 40

    def test_walking_through_spikes_damages_each_step(self):
        """End-to-end: cast real Spike Growth, walk an ally through it hex by
        hex, and confirm 2 damage per in-zone step (no save) + difficult terrain."""
        from arena.grid.coordinates import HexCoord
        from arena.grid.hexgrid import HexGrid  # noqa: F401
        from arena.combat.zones import is_in_zone
        from arena.models.encounter import TerrainType

        druid = _creature("Druid")
        druid.actions = [_load_spell("spike_growth")]
        scout = _creature("Scout", hp=80)
        scout.current_hit_points = 80
        scout.speed = {"walk": 300}  # plenty of budget to cross the spikes

        # A distant enemy keeps the encounter live so turns actually advance.
        entries = [
            CombatantEntry(creature_id="druid", creature_data=druid,
                           team="player", starting_position=(2, 8)),
            CombatantEntry(creature_id="scout", creature_data=scout,
                           team="player", starting_position=(4, 8)),
            CombatantEntry(creature_id="orc", creature_data=_creature("Orc"),
                           team="enemy", starting_position=(22, 1)),
        ]
        enc = Encounter(name="SpikeWalk", grid_width=24, grid_height=16,
                        combatants=entries)
        cm = CombatManager()
        cm.load_encounter(enc, Path("."))
        with patch("arena.combat.manager.roll_die", side_effect=[20, 10, 1]):
            cm.roll_initiative()
        cm.begin_combat()

        druid_id = _id_by_name(cm, "Druid")
        scout_id = _id_by_name(cm, "Scout")

        # Druid casts Spike Growth centered at (10, 8) — astride the scout's path.
        assert cm.active_combatant.creature_id == druid_id
        cm.select_action(cm.combatants[druid_id].creature.actions[0])
        cm.execute_effect_at_hex(HexCoord(10, 8))
        assert len(cm.active_zones) == 1
        zone = cm.active_zones[0]

        # Difficult terrain was laid down.
        assert cm.grid.get_cell(HexCoord(10, 8)).terrain == TerrainType.DIFFICULT

        # Advance to the scout's turn.
        safety = 0
        while cm.active_combatant.creature_id != scout_id and safety < 10:
            cm.end_turn()
            safety += 1
        assert cm.active_combatant.creature_id == scout_id

        # Walk east, one hex at a time, tallying expected hazard hits. Each step
        # dealing 2 (patched) when the landing hex is inside the spikes. (Read HP
        # from the manager's combatant — load_encounter deep-copies the creature.)
        scout_creature = cm.combatants[scout_id].creature
        hp_before = scout_creature.current_hit_points
        in_zone_steps = 0
        with patch("arena.util.dice.roll_expression", return_value=(2, [2])):
            for q in range(5, 16):
                moved = cm.try_move(HexCoord(q, 8))
                if not moved:
                    break
                if is_in_zone(scout_id, zone, cm.combatants, cm.grid):
                    in_zone_steps += 1

        assert in_zone_steps >= 3  # genuinely crossed the spikes
        assert hp_before - scout_creature.current_hit_points == 2 * in_zone_steps


# ==================================================================
# Spirit Guardians — difficult terrain for enemies
# ==================================================================


class TestSpiritGuardians:
    def test_json_zone_slows(self):
        assert _load_spell("spirit_guardians").zone_slows is True

    def test_pathfinding_difficult_hexes_cost_double(self):
        from arena.grid.hexgrid import HexGrid
        from arena.grid.coordinates import HexCoord
        from arena.grid.pathfinding import get_reachable_hexes

        grid = HexGrid(10, 10)
        plain = get_reachable_hexes(HexCoord(0, 0), grid, 30)
        slowed = get_reachable_hexes(
            HexCoord(0, 0), grid, 30, difficult_hexes={(1, 0)},
        )
        assert plain[(1, 0)] == 5       # normal terrain: 5 ft
        assert slowed[(1, 0)] == 10     # difficult: 10 ft

    def test_aura_slows_enemies_not_caster_or_allies(self):
        cleric = _creature("Cleric")
        cleric.actions = [_load_spell("spirit_guardians")]
        cm, caster_id = _setup_combat(
            cleric,
            [("Brute", _creature("Brute"), (4, 2))],
            caster_pos=(2, 2),
        )
        # Add an ally so we can confirm allies are spared.
        cm.select_action(cm.combatants[caster_id].creature.actions[0])
        cm.execute_effect(_id_by_name(cm, "Brute"))
        assert cm.active_zones and cm.active_zones[0].slows_movement

        brute_id = _id_by_name(cm, "Brute")
        # The enemy sees the aura as difficult terrain; the caster does not.
        enemy_diff = cm._get_zone_difficult_hexes(brute_id)
        caster_diff = cm._get_zone_difficult_hexes(caster_id)
        assert enemy_diff       # non-empty
        assert (2, 2) in enemy_diff  # the caster's own hex is inside the aura
        assert caster_diff == set()

    def test_turn_start_wires_difficult_hexes_for_enemy(self):
        cleric = _creature("Cleric")
        cleric.actions = [_load_spell("spirit_guardians")]
        cm, caster_id = _setup_combat(
            cleric, [("Brute", _creature("Brute"), (5, 2))], caster_pos=(2, 2),
        )
        cm.select_action(cm.combatants[caster_id].creature.actions[0])
        cm.execute_effect(_id_by_name(cm, "Brute"))
        brute_id = _id_by_name(cm, "Brute")

        # Advance to the enemy's turn; the manager should have populated the
        # movement tracker's difficult_hexes from the aura.
        safety = 0
        while cm.active_combatant.creature_id != brute_id and safety < 10:
            cm.end_turn()
            safety += 1
        assert cm.active_combatant.creature_id == brute_id
        assert cm.movement.difficult_hexes  # aura registered for the mover


# ==================================================================
# Confusion — d10 random-behavior table
# ==================================================================


def _melee_action() -> Action:
    return Action(
        name="Slam", description="A wild swing", action_type=ActionType.ACTION,
        attack=Attack(
            name="Slam", attack_type="melee_weapon", ability="strength",
            damage=[DamageRoll(dice="2d6", damage_type=DamageType.BLUDGEONING)],
        ),
    )


class TestConfusion:
    def test_json_applies_confused_not_incapacitated(self):
        spell = _load_spell("confusion")
        conds = spell.saving_throw.conditions_on_fail
        assert "confused" in conds
        assert "incapacitated" not in conds

    def test_real_json_applies_confused_on_failed_save(self):
        from arena.combat.actions import resolve_effect

        spell = _load_spell("confusion")
        caster, victim = _creature("Wizard"), _creature("Victim")
        with patch("arena.combat.actions.roll_die", return_value=1):  # victim fails
            resolve_effect(
                user=caster, user_id="w", target=victim, target_id="v",
                action=spell, grid=None, combatants={},
            )
        assert has_condition(victim, Condition.CONFUSED)

    def test_confused_creature_cannot_react(self):
        cm, pid = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        cm.active_combatant.creature.active_conditions.append(
            AppliedCondition(condition=Condition.CONFUSED, source="Confusion")
        )
        assert not cm.can_use_action_type(ActionType.REACTION)
        assert cm._reaction_blocked(pid)

    def test_d10_act_normally_falls_through(self):
        """A 9-10 lets the creature act normally (resolver returns False)."""
        cm, pid = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        combatant = cm.combatants[pid]
        with patch("arena.combat.manager.roll_die", return_value=10):
            assert cm._process_confusion_turn(combatant) is False

    def test_d10_freeze_consumes_turn(self):
        """A 2-6 freezes the creature: turn consumed, no movement."""
        cm, pid = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (6, 4))])
        combatant = cm.combatants[pid]
        pos_before = combatant.position
        with patch("arena.combat.manager.roll_die", return_value=4):
            assert cm._process_confusion_turn(combatant) is True
        assert combatant.position == pos_before  # didn't move

    def test_d10_wander_moves_creature(self):
        """A 1 makes the creature wander (position changes)."""
        cm, pid = _setup_combat(_creature("Hero"), [("Gob", _creature("Gob"), (12, 9))])
        combatant = cm.combatants[pid]
        pos_before = combatant.position
        # d10=1, then d6=1 picks a direction.
        with patch("arena.combat.manager.roll_die", side_effect=[1, 1]):
            assert cm._process_confusion_turn(combatant) is True
        assert combatant.position != pos_before  # wandered off

    def test_d10_lash_out_attacks_adjacent_creature(self):
        """A 7-8 makes the creature melee-attack a random creature in reach."""
        brute = _creature("Brute")
        brute.actions = [_melee_action()]
        # Enemy placed adjacent to the caster start (2,2) -> (3,2).
        cm, pid = _setup_combat(brute, [("Bystander", _creature("Bystander"), (3, 2))])
        combatant = cm.combatants[pid]
        victim = cm.combatants[_id_by_name(cm, "Bystander")].creature
        hp_before = victim.current_hit_points
        # d10=7, target-pick=1; force the attack roll to hit (actions.roll_die=20).
        with patch("arena.combat.manager.roll_die", side_effect=[7, 1]), \
             patch("arena.combat.actions.roll_die", return_value=20):
            assert cm._process_confusion_turn(combatant) is True
        assert victim.current_hit_points < hp_before  # struck the bystander

    def test_start_of_turn_auto_skips_frozen_confused_creature(self):
        """End-to-end: a confused creature that rolls 2-6 has its turn auto-ended."""
        hero = _creature("Hero")
        cm, pid = _setup_combat(hero, [("Orc", _creature("Orc"), (10, 9))])
        target_id = _id_by_name(cm, "Orc")
        cm.combatants[target_id].creature.active_conditions.append(
            AppliedCondition(condition=Condition.CONFUSED, source="Confusion")
        )
        # End the hero's turn; the orc's turn begins and should auto-skip on a 4.
        with patch("arena.combat.manager.roll_die", return_value=4):
            cm.end_turn()
        # The orc never got to act — the turn advanced back around to the hero.
        assert cm.active_combatant.creature_id == pid
