"""House rules (per-world variants) — the first table-level settings that
cross the story→Arena boundary, riding the encounter file.

Covers: the Encounter model's defaults (old files play by the book), the
load-time install/reset of the process-wide active rules, side initiative,
re-roll-each-round, the flanking advantage geometry, crits on 19–20 for
everyone, and brutal (maximized) crit dice.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from arena.combat import house_rules as hr
from arena.combat.actions import _flanking_advantage, resolve_attack_hit
from arena.combat.damage import _max_expression, roll_damage
from arena.combat.manager import Combatant, CombatManager
from arena.grid.coordinates import HexCoord
from arena.grid.hexgrid import HexGrid
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType
from arena.models.character import Creature, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter, HouseRules


@pytest.fixture(autouse=True)
def _by_the_book():
    """Every test starts and ends with the rules at book defaults — the active
    rules are process-wide, so leakage between tests must be impossible."""
    hr.reset()
    yield
    hr.reset()


def _creature(name: str, player: bool = False, dex: int = 10) -> Creature:
    return Creature(name=name, max_hit_points=10, armor_class=10,
                    ability_scores=AbilityScores(dexterity=dex),
                    is_player_controlled=player)


def _encounter(rules: HouseRules) -> Encounter:
    combatants = (
        [CombatantEntry(creature_id="inline",
                        creature_data=_creature(f"Hero {i}", player=True, dex=10 + i),
                        team="player") for i in range(2)]
        + [CombatantEntry(creature_id="inline",
                          creature_data=_creature(f"Foe {i}", dex=12 + i),
                          team="enemy") for i in range(2)]
    )
    return Encounter(name="test", combatants=combatants, house_rules=rules)


def _melee_action() -> Action:
    return Action(
        name="Sword", description="melee", action_type=ActionType.ACTION,
        attack=Attack(name="Sword", attack_type="melee_weapon", ability="strength",
                      reach=5,
                      damage=[DamageRoll(dice="1d8", damage_type=DamageType.SLASHING,
                                         ability_modifier="strength")]),
    )


# --- the encounter file: defaults + install --------------------------------

def test_encounter_defaults_play_by_the_book():
    enc = Encounter(name="plain")
    assert enc.house_rules.initiative == "standard"
    assert enc.house_rules.flanking is False
    assert enc.house_rules.crit_range_19 is False
    assert enc.house_rules.brutal_crits is False
    # An old encounter file (no house_rules block) still validates
    old = Encounter.model_validate({"name": "legacy"})
    assert old.house_rules.initiative == "standard"


def test_load_encounter_installs_rules_and_a_fresh_manager_resets():
    cm = CombatManager()
    cm.load_encounter(_encounter(HouseRules(flanking=True, crit_range_19=True)),
                      Path("."))
    assert hr.active().flanking is True and hr.active().crit_range_19 is True
    CombatManager()                      # a new fight starts by the book
    assert hr.active().flanking is False and hr.active().crit_range_19 is False


# --- initiative variants -----------------------------------------------------

def test_side_initiative_groups_the_teams():
    cm = CombatManager()
    cm.load_encounter(_encounter(HouseRules(initiative="side")), Path("."))
    cm.roll_initiative()
    rolls = {e.creature_id: e.initiative_roll for e in cm.initiative.entries}
    hero_rolls = {rolls[cid] for cid, c in cm.combatants.items() if c.team == "player"}
    foe_rolls = {rolls[cid] for cid, c in cm.combatants.items() if c.team == "enemy"}
    assert len(hero_rolls) == 1 and len(foe_rolls) == 1   # one d20 per side
    assert hero_rolls != foe_rolls                        # distinct — no interleaving
    # The order is contiguous by side: once the second side starts, the first is done
    teams = [cm.combatants[e.creature_id].team for e in cm.initiative.entries]
    assert teams == sorted(teams, key=lambda t: t != teams[0])


def test_reroll_initiative_fires_on_the_round_boundary():
    cm = CombatManager()
    cm.load_encounter(_encounter(HouseRules(initiative="reroll")), Path("."))
    cm.roll_initiative()
    cm.initiative.current_index = len(cm.initiative.entries) - 1
    with patch.object(CombatManager, "_start_current_turn"):
        cm._advance_to_next_turn()                        # wraps into round 2
    assert cm.initiative.round_number == 2
    assert cm.initiative.current_index == 0               # the new top acts first
    assert any("re-rolled" in ev.message.lower() for ev in cm.log.events)


def test_standard_initiative_never_rerolls():
    cm = CombatManager()
    cm.load_encounter(_encounter(HouseRules()), Path("."))
    cm.roll_initiative()
    cm.initiative.current_index = len(cm.initiative.entries) - 1
    with patch.object(CombatManager, "_start_current_turn"):
        cm._advance_to_next_turn()
    assert not any("re-rolled" in ev.message.lower() for ev in cm.log.events)


# --- flanking ----------------------------------------------------------------

def _flank_board(ally_at: tuple[int, int]):
    grid = HexGrid(20, 20)
    attacker, target, ally = (_creature("A", player=True), _creature("T"),
                              _creature("B", player=True))
    grid.place_creature(HexCoord(4, 5), "atk")
    grid.place_creature(HexCoord(5, 5), "tgt")
    grid.place_creature(HexCoord(*ally_at), "ally")
    combatants = {
        "atk": Combatant(creature_id="atk", creature=attacker, team="player"),
        "tgt": Combatant(creature_id="tgt", creature=target, team="enemy"),
        "ally": Combatant(creature_id="ally", creature=ally, team="player"),
    }
    return grid, attacker, target, ally, combatants


def _flanks(grid, attacker, target, combatants, is_melee=True) -> bool:
    return _flanking_advantage(
        attacker, "atk", target, "tgt",
        HexCoord(4, 5), HexCoord(5, 5), combatants, grid, is_melee)


def test_flanking_needs_the_opposite_side():
    grid, attacker, target, _, combatants = _flank_board((6, 5))   # true opposite
    assert _flanks(grid, attacker, target, combatants) is True
    grid, attacker, target, _, combatants = _flank_board((5, 4))   # adjacent, same side
    assert _flanks(grid, attacker, target, combatants) is False


def test_flanking_needs_a_conscious_ally_and_a_melee_swing():
    grid, attacker, target, ally, combatants = _flank_board((6, 5))
    ally.current_hit_points = 0                                    # ally down
    assert _flanks(grid, attacker, target, combatants) is False
    grid, attacker, target, _, combatants = _flank_board((6, 5))
    assert _flanks(grid, attacker, target, combatants, is_melee=False) is False


def test_flanking_grants_advantage_only_under_the_house_rule():
    grid, _, target, _, combatants = _flank_board((6, 5))
    attacker = PlayerCharacter(name="A", character_class="Fighter",
                               max_hit_points=20,
                               ability_scores=AbilityScores(strength=16),
                               proficiency_bonus=2)
    kwargs = dict(combatants=combatants, attacker_pos=HexCoord(4, 5),
                  target_pos=HexCoord(5, 5))
    by_the_book = resolve_attack_hit(
        attacker, "atk", target, "tgt", _melee_action(), grid, **kwargs)
    assert by_the_book.effective_advantage == 0
    hr.set_active(HouseRules(flanking=True))
    flanked = resolve_attack_hit(
        attacker, "atk", target, "tgt", _melee_action(), grid, **kwargs)
    assert flanked.effective_advantage == 1


# --- crit variants -------------------------------------------------------------

@patch("arena.combat.actions.roll_die")
def test_crit_range_19_makes_everyone_crit_on_19(mock_d20):
    mock_d20.return_value = 19
    grid = HexGrid(20, 20)
    grid.place_creature(HexCoord(5, 5), "atk")
    grid.place_creature(HexCoord(5, 6), "tgt")
    attacker = PlayerCharacter(name="A", character_class="Fighter",
                               max_hit_points=20,
                               ability_scores=AbilityScores(strength=16),
                               proficiency_bonus=2)
    target = _creature("T")
    by_the_book = resolve_attack_hit(
        attacker, "atk", target, "tgt", _melee_action(), grid)
    assert by_the_book.critical is False
    hr.set_active(HouseRules(crit_range_19=True))
    house = resolve_attack_hit(
        attacker, "atk", target, "tgt", _melee_action(), grid)
    assert house.critical is True


def test_max_expression_maximizes_dice():
    assert _max_expression("2d6") == (12, [6, 6])
    assert _max_expression("1d12") == (12, [12])
    assert _max_expression("2d6+1") == (13, [6, 6])


def test_brutal_crits_maximize_the_extra_dice():
    hr.set_active(HouseRules(brutal_crits=True))
    attacker = _creature("A")
    rolls = [DamageRoll(dice="2d6", damage_type=DamageType.SLASHING)]
    (packet,) = roll_damage(rolls, attacker, is_critical=True)
    # rolled 2d6 (2..12) + maximized 2d6 (exactly 12)
    assert packet.breakdown["rolls"][-2:] == [6, 6]
    assert 2 + 12 <= packet.amount <= 12 + 12
