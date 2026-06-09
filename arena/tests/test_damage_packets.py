"""Tests for the per-type damage-packet pipeline (Stage 3.5 / D-COMBAT-5).

The point of the refactor: a mixed-type attack (e.g. a dragon's piercing+fire
bite) must resolve resistance / immunity / vulnerability PER TYPE, not collapse
into the first type only.  These tests exercise that, plus the safety property
that single-type damage is byte-identical to the old scalar math.
"""

from unittest.mock import patch

from arena.combat.damage import (
    DamagePacket,
    apply_damage,
    halve_packets,
    zero_packets,
    reduce_packets_flat,
    _apply_damage_modifiers,
)
from arena.combat.actions import resolve_attack_damage, AttackHitResult
from arena.models.abilities import AbilityScores
from arena.models.actions import Attack, DamageRoll, DamageType
from arena.models.character import Creature


def _make_creature(hp=100, resistances=None, immunities=None, vulnerabilities=None,
                   temp_hp=0):
    c = Creature(
        name="Target",
        max_hit_points=hp,
        current_hit_points=hp,
        ability_scores=AbilityScores(),
        damage_resistances=resistances or [],
        damage_immunities=immunities or [],
        damage_vulnerabilities=vulnerabilities or [],
    )
    c.temporary_hit_points = temp_hp
    return c


def _mixed_bite():
    """8 piercing + 8 fire packets (a dragon-style mixed bite)."""
    return [
        DamagePacket(amount=8, dtype="piercing"),
        DamagePacket(amount=8, dtype="fire"),
    ]


# ── Per-type defenses on mixed damage (the whole point) ──────────────

class TestMixedTypeDefenses:
    def test_resistance_halves_only_matching_type(self):
        target = _make_creature(hp=100, resistances=["fire"])
        event, _ = apply_damage(target, _mixed_bite())
        # piercing 8 (full) + fire 4 (halved) = 12
        assert target.current_hit_points == 88
        assert event.details["damage"] == 12
        assert event.details["raw_damage"] == 16

    def test_immunity_zeros_only_matching_type(self):
        target = _make_creature(hp=100, immunities=["fire"])
        event, _ = apply_damage(target, _mixed_bite())
        # piercing 8 (full) + fire 0 (immune) = 8
        assert target.current_hit_points == 92
        assert event.details["damage"] == 8

    def test_vulnerability_doubles_only_matching_type(self):
        target = _make_creature(hp=100, vulnerabilities=["fire"])
        event, _ = apply_damage(target, _mixed_bite())
        # piercing 8 (full) + fire 16 (doubled) = 24
        assert target.current_hit_points == 76
        assert event.details["damage"] == 24

    def test_resistance_to_nonpresent_type_changes_nothing(self):
        target = _make_creature(hp=100, resistances=["cold"])
        event, _ = apply_damage(target, _mixed_bite())
        assert event.details["damage"] == 16

    def test_message_lists_both_types(self):
        target = _make_creature(hp=100, resistances=["fire"])
        event, _ = apply_damage(target, _mixed_bite())
        assert "piercing+fire" in event.message
        assert "RESISTANT" in event.message

    def test_per_packet_breakdown_in_details(self):
        target = _make_creature(hp=100, resistances=["fire"])
        event, _ = apply_damage(target, _mixed_bite())
        packets = event.details["packets"]
        assert packets[0] == {"amount": 8, "damage_type": "piercing", "modifier_text": ""}
        assert packets[1]["amount"] == 4
        assert "RESISTANT" in packets[1]["modifier_text"]


# ── Temp HP across packets ───────────────────────────────────────────

class TestTempHpAcrossPackets:
    def test_temp_hp_absorbs_across_both_types(self):
        target = _make_creature(hp=100, temp_hp=10)
        event, _ = apply_damage(target, _mixed_bite())
        # 16 total; 10 absorbed by temp, 6 to HP
        assert target.temporary_hit_points == 0
        assert target.current_hit_points == 94
        assert event.details["temp_absorbed"] == 10

    def test_temp_hp_after_resistance(self):
        target = _make_creature(hp=100, temp_hp=10, resistances=["fire"])
        event, _ = apply_damage(target, _mixed_bite())
        # resistance first: 8 + 4 = 12; temp absorbs 10, 2 to HP
        assert target.temporary_hit_points == 0
        assert target.current_hit_points == 98


# ── Reduction / halving helpers ──────────────────────────────────────

class TestPacketHelpers:
    def test_halve_packets_floors_each(self):
        packets = [DamagePacket(amount=7, dtype="fire"), DamagePacket(amount=5, dtype="cold")]
        halve_packets(packets)
        assert [p.amount for p in packets] == [3, 2]

    def test_zero_packets(self):
        packets = _mixed_bite()
        zero_packets(packets)
        assert all(p.amount == 0 for p in packets)

    def test_reduce_flat_drains_in_order(self):
        packets = [DamagePacket(amount=5, dtype="fire"), DamagePacket(amount=5, dtype="cold")]
        reduce_packets_flat(packets, 7)
        # 5 from first, 2 from second
        assert [p.amount for p in packets] == [0, 3]

    def test_reduce_flat_respects_can_reduce(self):
        packets = [
            DamagePacket(amount=5, dtype="fire", can_reduce=False),
            DamagePacket(amount=5, dtype="cold"),
        ]
        reduce_packets_flat(packets, 4)
        assert [p.amount for p in packets] == [5, 1]


# ── Safety property: single-type == old scalar math ──────────────────

class TestSingleTypeEquivalence:
    def test_single_type_resistance_equals_scalar(self):
        # apply_damage with a 1-packet list must match the int shim exactly.
        a = _make_creature(hp=50, resistances=["fire"])
        b = _make_creature(hp=50, resistances=["fire"])
        ev_packet, _ = apply_damage(a, [DamagePacket(amount=11, dtype="fire")])
        ev_scalar, _ = apply_damage(b, 11, "fire")
        assert a.current_hit_points == b.current_hit_points
        assert ev_packet.details["damage"] == ev_scalar.details["damage"] == 5

    def test_scalar_shim_matches_legacy_modifiers(self):
        target = _make_creature(resistances=["fire"])
        dmg, text = _apply_damage_modifiers(target, 10, "fire")
        assert dmg == 5 and "RESISTANT" in text


# ── End-to-end through the real producer path ────────────────────────

class TestProducerIntegration:
    def _hit(self, attacker, target, attack):
        return AttackHitResult(
            hit=True,
            critical=False,
            natural_roll=15,
            modifier=4,
            total_roll=19,
            target_ac=10,
            effective_advantage=0,
            events=[],
            attacker=attacker,
            attacker_id="dragon_1",
            target=target,
            target_id="hero_1",
            action=None,
            attack=attack,
            combatants={"dragon_1": attacker, "hero_1": target},
        )

    def test_mixed_attack_resists_only_fire_through_resolve(self):
        attacker = Creature(name="Dragon", max_hit_points=200, current_hit_points=200,
                            ability_scores=AbilityScores())
        target = _make_creature(hp=100, resistances=["fire"])
        attack = Attack(
            name="Bite",
            attack_type="melee_weapon",
            ability="strength",
            damage=[
                DamageRoll(dice="2d6", damage_type=DamageType.PIERCING),
                DamageRoll(dice="2d6", damage_type=DamageType.FIRE),
            ],
        )
        hit = self._hit(attacker, target, attack)
        # roll_damage produces a packet per type; control the amounts.
        with patch("arena.combat.actions.roll_damage",
                   side_effect=lambda *a, **k: [
                       DamagePacket(amount=10, dtype="piercing"),
                       DamagePacket(amount=10, dtype="fire"),
                   ]):
            result = resolve_attack_damage(hit)
        dmg_events = [e for e in result.events
                      if e.details.get("damage") is not None]
        assert dmg_events
        # piercing 10 (full) + fire 5 (halved) = 15
        assert dmg_events[0].details["damage"] == 15
        assert target.current_hit_points == 85
