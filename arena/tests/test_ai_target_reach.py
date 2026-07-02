"""Attack scoring must respect what's attackable THIS turn.

OublietteDev's triceratops report (2026-07-02): standing against Gareth, it
planned Gore at far-away Thorin (higher threat score), walked the wrong
way, and whiffed "out of range" — the range penalty (10/hex) was too
gentle to stop a high-desirability far target from outbidding an
adjacent one. An unattackable-this-turn target now eats a decisive
penalty, so a reachable enemy always wins when one exists.
"""

from arena.ai.behavior import DEFAULT_PROFILES
from arena.ai.context import CombatContext, CreatureView
from arena.ai.scoring import score_attack_action
from arena.grid.coordinates import HexCoord
from arena.models.actions import Action, ActionType, Attack, DamageRoll, DamageType


def _gore():
    return Action(
        name="Gore", description="x", action_type=ActionType.ACTION,
        attack=Attack(
            name="Gore", attack_type="melee_weapon", ability="strength",
            reach=5,
            damage=[DamageRoll(dice="4d8", damage_type=DamageType.PIERCING,
                               ability_modifier="strength")],
        ),
    )


def _view(cid, team, pos, hp_pct=1.0, actions=1):
    return CreatureView(
        creature_id=cid, team=team, position=pos, hp_percent=hp_pct,
        is_conscious=True, armor_class=14, has_concentration=False,
        is_spellcaster=False, condition_names=(), max_hit_points=50,
        current_hit_points=int(50 * hp_pct), speed=30, actions_count=actions,
    )


def _context(me, enemies, movement_ft=50):
    return CombatContext(
        me=me, allies=(), enemies=tuple(enemies),
        all_combatants=(me, *enemies), grid_width=26, grid_height=14,
        round_number=1, remaining_movement=movement_ft,
        has_used_action=False, has_used_bonus_action=False,
    )


def test_adjacent_target_outscores_unreachable_high_threat_target():
    """A juicy target 15 hexes out (beyond reach + movement) must not
    outbid the enemy standing adjacent, no matter its threat profile."""
    me = _view("tricera", "enemy", HexCoord(5, 5))
    near = _view("gareth", "player", HexCoord(6, 5))               # adjacent
    far = _view("thorin", "player", HexCoord(20, 5), actions=5)    # tanky, far
    ctx = _context(me, [near, far], movement_ft=50)  # 10 hexes of movement
    profile = DEFAULT_PROFILES["berserker"]

    s_near = score_attack_action(_gore(), profile, ctx, near, 1)
    s_far = score_attack_action(_gore(), profile, ctx, far, 15)
    assert s_near > s_far


def test_reachable_far_target_keeps_its_ordinary_score():
    """A target the creature CAN close on this turn takes only the gentle
    per-hex penalty — approach-and-attack stays a normal, viable play."""
    me = _view("tricera", "enemy", HexCoord(5, 5))
    reachable = _view("gareth", "player", HexCoord(11, 5))  # 6 out, 10 move
    ctx = _context(me, [reachable], movement_ft=50)
    profile = DEFAULT_PROFILES["berserker"]

    s = score_attack_action(_gore(), profile, ctx, reachable, 6)
    # The decisive -150 must NOT have applied: with base priority and big
    # gore dice the score stays comfortably positive.
    assert s > 50
