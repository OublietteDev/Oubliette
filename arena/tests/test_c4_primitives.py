"""C4 — new spell/feature primitives.

Sculpt Spells (Evocation wizard): the caster's harmful AoE spares allies
entirely — both effect-target resolvers, the AI's friendly-fire scoring,
and (visually) the AoE preview. The approximation of RAW's "choose 1+level
creatures to auto-succeed" is full exemption of the caster's team.
"""

from pathlib import Path
from unittest.mock import patch

from arena.ai.behavior import AIProfile
from arena.ai.context import CombatContext, CreatureView
from arena.ai.scoring import score_effect_action
from arena.combat.manager import CombatManager
from arena.combat.stat_modifiers import has_sculpt_spells
from arena.grid.coordinates import HexCoord
from arena.models.abilities import AbilityScores
from arena.models.actions import (
    Action,
    ActionType,
    DamageRoll,
    DamageType,
    SavingThrowEffect,
    TargetType,
)
from arena.models.character import Creature, Feature, PlayerCharacter
from arena.models.encounter import CombatantEntry, Encounter

SCULPT = Feature(name="Sculpt Spells", description="Spare allies from blasts.",
                 sculpt_spells=True)


def _creature(name="Pip", hp=40, is_player=True, actions=None, features=None):
    # Features live on PlayerCharacter, not base Creature — same split the
    # bridge uses (only PCs carry staged class features).
    common = dict(
        name=name,
        max_hit_points=hp,
        current_hit_points=hp,
        armor_class=12,
        ability_scores=AbilityScores(),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=actions or [],
    )
    if features:
        return PlayerCharacter(
            character_class="Wizard", features=features, **common)
    return Creature(**common)


def _fireburst(healing=False):
    if healing:
        return Action(
            name="Mass Cure", description="Healing burst",
            action_type=ActionType.ACTION, target_type=TargetType.AREA_SPHERE,
            range=30, area_size=15, healing="1d8",
        )
    return Action(
        name="Burst", description="A damaging burst",
        action_type=ActionType.ACTION, target_type=TargetType.AREA_SPHERE,
        range=30, area_size=15, spell_level=3,
        saving_throw=SavingThrowEffect(
            ability="dexterity", dc=15,
            damage_on_fail=[DamageRoll(dice="2d6", damage_type=DamageType.FIRE)],
            damage_on_success="half",
        ),
    )


def _three_way_combat(caster_features=None):
    """Caster + adjacent ally vs adjacent enemy, everyone inside a 15ft blast."""
    caster = _creature("Caster", actions=[_fireburst()],
                       features=caster_features)
    ally = _creature("Ally")
    enemy = _creature("Brute", is_player=False)
    encounter = Encounter(
        name="Sculpt", grid_width=10, grid_height=10,
        combatants=[
            CombatantEntry(creature_id="caster", creature_data=caster,
                           team="player", starting_position=(4, 4)),
            CombatantEntry(creature_id="ally", creature_data=ally,
                           team="player", starting_position=(5, 4)),
            CombatantEntry(creature_id="brute", creature_data=enemy,
                           team="enemy", starting_position=(4, 5)),
        ],
    )
    cm = CombatManager()
    cm.load_encounter(encounter, Path("."))
    with patch("arena.combat.manager.roll_die", side_effect=[20, 10, 1]):
        cm.roll_initiative()
    cm.begin_combat()
    by_name = {c.creature.name: (cid, c) for cid, c in cm.combatants.items()}
    return cm, by_name


class TestSculptSpellsQuery:
    def test_feature_flag_detected(self):
        assert has_sculpt_spells(_creature(features=[SCULPT]))

    def test_absent_by_default(self):
        assert not has_sculpt_spells(_creature())


class TestSculptSpellsTargets:
    def test_harmful_aoe_spares_allies(self):
        cm, by_name = _three_way_combat(caster_features=[SCULPT])
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets(_fireburst(), caster, brute_id)
        assert brute_id in affected
        assert ally_id not in affected      # sculpted around

    def test_hex_targeted_aoe_spares_caster_and_ally(self):
        cm, by_name = _three_way_combat(caster_features=[SCULPT])
        caster_id, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets_at_hex(
            _fireburst(), caster, HexCoord(4, 4),
        )
        assert brute_id in affected
        assert ally_id not in affected
        assert caster_id not in affected    # sculpting around yourself too

    def test_beneficial_aoe_still_reaches_allies(self):
        cm, by_name = _three_way_combat(caster_features=[SCULPT])
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        affected = cm._resolve_effect_targets(
            _fireburst(healing=True), caster, ally_id,
        )
        assert ally_id in affected

    def test_without_sculpt_friendly_fire_still_real(self):
        cm, by_name = _three_way_combat()
        _, caster = by_name["Caster"]
        ally_id, _ = by_name["Ally"]
        brute_id, _ = by_name["Brute"]
        affected = cm._resolve_effect_targets(_fireburst(), caster, brute_id)
        assert ally_id in affected          # B5 invariant unchanged


def _view(cid, team, pos, sculpt=False):
    return CreatureView(
        creature_id=cid, team=team, position=HexCoord(*pos), hp_percent=1.0,
        is_conscious=True, armor_class=12, has_concentration=False,
        is_spellcaster=False, condition_names=(), max_hit_points=20,
        current_hit_points=20, speed=30, actions_count=1,
        has_sculpt_spells=sculpt,
    )


def _context(me, allies=(), enemies=()):
    return CombatContext(
        me=me, allies=tuple(allies), enemies=tuple(enemies),
        all_combatants=(me, *allies, *enemies),
        grid_width=12, grid_height=12, round_number=1,
        remaining_movement=30, has_used_action=False,
        has_used_bonus_action=False,
    )


class TestSculptSpellsAiScoring:
    def test_sculpt_caster_ignores_allies_in_blast(self):
        target = _view("pc", "player", (6, 5))
        ally_in = _view("buddy", "enemy", (5, 6))   # 1 hex — inside 15ft
        burst = _fireburst()
        profile = AIProfile(name="caster", prefers_melee=False)
        plain = _view("me", "enemy", (5, 5))
        sculpted = _view("me", "enemy", (5, 5), sculpt=True)
        s_plain = score_effect_action(
            burst, profile, _context(plain, [ally_in], [target]), target, 1,
        )
        s_sculpt = score_effect_action(
            burst, profile, _context(sculpted, [ally_in], [target]), target, 1,
        )
        assert s_sculpt > s_plain           # no friendly-fire penalty
