"""Tests for Phase 6a: CombatContext perception layer."""

import pytest
from unittest.mock import patch

from arena.ai.context import CreatureView, CombatContext, build_context, _make_creature_view
from arena.combat.manager import CombatManager, CombatState, TurnPhase, Combatant
from arena.models.abilities import AbilityScores
from arena.models.actions import Action, Attack, DamageRoll, DamageType, ActionType
from arena.models.character import Creature
from arena.models.conditions import Condition, AppliedCondition
from arena.models.encounter import Encounter, CombatantEntry
from arena.grid.coordinates import HexCoord


def _make_creature(name, hp, ac=10, strength=10, dexterity=10, is_player=True, actions=None):
    """Create a simple creature for testing."""
    if actions is None:
        actions = [
            Action(
                name="Sword",
                description="Melee weapon attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Sword",
                    attack_type="melee_weapon",
                    ability="strength",
                    reach=5,
                    damage=[
                        DamageRoll(
                            dice="1d6",
                            damage_type=DamageType.SLASHING,
                            ability_modifier="strength",
                        )
                    ],
                ),
            )
        ]
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        ability_scores=AbilityScores(strength=strength, dexterity=dexterity),
        proficiency_bonus=2,
        is_player_controlled=is_player,
        actions=actions,
    )


def _make_spellcaster(name, hp, ac=10, is_player=True):
    """Create a creature with spell attacks."""
    return Creature(
        name=name,
        max_hit_points=hp,
        armor_class=ac,
        is_player_controlled=is_player,
        actions=[
            Action(
                name="Fire Bolt",
                description="Ranged spell attack",
                action_type=ActionType.ACTION,
                attack=Attack(
                    name="Fire Bolt",
                    attack_type="ranged_spell",
                    ability="intelligence",
                    range_normal=120,
                    damage=[
                        DamageRoll(dice="1d10", damage_type=DamageType.FIRE)
                    ],
                ),
            )
        ],
    )


def _setup_combat(combatant_specs):
    """Set up a CombatManager with specified combatants.

    combatant_specs: list of (name, hp, team, position, is_player, creature_or_None)
    """
    entries = []
    for spec in combatant_specs:
        name, hp, team, position, is_player = spec[:5]
        creature = spec[5] if len(spec) > 5 else None
        if creature is None:
            creature = _make_creature(name, hp, is_player=is_player)
        entries.append(
            CombatantEntry(
                creature_id=f"inline_{name.lower().replace(' ', '_')}",
                creature_data=creature,
                team=team,
                starting_position=position,
            )
        )

    encounter = Encounter(
        name="Test",
        grid_width=10,
        grid_height=10,
        combatants=entries,
    )

    cm = CombatManager()
    from pathlib import Path
    cm.load_encounter(encounter, Path("."))

    with patch("arena.combat.manager.roll_die", return_value=10):
        cm.roll_initiative()
    cm.begin_combat()
    return cm


# ── CreatureView ─────────────────────────────────────────────────────

class TestCreatureView:
    def test_creation_from_combatant(self):
        creature = _make_creature("Fighter", hp=20, ac=15)
        combatant = Combatant(
            creature_id="fighter",
            creature=creature,
            team="player",
            position=HexCoord(3, 4),
        )
        view = _make_creature_view(combatant)
        assert view.creature_id == "fighter"
        assert view.team == "player"
        assert view.position == HexCoord(3, 4)
        assert view.hp_percent == 1.0
        assert view.is_conscious is True
        assert view.armor_class == 15
        assert view.max_hit_points == 20
        assert view.current_hit_points == 20

    def test_hp_percent_reflects_damage(self):
        creature = _make_creature("Fighter", hp=20)
        creature.current_hit_points = 10
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.hp_percent == 0.5

    def test_unconscious_creature(self):
        creature = _make_creature("Fighter", hp=20)
        creature.current_hit_points = 0
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.is_conscious is False
        assert view.hp_percent == 0.0

    def test_spellcaster_detection_spell_attack(self):
        creature = _make_spellcaster("Wizard", hp=15)
        combatant = Combatant(
            creature_id="wizard", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.is_spellcaster is True

    def test_non_spellcaster_detection(self):
        creature = _make_creature("Fighter", hp=20)
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.is_spellcaster is False

    def test_concentration_detection(self):
        creature = _make_creature("Wizard", hp=15)
        creature.active_conditions.append(
            AppliedCondition(
                condition=Condition.CONCENTRATING,
                source="self",
            )
        )
        combatant = Combatant(
            creature_id="wizard", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.has_concentration is True

    def test_no_concentration(self):
        creature = _make_creature("Fighter", hp=20)
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.has_concentration is False

    def test_condition_names_captured(self):
        creature = _make_creature("Fighter", hp=20)
        creature.active_conditions.append(
            AppliedCondition(condition=Condition.POISONED, source="spider")
        )
        creature.active_conditions.append(
            AppliedCondition(condition=Condition.PRONE, source="fall")
        )
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert "poisoned" in view.condition_names
        assert "prone" in view.condition_names

    def test_frozen_immutability(self):
        creature = _make_creature("Fighter", hp=20)
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        with pytest.raises(AttributeError):
            view.hp_percent = 0.5

    def test_speed_captured(self):
        creature = _make_creature("Fighter", hp=20)
        creature.speed = {"walk": 25}
        combatant = Combatant(
            creature_id="dwarf", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.speed == 25

    def test_actions_count(self):
        creature = _make_creature("Fighter", hp=20)
        combatant = Combatant(
            creature_id="fighter", creature=creature, team="player"
        )
        view = _make_creature_view(combatant)
        assert view.actions_count == 1


# ── build_context ────────────────────────────────────────────────────

class TestBuildContext:
    def test_returns_none_without_active_combatant(self):
        cm = CombatManager()
        assert build_context(cm) is None

    def test_basic_context_creation(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (4, 2), False),
        ])
        ctx = build_context(cm)
        assert ctx is not None
        assert ctx.grid_width == 10
        assert ctx.grid_height == 10
        assert ctx.round_number >= 1

    def test_enemy_ally_separation(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Cleric", 18, "player", (2, 3), True),
            ("Goblin", 7, "enemy", (5, 2), False),
            ("Wolf", 11, "enemy", (5, 3), False),
        ])
        ctx = build_context(cm)
        assert ctx is not None

        # me is the active combatant; allies are same team (excluding me)
        my_team = ctx.me.team
        for ally in ctx.allies:
            assert ally.team == my_team
            assert ally.creature_id != ctx.me.creature_id

        for enemy in ctx.enemies:
            assert enemy.team != my_team

    def test_unconscious_excluded_from_enemies(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (5, 2), False),
        ])
        # Knock out the goblin
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                c.creature.current_hit_points = 0

        ctx = build_context(cm)
        assert ctx is not None
        assert len(ctx.enemies) == 0

    def test_unconscious_still_in_all_combatants(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (5, 2), False),
        ])
        for cid, c in cm.combatants.items():
            if c.team == "enemy":
                c.creature.current_hit_points = 0

        ctx = build_context(cm)
        assert ctx is not None
        # all_combatants includes everyone
        assert len(ctx.all_combatants) == 2

    def test_movement_state_captured(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (5, 2), False),
        ])
        ctx = build_context(cm)
        assert ctx is not None
        assert ctx.remaining_movement >= 0

    def test_action_state_captured(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (5, 2), False),
        ])
        ctx = build_context(cm)
        assert ctx is not None
        assert ctx.has_used_action is False
        assert ctx.has_used_bonus_action is False


# ── CombatContext immutability ───────────────────────────────────────

class TestContextImmutability:
    def test_context_is_frozen(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (5, 2), False),
        ])
        ctx = build_context(cm)
        assert ctx is not None
        with pytest.raises(AttributeError):
            ctx.round_number = 99

    def test_allies_tuple_immutable(self):
        cm = _setup_combat([
            ("Fighter", 20, "player", (2, 2), True),
            ("Goblin", 7, "enemy", (5, 2), False),
        ])
        ctx = build_context(cm)
        assert ctx is not None
        assert isinstance(ctx.allies, tuple)
        assert isinstance(ctx.enemies, tuple)
