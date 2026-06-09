"""Tests for counterspell and spell interruption mechanics."""

import pytest
from unittest.mock import patch

from arena.models.actions import Action, ActionType
from arena.models.abilities import AbilityScores
from arena.models.character import Creature, PlayerCharacter
from arena.combat.counterspell import can_counterspell, resolve_counterspell


# ── Helpers ──────────────────────────────────────────────────────────


def _make_counterspell(spell_level=3, auto_level=None):
    """Create a Counterspell action."""
    return Action(
        name="Counterspell",
        description="Counter a spell being cast.",
        action_type=ActionType.REACTION,
        is_counterspell=True,
        spell_level=spell_level,
        counterspell_auto_level=auto_level,
        counterspell_check_dc_base=10,
    )


def _make_spell(name="Fireball", spell_level=3):
    """Create a generic spell action."""
    return Action(
        name=name,
        description=f"Cast {name}.",
        action_type=ActionType.ACTION,
        spell_level=spell_level,
    )


def _make_non_spell():
    """Create a non-spell action (spell_level=None)."""
    return Action(
        name="Longsword",
        description="Melee weapon attack.",
        action_type=ActionType.ACTION,
        spell_level=None,
    )


def _make_caster(spellcasting_ability="intelligence", intelligence=18, wisdom=10, charisma=10):
    """Create a PlayerCharacter caster."""
    return PlayerCharacter(
        name="Wizard",
        max_hit_points=30,
        character_class="Wizard",
        level=5,
        spellcasting_ability=spellcasting_ability,
        ability_scores=AbilityScores(
            intelligence=intelligence,
            wisdom=wisdom,
            charisma=charisma,
        ),
    )


def _make_base_creature():
    """Create a basic Creature (no spellcasting_ability field)."""
    return Creature(
        name="Goblin Shaman",
        max_hit_points=20,
        ability_scores=AbilityScores(intelligence=14),
    )


# ── can_counterspell tests ───────────────────────────────────────────


class TestCanCounterspell:
    """Tests for can_counterspell()."""

    def test_valid_counterspell_vs_spell(self):
        cs = _make_counterspell()
        spell = _make_spell()
        assert can_counterspell(cs, spell) is True

    def test_cannot_counter_non_spell(self):
        cs = _make_counterspell()
        non_spell = _make_non_spell()
        assert can_counterspell(cs, non_spell) is False

    def test_non_counterspell_action_cannot_counter(self):
        regular = Action(
            name="Shield",
            description="Reaction spell.",
            action_type=ActionType.REACTION,
            is_counterspell=False,
            spell_level=1,
        )
        spell = _make_spell()
        assert can_counterspell(regular, spell) is False

    def test_counterspell_vs_cantrip(self):
        """Cantrips have spell_level=0, which is still a spell."""
        cs = _make_counterspell()
        cantrip = _make_spell(name="Fire Bolt", spell_level=0)
        assert can_counterspell(cs, cantrip) is True


# ── resolve_counterspell tests ───────────────────────────────────────


class TestResolveCounterspellAutoCounter:
    """Tests for auto-counter scenarios."""

    def test_auto_counter_same_level(self):
        """3rd level counterspell vs 3rd level spell = auto-counter."""
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Fireball", spell_level=3)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
        )

        assert success is True
        assert len(events) == 1
        assert events[0].details["counterspell_success"] is True
        assert events[0].details["auto"] is True
        assert "automatically counters" in events[0].message

    def test_auto_counter_upcast_counterspell(self):
        """5th level counterspell vs 3rd level spell = auto-counter."""
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Fireball", spell_level=3)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
            counterspell_cast_level=5,
        )

        assert success is True
        assert events[0].details["auto"] is True

    def test_auto_counter_upcast_vs_upcast_target(self):
        """5th level counterspell vs 5th level upcast Fireball = auto-counter."""
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Fireball", spell_level=3)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
            target_spell_cast_level=5,
            counterspell_cast_level=5,
        )

        assert success is True
        assert events[0].details["auto"] is True

    def test_auto_counter_low_level_spell(self):
        """3rd level counterspell vs 1st level spell = auto-counter."""
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Magic Missile", spell_level=1)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
        )

        assert success is True
        assert events[0].details["auto"] is True


class TestResolveCounterspellAbilityCheck:
    """Tests for ability check scenarios."""

    @patch("arena.combat.counterspell.roll_die")
    def test_ability_check_needed_high_target(self, mock_roll):
        """3rd level counterspell vs 5th level spell needs ability check."""
        mock_roll.return_value = 10
        caster = _make_caster(intelligence=18)  # +4 modifier
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Cone of Cold", spell_level=5)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
        )

        # DC = 10 + 5 = 15, roll 10 + 4 = 14 < 15
        assert success is False
        assert events[0].details["auto"] is False
        assert events[0].details["dc"] == 15
        assert events[0].details["natural"] == 10
        assert events[0].details["modifier"] == 4
        assert events[0].details["roll"] == 14
        assert "FAILURE" in events[0].message

    @patch("arena.combat.counterspell.roll_die")
    def test_ability_check_success_high_roll(self, mock_roll):
        """High roll succeeds on ability check."""
        mock_roll.return_value = 15
        caster = _make_caster(intelligence=18)  # +4 modifier
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Cone of Cold", spell_level=5)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
        )

        # DC = 10 + 5 = 15, roll 15 + 4 = 19 >= 15
        assert success is True
        assert events[0].details["counterspell_success"] is True
        assert events[0].details["auto"] is False
        assert events[0].details["roll"] == 19
        assert "SUCCESS" in events[0].message

    @patch("arena.combat.counterspell.roll_die")
    def test_ability_check_failure_low_roll(self, mock_roll):
        """Low roll fails on ability check."""
        mock_roll.return_value = 2
        caster = _make_caster(intelligence=14)  # +2 modifier
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Power Word Kill", spell_level=9)

        success, events = resolve_counterspell(
            caster, "wizard_1", cs, target,
        )

        # DC = 10 + 9 = 19, roll 2 + 2 = 4 < 19
        assert success is False
        assert events[0].details["dc"] == 19
        assert events[0].details["roll"] == 4
        assert "fails to counter" in events[0].message


class TestDCCalculation:
    """Tests for DC = 10 + target spell level."""

    @patch("arena.combat.counterspell.roll_die")
    def test_dc_for_5th_level_spell(self, mock_roll):
        mock_roll.return_value = 1
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Cone of Cold", spell_level=5)

        _, events = resolve_counterspell(caster, "w1", cs, target)
        assert events[0].details["dc"] == 15

    @patch("arena.combat.counterspell.roll_die")
    def test_dc_for_9th_level_spell(self, mock_roll):
        mock_roll.return_value = 1
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Wish", spell_level=9)

        _, events = resolve_counterspell(caster, "w1", cs, target)
        assert events[0].details["dc"] == 19

    @patch("arena.combat.counterspell.roll_die")
    def test_dc_for_4th_level_spell(self, mock_roll):
        mock_roll.return_value = 1
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Blight", spell_level=4)

        _, events = resolve_counterspell(caster, "w1", cs, target)
        assert events[0].details["dc"] == 14

    @patch("arena.combat.counterspell.roll_die")
    def test_dc_uses_upcast_target_level(self, mock_roll):
        """DC uses the cast level, not the base spell level."""
        mock_roll.return_value = 1
        caster = _make_caster()
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Fireball", spell_level=3)

        _, events = resolve_counterspell(
            caster, "w1", cs, target,
            target_spell_cast_level=7,
        )
        # DC = 10 + 7 (cast level), not 10 + 3 (base level)
        assert events[0].details["dc"] == 17


class TestSpellcastingAbility:
    """Tests for different spellcasting abilities."""

    @patch("arena.combat.counterspell.roll_die")
    def test_wisdom_caster(self, mock_roll):
        """Cleric uses wisdom for counterspell check."""
        mock_roll.return_value = 10
        caster = PlayerCharacter(
            name="Cleric",
            max_hit_points=40,
            character_class="Cleric",
            level=5,
            spellcasting_ability="wisdom",
            ability_scores=AbilityScores(intelligence=10, wisdom=20),
        )
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Fireball", spell_level=5)

        success, events = resolve_counterspell(
            caster, "cleric_1", cs, target,
        )

        # DC = 15, roll 10 + 5 (WIS) = 15 >= 15
        assert success is True
        assert events[0].details["modifier"] == 5

    @patch("arena.combat.counterspell.roll_die")
    def test_charisma_caster(self, mock_roll):
        """Sorcerer uses charisma for counterspell check."""
        mock_roll.return_value = 10
        caster = PlayerCharacter(
            name="Sorcerer",
            max_hit_points=30,
            character_class="Sorcerer",
            level=5,
            spellcasting_ability="charisma",
            ability_scores=AbilityScores(intelligence=10, charisma=18),
        )
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Hold Person", spell_level=5)

        success, events = resolve_counterspell(
            caster, "sorcerer_1", cs, target,
        )

        # DC = 15, roll 10 + 4 (CHA) = 14 < 15
        assert success is False
        assert events[0].details["modifier"] == 4

    @patch("arena.combat.counterspell.roll_die")
    def test_base_creature_defaults_to_intelligence(self, mock_roll):
        """Creature without spellcasting_ability defaults to intelligence."""
        mock_roll.return_value = 10
        creature = _make_base_creature()  # INT 14 = +2
        cs = _make_counterspell(spell_level=3)
        target = _make_spell(name="Lightning Bolt", spell_level=5)

        success, events = resolve_counterspell(
            creature, "goblin_1", cs, target,
        )

        # DC = 15, roll 10 + 2 (INT) = 12 < 15
        assert success is False
        assert events[0].details["modifier"] == 2
