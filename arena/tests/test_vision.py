"""Tests for the pairwise vision layer (P-VISION-LIGHT).

Covers the pure grid.vision.can_see query and the visibility extension to
condition_effects.get_attack_advantage. Zone/spell integration is exercised
separately once wired into the manager.
"""

from arena.grid.vision import can_see
from arena.grid.coordinates import HexCoord
from arena.combat.condition_effects import get_attack_advantage
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.combat.conditions import apply_condition


def _creature(name="Test", conditions=None):
    c = Creature(
        name=name, max_hit_points=20,
        ability_scores=AbilityScores(strength=14, dexterity=14),
        proficiency_bonus=2,
    )
    for cond in (conditions or []):
        apply_condition(c, name.lower(), cond, "test")
    return c


# ── can_see: the pure spatial query ──────────────────────────────────

class TestCanSee:
    def test_clear_sight_no_obscurement(self):
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), set()) is True

    def test_none_positions_fallback_visible(self):
        # Non-positional contexts must never spuriously blind anyone.
        assert can_see(None, HexCoord(0, 5), {(0, 2)}) is True
        assert can_see(HexCoord(0, 0), None, {(0, 2)}) is True

    def test_target_in_obscured_hex_blocks(self):
        # Target standing in fog: cannot be seen.
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(0, 5)}) is False

    def test_fog_between_blocks(self):
        # An obscured hex on the line of sight blocks it.
        line_hex = HexCoord(0, 2)
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(line_hex.q, line_hex.r)}) is False

    def test_observer_standing_in_fog_is_blinded_outward(self):
        # A creature in heavy obscurement can't see *out* either.
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(0, 0)}) is False

    def test_obscurement_off_the_line_does_not_block(self):
        # Fog that is neither on the line nor at either endpoint is irrelevant.
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(9, 9)}) is True

    def test_truesight_pierces_within_range(self):
        # Target in fog 25 ft away (5 hexes), truesight 30 ft → still seen.
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(0, 5)}, truesight_ft=30) is True

    def test_truesight_out_of_range_does_not_pierce(self):
        # Target 25 ft away, truesight only 10 ft → blocked.
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(0, 5)}, truesight_ft=10) is False

    def test_blindsight_pierces_within_range(self):
        assert can_see(HexCoord(0, 0), HexCoord(0, 5), {(0, 5)}, blindsight_ft=30) is True


# ── get_attack_advantage: visibility extension ───────────────────────

class TestVisibilityAdvantage:
    def test_defaults_are_pure_condition_query(self):
        a, t = _creature(), _creature()
        assert get_attack_advantage(a, t) == 0

    def test_attacker_cannot_see_target_disadvantage(self):
        a, t = _creature(), _creature()
        assert get_attack_advantage(a, t, attacker_sees_target=False) == -1

    def test_target_cannot_see_attacker_advantage(self):
        a, t = _creature(), _creature()
        assert get_attack_advantage(a, t, target_sees_attacker=False) == 1

    def test_mutual_blindness_cancels(self):
        # Neither can see the other (both in/across fog): adv + dis → normal.
        a, t = _creature(), _creature()
        assert get_attack_advantage(
            a, t, attacker_sees_target=False, target_sees_attacker=False
        ) == 0

    def test_unseen_attacker_cancels_with_existing_disadvantage(self):
        # Attacker is prone (disadvantage) but unseen (advantage) → cancel.
        a = _creature(conditions=[Condition.PRONE])
        t = _creature()
        assert get_attack_advantage(a, t, target_sees_attacker=False) == 0

    def test_cant_see_target_stacks_into_existing_disadvantage(self):
        # Can't-see disadvantage alongside another disadvantage is still just -1.
        a = _creature(conditions=[Condition.POISONED])
        t = _creature()
        assert get_attack_advantage(a, t, attacker_sees_target=False) == -1


# ── Integration: zone obscurement → attack advantage ─────────────────

from arena.combat.zones import ActiveZone, compute_obscured_hexes
from arena.combat.actions import resolve_attack_hit
from arena.grid.hexgrid import HexGrid
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType


def _fog(center, radius_feet=10, **kw):
    return ActiveZone(
        zone_id=kw.pop("zone_id", "z"), caster_id=kw.pop("caster_id", "c"),
        name=kw.pop("name", "Zone"), radius_feet=radius_feet,
        follows_caster=False, center=center, damage_dice="0",
        **kw,
    )


class TestComputeObscuredHexes:
    def test_fog_zone_obscures_its_hexes(self):
        grid = HexGrid(20, 20)
        z = _fog(HexCoord(5, 5), obscures_vision=True, is_magical=False, spell_level=1)
        obscured = compute_obscured_hexes([z], {}, grid)
        assert (5, 5) in obscured

    def test_daylight_dispels_lower_or_equal_level_darkness(self):
        grid = HexGrid(20, 20)
        dark = _fog(HexCoord(5, 5), zone_id="d", obscures_vision=True,
                    is_magical=True, spell_level=2)
        day = _fog(HexCoord(5, 5), zone_id="day", provides_bright_light=True,
                   spell_level=3)
        obscured = compute_obscured_hexes([dark, day], {}, grid)
        assert (5, 5) not in obscured  # daylight L3 >= darkness L2 → dispelled

    def test_daylight_does_not_dispel_higher_level_darkness(self):
        grid = HexGrid(20, 20)
        dark = _fog(HexCoord(5, 5), zone_id="d", obscures_vision=True,
                    is_magical=True, spell_level=4)
        day = _fog(HexCoord(5, 5), zone_id="day", provides_bright_light=True,
                   spell_level=3)
        obscured = compute_obscured_hexes([dark, day], {}, grid)
        assert (5, 5) in obscured  # daylight L3 < darkness L4 → stands

    def test_daylight_does_not_dispel_natural_fog(self):
        grid = HexGrid(20, 20)
        fog = _fog(HexCoord(5, 5), zone_id="f", obscures_vision=True,
                   is_magical=False, spell_level=1)
        day = _fog(HexCoord(5, 5), zone_id="day", provides_bright_light=True,
                   spell_level=9)
        obscured = compute_obscured_hexes([fog, day], {}, grid)
        assert (5, 5) in obscured  # fog is physical; light doesn't clear it


def _attacker_target_grid():
    grid = HexGrid(20, 20)
    grid.place_creature(HexCoord(5, 5), "atk")
    grid.place_creature(HexCoord(5, 6), "tgt")
    return grid


def _melee():
    return Action(
        name="Sword", description="x", action_type=ActionType.ACTION,
        attack=Attack(name="Sword", attack_type="melee_weapon", ability="strength",
                      reach=5,
                      damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                                         ability_modifier="strength")]),
    )


class TestAttackThroughObscurement:
    def test_mutual_obscurement_cancels_to_normal(self):
        # Target in fog, neither side has special senses: attacker can't see
        # target (disadvantage) AND target (in fog) can't see attacker
        # (advantage) → cancel → normal roll. Correct 5e.
        grid = _attacker_target_grid()
        atk, tgt = _creature("Atk"), _creature("Tgt")
        res = resolve_attack_hit(
            atk, "atk", tgt, "tgt", _melee(), grid,
            combatants={}, attacker_pos=HexCoord(5, 5), target_pos=HexCoord(5, 6),
            obscured_hexes={(5, 6)},
        )
        assert res.effective_advantage == 0

    def test_one_sided_blindness_is_disadvantage(self):
        # Target has truesight (sees attacker), attacker does not and the target
        # sits in fog: attacker can't see target (disadvantage), target CAN see
        # attacker (no offsetting advantage) → net disadvantage.
        grid = _attacker_target_grid()
        atk, tgt = _creature("Atk"), _creature("Tgt")
        tgt.senses = {"truesight": 60}
        res = resolve_attack_hit(
            atk, "atk", tgt, "tgt", _melee(), grid,
            combatants={}, attacker_pos=HexCoord(5, 5), target_pos=HexCoord(5, 6),
            obscured_hexes={(5, 6)},
        )
        assert res.effective_advantage == -1

    def test_clear_sight_no_penalty(self):
        grid = _attacker_target_grid()
        atk, tgt = _creature("Atk"), _creature("Tgt")
        res = resolve_attack_hit(
            atk, "atk", tgt, "tgt", _melee(), grid,
            combatants={}, attacker_pos=HexCoord(5, 5), target_pos=HexCoord(5, 6),
            obscured_hexes=set(),
        )
        assert res.effective_advantage == 0

    def test_truesight_attacker_vs_fogbound_target_gets_advantage(self):
        # Attacker has truesight (sees target); target in fog can't see attacker
        # → attacker strikes an unseeing foe with advantage.
        grid = _attacker_target_grid()
        atk, tgt = _creature("Atk"), _creature("Tgt")
        atk.senses = {"truesight": 60}
        res = resolve_attack_hit(
            atk, "atk", tgt, "tgt", _melee(), grid,
            combatants={}, attacker_pos=HexCoord(5, 5), target_pos=HexCoord(5, 6),
            obscured_hexes={(5, 6)},
        )
        assert res.effective_advantage == 1


# ── End-to-end: casting fog cloud creates & persists an obscuring zone ─

import json as _json
from pathlib import Path as _Path
from unittest.mock import patch as _patch
from arena.combat.manager import CombatManager
from arena.models.encounter import Encounter, CombatantEntry


def _load_spell(spell_id):
    from arena.paths import DATA_DIR
    p = DATA_DIR / "spells" / "srd" / f"{spell_id}.json"
    return Action.model_validate(_json.loads(p.read_text()))


class TestFogCloudCastEndToEnd:
    """Guards the full cast path: bridge-shaped spell JSON → manager → zone.

    (The field must reach the manager. In live play a stale Oubliette server
    can strip the obscuring_zone field during staging — this test pins the
    in-process behavior so the engine half never regresses.)
    """

    def _combat_with(self, action):
        caster = _creature("Caster")
        caster.actions = [action]
        enemy = _creature("Brute")
        enemy.is_player_controlled = False
        enc = Encounter(name="FogE2E", grid_width=10, grid_height=10, combatants=[
            CombatantEntry(creature_id="caster", creature_data=caster,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="brute", creature_data=enemy,
                           team="enemy", starting_position=(4, 6)),
        ])
        cm = CombatManager()
        cm.load_encounter(enc, _Path("."))
        with _patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
            cm.roll_initiative()
        cm.begin_combat()
        return cm

    def test_fog_cloud_creates_persistent_obscuring_zone(self):
        fog = _load_spell("fog_cloud").model_copy(update={"resource_cost": {}})
        assert fog.obscuring_zone == "fog"  # field survives the model
        cm = self._combat_with(fog)
        cm.selected_action = fog
        res = cm.execute_effect("brute")
        assert res.success
        zones = [z for z in cm.active_zones if z.obscures_vision]
        assert len(zones) == 1
        assert zones[0].concentration_linked is True
        # persists across a full round (concentration held)
        cm.end_turn(); cm.end_turn()
        assert any(z.obscures_vision for z in cm.active_zones)
        # and actually obscures the target's hex
        obs = compute_obscured_hexes(cm.active_zones, cm.combatants, cm.grid)
        assert (4, 6) in obs

    def test_darkness_zone_is_magical(self):
        dark = _load_spell("darkness").model_copy(update={"resource_cost": {}})
        cm = self._combat_with(dark)
        cm.selected_action = dark
        cm.execute_effect("brute")
        zones = [z for z in cm.active_zones if z.obscures_vision]
        assert len(zones) == 1 and zones[0].is_magical is True

    def test_fog_cloud_via_hex_cast_sets_zone_and_concentration(self):
        # The GUI routes AoE casts through execute_effect_at_hex, NOT
        # execute_effect — this guards that path (the bug OublietteDev hit: no zone,
        # no concentration when casting fog on a hex/area).
        from arena.combat.conditions import has_condition
        from arena.models.conditions import Condition
        fog = _load_spell("fog_cloud").model_copy(update={"resource_cost": {}})
        cm = self._combat_with(fog)
        caster = cm.combatants["caster"].creature
        cm.selected_action = fog
        res = cm.execute_effect_at_hex(HexCoord(4, 6), clicked_target_id=None)
        assert res.success
        zones = [z for z in cm.active_zones if z.obscures_vision]
        assert len(zones) == 1
        assert zones[0].center == HexCoord(4, 6)   # centered on the chosen hex
        assert has_condition(caster, Condition.CONCENTRATING)


class TestRollTypeLabel:
    """The combat log line carries an explicit roll-type word (OublietteDev's ask)."""

    def _line(self, res):
        from arena.combat.events import CombatEventType
        for e in res.events:
            if e.event_type == CombatEventType.ATTACK_ROLL:
                return e.message
        return ""

    def test_normal_attack_says_normal(self):
        from unittest.mock import patch
        grid = _attacker_target_grid()
        a, t = _creature("A"), _creature("B")
        with patch("arena.combat.actions.roll_die", return_value=11):
            res = resolve_attack_hit(a, "atk", t, "tgt", _melee(), grid,
                                     combatants={}, attacker_pos=HexCoord(5, 5),
                                     target_pos=HexCoord(5, 6))
        assert "[normal]" in self._line(res)

    def test_disadvantage_attack_says_disadvantage(self):
        from unittest.mock import patch
        grid = _attacker_target_grid()
        a, t = _creature("A"), _creature("B")
        t.senses = {"truesight": 60}  # one-sided: attacker blind, target sees
        with patch("arena.combat.actions.roll_with_disadvantage", return_value=(7, 7, 15)):
            res = resolve_attack_hit(a, "atk", t, "tgt", _melee(), grid,
                                     combatants={}, attacker_pos=HexCoord(5, 5),
                                     target_pos=HexCoord(5, 6), obscured_hexes={(5, 6)})
        assert "[disadvantage:" in self._line(res)


# ── Detection trio: See Invisibility / True Seeing / Mislead ─────────

from arena.combat.buff_effects import can_see_invisible, get_buff_truesight_ft
from arena.combat.conditions import has_condition, apply_condition
from arena.models.conditions import Condition, ActiveBuff, BuffEffect


def _self_cast(spell_id):
    """Build a 1v1 combat, cast a self-target spell, return the caster creature."""
    from arena.combat.manager import CombatManager
    from arena.models.encounter import Encounter, CombatantEntry
    from unittest.mock import patch
    from pathlib import Path as _P
    fog_caster = _creature("Caster")
    fog_caster.is_player_controlled = True
    fog_caster.actions = [_load_spell(spell_id).model_copy(update={"resource_cost": {}})]
    enemy = _creature("Baboon"); enemy.is_player_controlled = False
    enc = Encounter(name="t", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="caster", creature_data=fog_caster, team="player", starting_position=(4, 4)),
        CombatantEntry(creature_id="baboon", creature_data=enemy, team="enemy", starting_position=(4, 6)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, _P("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    cm.selected_action = cm.combatants["caster"].creature.actions[0]
    cm.execute_effect("caster")
    return cm.combatants["caster"].creature


class TestSeeInvisibleGating:
    def test_see_invisible_negates_target_invisible_disadvantage(self):
        a, t = _creature("A"), _creature("T", conditions=[Condition.INVISIBLE])
        assert get_attack_advantage(a, t) == -1
        assert get_attack_advantage(a, t, attacker_can_see_invisible=True) == 0

    def test_see_invisible_negates_attacker_invisible_advantage(self):
        a = _creature("A", conditions=[Condition.INVISIBLE])
        t = _creature("T")
        assert get_attack_advantage(a, t) == 1
        assert get_attack_advantage(a, t, target_can_see_invisible=True) == 0


class TestDetectionSpells:
    def test_see_invisibility_grants_flag(self):
        caster = _self_cast("see_invisibility")
        assert can_see_invisible(caster) is True

    def test_true_seeing_grants_truesight_and_see_invisible(self):
        caster = _self_cast("true_seeing")
        assert can_see_invisible(caster) is True
        assert get_buff_truesight_ft(caster) == 120

    def test_mislead_invisible_decoy_concentration(self):
        caster = _self_cast("mislead")
        assert has_condition(caster, Condition.INVISIBLE)
        assert has_condition(caster, Condition.CONCENTRATING)
        decoy = [b for b in caster.active_buffs
                 if any(m.stat == "decoy_images" for m in b.modifiers)]
        assert decoy and decoy[0].charges == 1

    def test_attacking_invisible_target_with_see_invisibility_is_normal(self):
        # Full path: attacker carries a see-invisible buff; target is invisible.
        a = _creature("A")
        a.active_buffs.append(ActiveBuff(
            name="See Invisibility", source_id="a",
            modifiers=[BuffEffect(stat="see_invisible", modifier_type="set", value=1)],
        ))
        t = _creature("T", conditions=[Condition.INVISIBLE])
        grid = _attacker_target_grid()
        res = resolve_attack_hit(a, "atk", t, "tgt", _melee(), grid, combatants={},
                                 attacker_pos=HexCoord(5, 5), target_pos=HexCoord(5, 6))
        assert res.effective_advantage == 0  # disadvantage negated by seeing invisible
