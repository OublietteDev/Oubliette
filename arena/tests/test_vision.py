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
