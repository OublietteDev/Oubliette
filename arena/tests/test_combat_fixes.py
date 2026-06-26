"""C6 playtest-straggler fixes.

- A HIDDEN attacker gets advantage, and attacking reveals it (clears HIDDEN).
- A "Stabilize" action lets an ally make a DC 10 Medicine check on an adjacent
  dying creature (the only non-healing way to stop death saves).
"""
import json
from pathlib import Path
from unittest.mock import patch

from arena.combat.manager import CombatManager, Combatant
from arena.combat.condition_effects import get_attack_advantage
from arena.combat.conditions import apply_condition, has_condition
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, PlayerCharacter, CreatureType
from arena.models.actions import Action, ActionType, TargetType, SavingThrowEffect
from arena.models.conditions import Condition
from arena.models.encounter import Encounter, CombatantEntry

_GOBLIN = json.loads((Path("arena/data/monsters/goblin.json")).read_text(encoding="utf-8"))


# ── HIDDEN → advantage, revealed on attack ───────────────────────────────────

class TestHiddenAdvantage:
    def test_hidden_attacker_has_advantage(self):
        atk = Creature(name="Sneak", max_hit_points=20)
        apply_condition(atk, "sneak", Condition.HIDDEN, source="hide",
                        duration_type="indefinite")
        tgt = Creature(name="Mark", max_hit_points=20)
        assert get_attack_advantage(atk, tgt, is_melee=True) == 1

    def test_not_hidden_is_straight(self):
        atk = Creature(name="Open", max_hit_points=20)
        tgt = Creature(name="Mark", max_hit_points=20)
        assert get_attack_advantage(atk, tgt, is_melee=True) == 0

    def test_attacking_a_hidden_target_has_disadvantage(self):
        atk = Creature(name="Seeker", max_hit_points=20)
        tgt = Creature(name="Lurker", max_hit_points=20)
        apply_condition(tgt, "lurker", Condition.HIDDEN, source="hide",
                        duration_type="indefinite")
        assert get_attack_advantage(atk, tgt, is_melee=True) == -1


def _attack_combat():
    """A hidden attacker (with a real goblin scimitar) adjacent to a target."""
    atk = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    atk.name = "Sneak"; atk.is_player_controlled = True
    apply_condition(atk, "sneak", Condition.HIDDEN, source="hide",
                    duration_type="indefinite")
    tgt = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    tgt.name = "Mark"; tgt.is_player_controlled = False
    tgt.max_hit_points = 60; tgt.current_hit_points = 60
    enc = Encounter(name="t", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="lab/sneak", creature_data=atk, team="player",
                       starting_position=(4, 4)),
        CombatantEntry(creature_id="lab/mark", creature_data=tgt, team="enemy",
                       starting_position=(4, 5)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    return cm


class TestHiddenRevealedOnAttack:
    def test_attacking_clears_hidden(self):
        cm = _attack_combat()
        sneak = cm.combatants["sneak"]
        assert has_condition(sneak.creature, Condition.HIDDEN)
        # Select the goblin's melee attack and strike the adjacent target.
        atk_action = next(a for a in sneak.creature.actions if a.attack)
        cm.selected_action = atk_action
        with patch("arena.combat.actions.roll_die", return_value=10):
            cm.execute_attack("mark")
        # The attack reveals the attacker.
        assert not has_condition(sneak.creature, Condition.HIDDEN)


# ── Stabilize a dying ally ───────────────────────────────────────────────────

def _stabilize_combat(distance: int = 1):
    """A conscious medic on the player team, a dying PC ally `distance` hexes
    away, and an enemy to keep the fight live."""
    medic = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    medic.name = "Medic"; medic.is_player_controlled = True
    medic.ability_scores = AbilityScores(wisdom=16)
    enemy = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    enemy.name = "Foe"; enemy.is_player_controlled = False
    enc = Encounter(name="t", grid_width=12, grid_height=12, combatants=[
        CombatantEntry(creature_id="lab/medic", creature_data=medic, team="player",
                       starting_position=(4, 4)),
        CombatantEntry(creature_id="lab/foe", creature_data=enemy, team="enemy",
                       starting_position=(9, 9)),
    ])
    cm = CombatManager()
    cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    # Inject a dying PC ally (a real PlayerCharacter, so it runs death saves).
    faller = PlayerCharacter(name="Faller", character_class="fighter", max_hit_points=20,
                             current_hit_points=0, is_player_controlled=True)
    faller.death_save_failures = 2
    pos = HexCoord(4, 4 + distance)
    cm.combatants["faller"] = Combatant(creature_id="faller", creature=faller,
                                        team="player", position=pos)
    cm.grid.place_creature(pos, "faller", faller.size)
    assert cm.active_combatant.creature_id == "medic"
    return cm


class TestStabilize:
    def test_success_stabilizes_adjacent_dying_ally(self):
        cm = _stabilize_combat(distance=1)
        with patch("arena.combat.standard_actions.roll_die", return_value=20):
            ev = cm.execute_standard_action("stabilize", "faller")
        faller = cm.combatants["faller"].creature
        assert ev is not None and faller.is_stabilized is True
        assert faller.death_save_failures == 0          # death saves cleared
        assert cm.turn_resources.has_used_action is True  # costs the action

    def test_failed_check_does_not_stabilize(self):
        cm = _stabilize_combat(distance=1)
        with patch("arena.combat.standard_actions.roll_die", return_value=1):
            cm.execute_standard_action("stabilize", "faller")
        assert cm.combatants["faller"].creature.is_stabilized is False

    def test_too_far_is_refused(self):
        cm = _stabilize_combat(distance=4)   # 20 ft away
        with patch("arena.combat.standard_actions.roll_die", return_value=20):
            ev = cm.execute_standard_action("stabilize", "faller")
        assert ev is not None and "too far" in ev.message.lower()
        assert cm.combatants["faller"].creature.is_stabilized is False


# ── switching concentration tears down the old zone (Web → Hold Person) ───────

def _zone_action():
    """A Web-like concentration zone: restrains on a failed DEX save."""
    return Action(
        name="Webbing", description="sticky webs", action_type=ActionType.ACTION, range=60,
        target_type=TargetType.AREA_CUBE, area_size=20,
        requires_concentration=True,
        saving_throw=SavingThrowEffect(ability="dexterity", dc=13,
                                       conditions_on_fail=["restrained"]),
    )


def test_switching_concentration_clears_old_zone_and_its_condition():
    from arena.combat.concentration import start_concentrating
    caster = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    caster.name = "Caster"
    victim = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    victim.name = "Victim"; victim.is_player_controlled = False
    enc = Encounter(name="t", grid_width=10, grid_height=10, combatants=[
        CombatantEntry(creature_id="lab/caster", creature_data=caster, team="player",
                       starting_position=(2, 2)),
        CombatantEntry(creature_id="lab/victim", creature_data=victim, team="enemy",
                       starting_position=(5, 5)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 1]):
        cm.roll_initiative()
    cm.begin_combat()

    zone = _zone_action()
    cm._cast_level = None
    cm._execute_zone_spell(zone, cm.combatants["caster"],
                           target_hex=cm.combatants["victim"].position)
    # The zone restrains the victim (zone applies with source == zone name).
    apply_condition(cm.combatants["victim"].creature, "victim", Condition.RESTRAINED,
                    source="Webbing", duration_type="indefinite")
    assert any(z.name == "Webbing" for z in cm.active_zones)

    # The caster moves their concentration to a different spell.
    start_concentrating(cm.combatants["caster"].creature, "caster", "Hold Person",
                        combatants=cm.combatants)
    cm._cleanup_orphaned_zones()

    assert not any(z.name == "Webbing" for z in cm.active_zones)       # zone gone
    assert not has_condition(cm.combatants["victim"].creature,         # restrained gone
                             Condition.RESTRAINED)


# ── frightened creatures flee their fear source ──────────────────────────────

def test_frightened_creature_plans_a_move_away_from_its_fear_source():
    from arena.ai.controller import AIController
    from arena.grid.coordinates import HexCoord
    hero = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    hero.name = "Hero"; hero.is_player_controlled = True
    coward = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    coward.name = "Coward"; coward.is_player_controlled = False
    enc = Encounter(name="t", grid_width=16, grid_height=12, combatants=[
        CombatantEntry(creature_id="lab/hero", creature_data=hero, team="player",
                       starting_position=(3, 6)),
        CombatantEntry(creature_id="lab/coward", creature_data=coward, team="enemy",
                       starting_position=(5, 6)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[1, 20]):  # coward goes first
        cm.roll_initiative()
    cm.begin_combat()
    apply_condition(cm.combatants["coward"].creature, "coward", Condition.FRIGHTENED,
                    source="Hero", duration_type="indefinite")
    assert cm.active_combatant.creature_id == "coward"

    hero_pos = cm.combatants["hero"].position
    before = cm.combatants["coward"].position.distance_to(hero_pos)
    plan = AIController().plan_turn(cm)
    moves = [s for s in plan.steps if s.step_type.name == "MOVE"]
    assert moves, "frightened creature should plan a flee move"
    dest = HexCoord(*moves[0].target_hex)
    assert dest.distance_to(hero_pos) > before   # moved away from the fear source


# ── opportunity-attack player prompt ─────────────────────────────────────────

def _oa_combat(reactor_is_player: bool):
    """An active enemy 'Runner' adjacent to a 'Guard' that threatens it; the
    Guard is player-controlled (prompt) or AI (auto-fire) per the flag."""
    guard = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    guard.name = "Guard"; guard.is_player_controlled = reactor_is_player
    runner = Creature.model_validate(_GOBLIN).model_copy(deep=True)
    runner.name = "Runner"; runner.is_player_controlled = False
    runner.max_hit_points = 40; runner.current_hit_points = 40
    enc = Encounter(name="t", grid_width=14, grid_height=10, combatants=[
        CombatantEntry(creature_id="lab/guard", creature_data=guard,
                       team=("player" if reactor_is_player else "ally"),
                       starting_position=(4, 4)),
        CombatantEntry(creature_id="lab/runner", creature_data=runner, team="enemy",
                       starting_position=(5, 4)),
    ])
    cm = CombatManager(); cm.load_encounter(enc, Path("."))
    cm._oa_prompts_enabled = True   # the GUI enables this in interactive play
    with patch("arena.combat.manager.roll_die", side_effect=[1, 20]):  # runner first
        cm.roll_initiative()
    cm.begin_combat()
    assert cm.active_combatant.creature_id == "runner"
    return cm


class TestOpportunityAttackPrompt:
    def test_player_reactor_defers_then_attacks(self):
        cm = _oa_combat(reactor_is_player=True)
        moved = cm.try_move(HexCoord(7, 4))         # Runner flees, provoking Guard
        assert moved is False and cm._pending_oa is not None
        assert cm.combatants["runner"].position == HexCoord(5, 4)   # not moved yet
        with patch("arena.combat.actions.roll_die", return_value=15):
            cm.resolve_opportunity_attack_choice(True)
        assert cm._pending_oa is None
        assert cm.combatants["runner"].position == HexCoord(7, 4)   # move completed
        assert cm.reaction_used.get("guard") is True               # reaction spent

    def test_player_reactor_skip_still_completes_move(self):
        cm = _oa_combat(reactor_is_player=True)
        cm.try_move(HexCoord(7, 4))
        cm.resolve_opportunity_attack_choice(False)                 # decline
        assert cm._pending_oa is None
        assert cm.combatants["runner"].position == HexCoord(7, 4)   # still moves
        assert cm.reaction_used.get("guard") in (False, None)       # reaction kept

    def test_ai_reactor_auto_fires_without_prompt(self):
        cm = _oa_combat(reactor_is_player=False)
        with patch("arena.combat.actions.roll_die", return_value=15):
            moved = cm.try_move(HexCoord(7, 4))
        assert cm._pending_oa is None          # no prompt for an AI reactor
        assert moved is True
        assert cm.reaction_used.get("guard") is True
