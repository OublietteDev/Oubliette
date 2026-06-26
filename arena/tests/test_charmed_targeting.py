"""D-COND-1 — a charmed creature can't target its charmer.

RAW: "The charmed creature can't attack the charmer or target the charmer with
harmful abilities or magical effects." It may still buff/heal the charmer.
Enforced two ways: the AI drops the charmer from context.enemies (never scores
it as a target), and execute_attack / execute_effect refuse a forbidden target.
The charmer is the CHARMED condition's source (a creature name), the same
convention FRIGHTENED uses for its fear source.
"""

from pathlib import Path

from unittest.mock import patch

from arena.ai.context import build_context
from arena.combat.conditions import apply_condition
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import CombatantEntry, Encounter


def _melee_attack():
    return Action(
        name="Slash", description="A melee swing",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name="Slash", attack_type="melee_weapon", ability="strength",
            damage=[DamageRoll(dice="1d6", damage_type=DamageType.SLASHING)],
        ),
    )


def _fireball():
    return Action(
        name="Scorch", description="A harmful save effect",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=60, spell_level=1,
        saving_throw=SavingThrowEffect(
            ability="dexterity", dc=14,
            damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
    )


def _heal():
    return Action(
        name="Cure", description="A beneficial heal",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=30, spell_level=1, healing="2d8",
    )


def _creature(name, hp=40, is_player=True, actions=None):
    return Creature(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=10,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=actions or [],
    )


def _manager_with_charmed_victim():
    """Victim (player, acts first) charmed by 'Enchanter'; a Goblin bystander
    is a legal target. Victim is adjacent to both enemies."""
    victim = _creature("Victim", actions=[_melee_attack()])
    combatants = [
        CombatantEntry(creature_id="victim", creature_data=victim,
                       team="player", starting_position=(4, 4)),
        CombatantEntry(creature_id="enchanter",
                       creature_data=_creature("Enchanter", is_player=False),
                       team="enemy", starting_position=(4, 5)),
        CombatantEntry(creature_id="goblin",
                       creature_data=_creature("Goblin", is_player=False),
                       team="enemy", starting_position=(5, 4)),
    ]
    encounter = Encounter(
        name="Charm", grid_width=10, grid_height=10, combatants=combatants,
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10, 5]):
        cm.roll_initiative()
    cm.begin_combat()
    # Victim is charmed by the Enchanter.
    apply_condition(cm.combatants["victim"].creature, "victim",
                    Condition.CHARMED, source="Enchanter")
    return cm


class TestHelpers:
    def test_charm_forbids_only_the_charmer(self):
        cm = _manager_with_charmed_victim()
        victim = cm.combatants["victim"].creature
        assert cm._charm_forbids_target(victim, "enchanter") is True
        assert cm._charm_forbids_target(victim, "goblin") is False

    def test_uncharmed_creature_forbids_nothing(self):
        cm = _manager_with_charmed_victim()
        goblin = cm.combatants["goblin"].creature
        assert cm._charm_forbids_target(goblin, "enchanter") is False

    def test_action_harmful_classification(self):
        assert CombatManager._action_is_harmful(_melee_attack()) is True
        assert CombatManager._action_is_harmful(_fireball()) is True
        assert CombatManager._action_is_harmful(_heal()) is False


class TestAITargeting:
    def test_charmer_dropped_from_enemies(self):
        cm = _manager_with_charmed_victim()
        # Victim won initiative, so it is the active combatant.
        assert cm.active_combatant.creature_id == "victim"
        ctx = build_context(cm)
        enemy_names = {e.creature_id for e in ctx.enemies}
        assert "enchanter" not in enemy_names
        assert "goblin" in enemy_names

    def test_uncharmed_active_sees_all_enemies(self):
        cm = _manager_with_charmed_victim()
        # Remove the charm — now the charmer is a normal enemy again.
        cm.combatants["victim"].creature.active_conditions.clear()
        ctx = build_context(cm)
        enemy_names = {e.creature_id for e in ctx.enemies}
        assert {"enchanter", "goblin"} <= enemy_names


class TestExecutionGuards:
    def test_attack_on_charmer_refused(self):
        cm = _manager_with_charmed_victim()
        cm.selected_action = _melee_attack()
        assert cm.execute_attack("enchanter") is None

    def test_attack_on_other_enemy_proceeds(self):
        cm = _manager_with_charmed_victim()
        cm.selected_action = _melee_attack()
        result = cm.execute_attack("goblin")
        assert result is not None

    def test_hit_check_on_charmer_refused(self):
        """The GUI's single-target attack uses execute_attack_hit_check, NOT
        execute_attack — the guard must cover this path (regression: it didn't,
        so a charmed hero could still melee its charmer in real play)."""
        cm = _manager_with_charmed_victim()
        cm.selected_action = _melee_attack()
        assert cm.execute_attack_hit_check("enchanter") is None

    def test_hit_check_on_other_enemy_proceeds(self):
        cm = _manager_with_charmed_victim()
        cm.selected_action = _melee_attack()
        assert cm.execute_attack_hit_check("goblin") is not None

    def test_harmful_effect_on_charmer_refused(self):
        cm = _manager_with_charmed_victim()
        cm.selected_action = _fireball()
        assert cm.execute_effect("enchanter") is None

    def test_beneficial_effect_on_charmer_allowed(self):
        cm = _manager_with_charmed_victim()
        cm.selected_action = _heal()
        # A heal on the charmer is not forbidden — it must not be refused by
        # the charm guard (returns a result, not None).
        assert cm.execute_effect("enchanter") is not None
