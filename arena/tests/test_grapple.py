"""C5 — grapples that can be escaped.

Monster on-hit grapples ("grappled (escape DC 13)") now ride attacks:
gen_arena_monsters emits conditions_applied=["grappled"] + the stat
block's grapple_escape_dc, and the engine applies GRAPPLED with the DC
in extra_data — no re-save (escaping is its own action). The escape:
manager.execute_escape_grapple rolls d20 + the better of Athletics/
Acrobatics vs the stored DC (or contests the grappler's Athletics when
no DC was stored). A downed/incapacitated grappler releases its hold
automatically (_reconcile_grapples, RAW).
"""

import json
from pathlib import Path
from unittest.mock import patch

from arena.combat.actions import resolve_attack
from arena.combat.conditions import has_condition
from arena.combat.manager import CombatManager
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    Attack,
    DamageRoll,
    DamageType,
    TargetType,
)
from arena.models.character import Creature
from arena.models.conditions import AppliedCondition, Condition
from arena.models.encounter import CombatantEntry, Encounter

SRD_DIR = Path(__file__).resolve().parents[1] / "data" / "monsters" / "srd"


def _creature(name="Pip", hp=40, is_player=True, ac=10, strength=10):
    return Creature(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=[],
    )


def _tentacle(escape_dc=13):
    return Action(
        name="Tentacles", description="Grabby.",
        action_type=ActionType.ACTION, target_type=TargetType.ONE_CREATURE,
        range=5,
        attack=Attack(
            name="Tentacles", attack_type="melee_weapon", ability="strength",
            reach=5,
            damage=[DamageRoll(dice="1d6", damage_type=DamageType.BLUDGEONING)],
        ),
        conditions_applied=["grappled"],
        grapple_escape_dc=escape_dc,
    )


def _duel():
    """Grappler enemy vs PC; PC wins initiative."""
    encounter = Encounter(
        name="Grapple", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="pip", creature_data=_creature("Pip"),
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="squid",
                           creature_data=_creature("Squid", is_player=False),
                           team="enemy", starting_position=(4, 5)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10]):
        cm.roll_initiative()
    cm.begin_combat()
    return cm


def _grapple_pc(cm, escape_dc=13):
    cm.combatants["pip"].creature.active_conditions.append(AppliedCondition(
        condition=Condition.GRAPPLED, source="Squid",
        extra_data={"escape_dc": escape_dc} if escape_dc else {},
    ))


class TestGrappleRider:
    def test_hit_applies_grappled_with_escape_dc_and_no_resave(self):
        cm = _duel()
        squid = cm.combatants["squid"]
        pc = cm.combatants["pip"]
        with patch("arena.combat.actions.roll_die", return_value=15):
            resolve_attack(
                squid.creature, "squid", pc.creature, "pip",
                _tentacle(escape_dc=16), cm.grid,
                combatants=cm.combatants,
            )
        cond = next(ac for ac in pc.creature.active_conditions
                    if ac.condition == Condition.GRAPPLED)
        assert cond.extra_data["escape_dc"] == 16
        assert cond.save_to_end is None       # no free end-of-turn escape
        assert cond.duration_type == "indefinite"

    def test_srd_grapplers_carry_the_rider(self):
        data = json.loads(
            (SRD_DIR / "giant_octopus.json").read_text(encoding="utf-8"))
        tentacles = next(a for a in data["actions"]
                         if a["name"] == "Tentacles")
        assert "grappled" in tentacles["conditions_applied"]
        assert tentacles["grapple_escape_dc"] == 16


class TestEscape:
    def test_escape_success_removes_the_grapple_and_spends_the_action(self):
        cm = _duel()
        _grapple_pc(cm, escape_dc=13)
        with patch("arena.combat.manager.roll_die", return_value=15):
            result = cm.execute_escape_grapple()
        assert result.success
        assert not has_condition(
            cm.combatants["pip"].creature, Condition.GRAPPLED)
        assert cm.turn_resources.has_used_action

    def test_escape_failure_keeps_the_grapple(self):
        cm = _duel()
        _grapple_pc(cm, escape_dc=13)
        with patch("arena.combat.manager.roll_die", return_value=2):
            result = cm.execute_escape_grapple()
        assert not result.success
        assert has_condition(cm.combatants["pip"].creature, Condition.GRAPPLED)
        assert cm.turn_resources.has_used_action   # the attempt cost the action

    def test_no_dc_contests_the_grapplers_athletics(self):
        cm = _duel()
        _grapple_pc(cm, escape_dc=None)
        # escaper rolls 15, grappler rolls 5 — escape wins
        with patch("arena.combat.manager.roll_die", side_effect=[15, 5]):
            result = cm.execute_escape_grapple()
        assert result.success

    def test_not_grappled_returns_none(self):
        cm = _duel()
        assert cm.execute_escape_grapple() is None


class TestRelease:
    def test_downed_grappler_releases_its_hold(self):
        cm = _duel()
        _grapple_pc(cm)
        cm.combatants["squid"].creature.current_hit_points = 0
        cm._check_victory()
        assert not has_condition(
            cm.combatants["pip"].creature, Condition.GRAPPLED)

    def test_living_grappler_keeps_its_hold(self):
        cm = _duel()
        _grapple_pc(cm)
        cm._check_victory()
        assert has_condition(cm.combatants["pip"].creature, Condition.GRAPPLED)
