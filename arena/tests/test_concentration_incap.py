"""D-COND-3 — incapacitation (and dropping to 0 HP) ends concentration.

RAW: a creature loses concentration the moment it becomes incapacitated —
whether by the STUNNED/PARALYZED/PETRIFIED/UNCONSCIOUS/INCAPACITATED
conditions or by dropping to 0 HP. The manager enforces this with a
_reconcile_concentration sweep (mirroring _reconcile_grapples), which runs
with full combatant context so the broken spell's linked conditions are also
stripped off their targets. BANISHED is deliberately NOT a trigger.
"""

from pathlib import Path

from arena.combat.concentration import (
    add_concentration_link,
    start_concentrating,
)
from arena.combat.conditions import apply_condition, has_condition
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.character import Creature
from arena.models.conditions import Condition
from arena.models.encounter import CombatantEntry, Encounter


def _creature(name, hp=40, is_player=True):
    return Creature(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=12,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=[],
    )


def _manager():
    """Caster (player) + one enemy target, on a small grid."""
    combatants = [
        CombatantEntry(creature_id="caster", creature_data=_creature("Caster"),
                       team="player", starting_position=(4, 4)),
        CombatantEntry(creature_id="target",
                       creature_data=_creature("Target", is_player=False),
                       team="enemy", starting_position=(4, 6)),
    ]
    encounter = Encounter(
        name="Conc", grid_width=10, grid_height=10, combatants=combatants,
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    return cm


def _concentrate_with_link(cm):
    """Caster concentrates on a Hold-Person-shaped spell that paralyzes target."""
    caster = cm.combatants["caster"].creature
    target = cm.combatants["target"].creature
    start_concentrating(caster, "caster", "Hold Person", combatants=cm.combatants)
    apply_condition(target, "target", Condition.PARALYZED, source="Hold Person")
    add_concentration_link(caster, "target", "paralyzed")
    assert has_condition(caster, Condition.CONCENTRATING)
    assert has_condition(target, Condition.PARALYZED)
    return caster, target


class TestIncapacitationEndsConcentration:
    def test_stun_ends_concentration(self):
        cm = _manager()
        caster, _ = _concentrate_with_link(cm)
        apply_condition(caster, "caster", Condition.STUNNED, source="enemy")
        cm._reconcile_concentration()
        assert not has_condition(caster, Condition.CONCENTRATING)

    def test_stun_strips_linked_condition_from_target(self):
        cm = _manager()
        _, target = _concentrate_with_link(cm)
        caster = cm.combatants["caster"].creature
        apply_condition(caster, "caster", Condition.STUNNED, source="enemy")
        cm._reconcile_concentration()
        # The paralysis the spell was sustaining must lift with concentration.
        assert not has_condition(target, Condition.PARALYZED)

    def test_paralysis_ends_concentration(self):
        cm = _manager()
        caster, _ = _concentrate_with_link(cm)
        apply_condition(caster, "caster", Condition.PARALYZED, source="enemy")
        cm._reconcile_concentration()
        assert not has_condition(caster, Condition.CONCENTRATING)

    def test_dropping_to_zero_hp_ends_concentration(self):
        cm = _manager()
        caster, target = _concentrate_with_link(cm)
        caster.current_hit_points = 0
        assert not caster.is_conscious
        cm._reconcile_concentration()
        assert not has_condition(caster, Condition.CONCENTRATING)
        assert not has_condition(target, Condition.PARALYZED)

    def test_runs_through_check_victory(self):
        """The sweep is wired into the _check_victory reconcile batch, so a
        real action that incapacitates a concentrator breaks it automatically."""
        cm = _manager()
        caster, _ = _concentrate_with_link(cm)
        apply_condition(caster, "caster", Condition.UNCONSCIOUS, source="enemy")
        cm._check_victory()
        assert not has_condition(caster, Condition.CONCENTRATING)


class TestConcentrationSurvives:
    def test_healthy_concentrator_keeps_concentration(self):
        cm = _manager()
        caster, target = _concentrate_with_link(cm)
        cm._reconcile_concentration()
        assert has_condition(caster, Condition.CONCENTRATING)
        assert has_condition(target, Condition.PARALYZED)

    def test_banished_concentrator_keeps_concentration(self):
        """BANISHED is off-plane, not incapacitated in the concentration
        sense — P-BANISH relies on its links surviving."""
        cm = _manager()
        caster, _ = _concentrate_with_link(cm)
        apply_condition(caster, "caster", Condition.BANISHED, source="Banishment")
        cm._reconcile_concentration()
        assert has_condition(caster, Condition.CONCENTRATING)
