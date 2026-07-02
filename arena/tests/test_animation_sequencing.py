"""Tests for animation sequencing: the director and event→beat grouping.

The AnimationDirector is pure timing logic (no pygame), so it's tested
directly with hand-rolled clocks. The grouping tests exercise the REAL
CombatScreen methods (_sequence_event and friends) on a bare instance
with stub collaborators, feeding event batches shaped like the actual
GUI path emits them (execute_attack_hit_check → complete_attack order,
multiattack, volleys) — per the test-the-real-path rule.
"""

from dataclasses import dataclass, field

import pytest

from arena.combat.events import CombatEvent, CombatEventType
from arena.grid.coordinates import HexCoord
from arena.gui.animation_director import AnimationDirector, Beat
from arena.gui.screens.combat import (
    CombatScreen,
    IMPACT_BEAT_MS,
    MELEE_IMPACT_DELAY_MS,
    PROJECTILE_TRAVEL_MS,
)


# ------------------------------------------------------------------
# AnimationDirector
# ------------------------------------------------------------------


class TestAnimationDirector:
    def test_idle_by_default(self):
        director = AnimationDirector()
        assert not director.is_busy
        director.update(1000)  # no-op, no crash

    def test_beats_fire_in_order_with_holds(self):
        director = AnimationDirector()
        fired: list[str] = []
        director.enqueue(Beat(cues=[lambda t: fired.append("a")], duration_ms=300))
        director.enqueue(Beat(cues=[lambda t: fired.append("b")], duration_ms=250))

        director.update(1000)
        assert fired == ["a"]
        assert director.is_busy

        director.update(1299)  # still holding beat a
        assert fired == ["a"]

        director.update(1300)  # a's hold over → b fires
        assert fired == ["a", "b"]
        assert director.is_busy  # b holds until 1550

        director.update(1550)
        assert not director.is_busy

    def test_zero_duration_beats_chain_in_one_update(self):
        director = AnimationDirector()
        fired: list[str] = []
        director.enqueue(Beat(cues=[lambda t: fired.append("a")]))
        director.enqueue(Beat(cues=[lambda t: fired.append("b")]))
        director.update(50)
        assert fired == ["a", "b"]
        assert not director.is_busy

    def test_cue_receives_fire_time(self):
        director = AnimationDirector()
        times: list[int] = []
        director.enqueue(Beat(cues=[times.append], duration_ms=100))
        director.enqueue(Beat(cues=[times.append]))
        director.update(500)
        director.update(700)  # past the first hold
        assert times == [500, 700]

    def test_add_cue_before_fire_joins_beat(self):
        director = AnimationDirector()
        fired: list[str] = []
        beat = director.enqueue(Beat(duration_ms=100))
        assert beat.add_cue(lambda t: fired.append("late"))
        director.update(10)
        assert fired == ["late"]

    def test_add_cue_after_fire_is_refused(self):
        director = AnimationDirector()
        beat = director.enqueue(Beat(duration_ms=100))
        director.update(10)
        assert beat.fired
        assert not beat.add_cue(lambda t: None)

    def test_clear_fires_pending_cues(self):
        # Cues release visual holds, so an abandoned sequence must
        # still run them or a hold would leak.
        director = AnimationDirector()
        fired: list[str] = []
        director.enqueue(Beat(cues=[lambda t: fired.append("a")], duration_ms=100))
        director.enqueue(Beat(cues=[lambda t: fired.append("b")], duration_ms=100))
        director.update(10)  # a fires, b pending
        director.clear(20)
        assert fired == ["a", "b"]
        assert not director.is_busy


# ------------------------------------------------------------------
# Event grouping on the real CombatScreen methods
# ------------------------------------------------------------------


@dataclass
class _StubCreature:
    is_conscious: bool = True
    current_hit_points: int = 20
    max_hit_points: int = 20


@dataclass
class _StubCombatant:
    position: HexCoord | None
    creature: _StubCreature = field(default_factory=_StubCreature)


class _StubCombat:
    def __init__(self, combatants):
        self.combatants = combatants


HEX_SIZE = 32


def _make_screen(monkeypatch, frames=8, fps=20):
    """A bare CombatScreen wired with just what sequencing touches.

    The real animation cache has no frames for test-only names, so the
    module-level lookups are patched; the spawn methods are replaced
    with recorders because these tests assert WHEN visuals fire, not
    what they draw.
    """
    import arena.gui.screens.combat as combat_mod

    monkeypatch.setattr(
        combat_mod, "get_animation_frames",
        lambda name, size: [object()] * frames if name != "missing" else [],
    )
    monkeypatch.setattr(combat_mod, "get_animation_fps", lambda name: fps)

    screen = CombatScreen.__new__(CombatScreen)
    screen.combat = _StubCombat({
        "archer": _StubCombatant(HexCoord(0, 0)),
        "wolf": _StubCombatant(HexCoord(1, 0)),
        "goblin": _StubCombatant(HexCoord(4, 0)),
    })
    screen._director = AnimationDirector()
    screen._pending_impact = None
    screen._impact_source = None
    screen._hp_credit = {}
    screen._downed_hold = set()
    screen._flash_until = {}
    screen._floating_texts = []
    screen._log_reveal_index = 0

    screen.spawned_anims = []
    screen.spawned_effects = []
    screen._try_spawn_animation = (
        lambda event, wx, wy, hex_size, t: screen.spawned_anims.append((event, t))
    )
    screen._try_spawn_visual_effect = (
        lambda event, hex_size, t: screen.spawned_effects.append((event, t))
    )
    return screen


def _ranged_hit(source="archer", target="goblin", damage=6, crit=False):
    """Events in the order the real hit-check → complete path logs them."""
    return [
        CombatEvent(
            CombatEventType.ATTACK_ROLL, "hits",
            source_id=source, target_id=target,
            details={"animation": "arrow", "attack_type": "ranged_weapon"},
        ),
        CombatEvent(
            CombatEventType.DAMAGE, "damage",
            source_id=source, target_id=target,
            details={"damage": damage, "critical": crit},
        ),
    ]


def _feed(screen, events, now, start_idx=0):
    for offset, event in enumerate(events):
        screen._sequence_event(event, start_idx + offset, HEX_SIZE, now)


class TestAttackGrouping:
    def test_ranged_damage_waits_for_projectile(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        _feed(screen, _ranged_hit(), now=1000)

        # Nothing visual yet — beats are queued, not fired
        screen._director.update(1000)
        assert [e.event_type for e, _ in screen.spawned_anims] == [
            CombatEventType.ATTACK_ROLL
        ]
        assert screen._floating_texts == []
        assert screen._flash_until == {}
        # HP bar frozen at pre-hit value while the arrow flies
        assert screen._hp_credit == {"goblin": 6}

        # Mid-flight: still nothing
        screen._director.update(1000 + PROJECTILE_TRAVEL_MS - 1)
        assert screen._floating_texts == []

        # Impact: number + flash + HP release together
        screen._director.update(1000 + PROJECTILE_TRAVEL_MS)
        assert [ft.text for ft in screen._floating_texts] == ["-6"]
        assert "goblin" in screen._flash_until
        assert screen._hp_credit == {}

    def test_melee_damage_lands_mid_swing(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        events = [
            CombatEvent(
                CombatEventType.ATTACK_ROLL, "hits",
                source_id="wolf", target_id="goblin",
                details={"animation": "bite", "attack_type": "melee_weapon"},
            ),
            CombatEvent(
                CombatEventType.DAMAGE, "damage",
                source_id="wolf", target_id="goblin",
                details={"damage": 4},
            ),
        ]
        _feed(screen, events, now=1000)
        screen._director.update(1000)
        assert screen._floating_texts == []
        screen._director.update(1000 + MELEE_IMPACT_DELAY_MS)
        assert [ft.text for ft in screen._floating_texts] == ["-4"]

    def test_short_animation_caps_melee_delay(self, monkeypatch):
        # 2 frames at 20fps = 100ms total → impact at half, not 150ms
        screen = _make_screen(monkeypatch, frames=2, fps=20)
        event = CombatEvent(
            CombatEventType.ATTACK_ROLL, "hits",
            source_id="wolf", target_id="goblin",
            details={"animation": "bite", "attack_type": "melee_weapon"},
        )
        assert screen._animation_hold_ms(event) == 50

    def test_animationless_attack_is_instant(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        events = [
            CombatEvent(
                CombatEventType.ATTACK_ROLL, "hits",
                source_id="wolf", target_id="goblin",
                details={"animation": "missing", "attack_type": "melee_weapon"},
            ),
            CombatEvent(
                CombatEventType.DAMAGE, "damage",
                source_id="wolf", target_id="goblin",
                details={"damage": 4},
            ),
        ]
        _feed(screen, events, now=1000)
        # No group opened: damage spawned immediately, no credit held
        assert [ft.text for ft in screen._floating_texts] == ["-4"]
        assert screen._hp_credit == {}
        assert not screen._director.is_busy

    def test_multiattack_swings_play_sequentially(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        batch = _ranged_hit(damage=6) + _ranged_hit(damage=8)
        _feed(screen, batch, now=1000)
        screen._director.update(1000)  # first travel beat launches
        assert screen._hp_credit == {"goblin": 14}

        # First impact: only the first number, HP partially released
        screen._director.update(1000 + PROJECTILE_TRAVEL_MS)
        assert [ft.text for ft in screen._floating_texts] == ["-6"]
        assert screen._hp_credit == {"goblin": 8}
        assert len(screen.spawned_anims) == 1

        # Second swing starts after the first impact's hold
        t_second_anim = 1000 + PROJECTILE_TRAVEL_MS + IMPACT_BEAT_MS
        screen._director.update(t_second_anim)
        assert len(screen.spawned_anims) == 2

        screen._director.update(t_second_anim + PROJECTILE_TRAVEL_MS)
        assert [ft.text for ft in screen._floating_texts] == ["-6", "-8"]
        assert screen._hp_credit == {}

    def test_crit_text_preserved(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        _feed(screen, _ranged_hit(damage=12, crit=True), now=1000)
        screen._director.update(1000)  # travel beat launches
        screen._director.update(1000 + PROJECTILE_TRAVEL_MS)
        assert [ft.text for ft in screen._floating_texts] == ["CRIT! -12"]
        assert screen._floating_texts[0].color == (255, 215, 0)

    def test_unrelated_source_damage_not_glued_to_group(self, monkeypatch):
        # Zone tick (different source) while an arrow is mid-flight
        screen = _make_screen(monkeypatch)
        _feed(screen, _ranged_hit(), now=1000)
        zone_tick = CombatEvent(
            CombatEventType.DAMAGE, "zone damage",
            source_id="zone_1", target_id="wolf",
            details={"damage": 3},
        )
        _feed(screen, [zone_tick], now=1001)
        # Spawned immediately, not deferred behind the arrow
        assert [ft.text for ft in screen._floating_texts] == ["-3"]
        assert "wolf" not in screen._hp_credit

    def test_new_animationless_attack_closes_open_group(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        _feed(screen, _ranged_hit(), now=1000)
        followup = [
            CombatEvent(
                CombatEventType.ATTACK_ROLL, "hits",
                source_id="archer", target_id="goblin",
                details={"animation": "missing", "attack_type": "melee_weapon"},
            ),
            CombatEvent(
                CombatEventType.DAMAGE, "damage",
                source_id="archer", target_id="goblin",
                details={"damage": 2},
            ),
        ]
        _feed(screen, followup, now=1001)
        # The follow-up's damage is NOT parked on the arrow's impact beat
        assert [ft.text for ft in screen._floating_texts] == ["-2"]
        assert screen._hp_credit == {"goblin": 6}

    def test_damage_after_impact_fired_spawns_instantly(self, monkeypatch):
        # Rider popup held complete_attack for seconds: the impact beat
        # already fired empty, so the late damage must not be lost.
        screen = _make_screen(monkeypatch)
        _feed(screen, _ranged_hit()[:1], now=1000)  # hit-check only
        screen._director.update(1000)  # travel beat fires
        screen._director.update(5000)  # empty impact beat fires
        screen._director.update(9000)  # its hold expires
        assert not screen._director.is_busy

        _feed(screen, _ranged_hit()[1:], now=6000)  # damage arrives late
        assert [ft.text for ft in screen._floating_texts] == ["-6"]
        assert screen._hp_credit == {}


class TestDownedHold:
    def test_token_stays_upright_until_killing_blow_lands(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        events = _ranged_hit(damage=25) + [
            CombatEvent(
                CombatEventType.CREATURE_DOWNED, "downed",
                source_id="archer", target_id="goblin",
                details={},
            ),
        ]
        _feed(screen, events, now=1000)
        screen._director.update(1000)
        assert "goblin" in screen._downed_hold

        screen._director.update(1000 + PROJECTILE_TRAVEL_MS)
        assert "goblin" not in screen._downed_hold

    def test_downed_without_pending_damage_not_held(self, monkeypatch):
        # e.g. failed death save / zone kill with no attack group open
        screen = _make_screen(monkeypatch)
        event = CombatEvent(
            CombatEventType.CREATURE_DOWNED, "downed",
            source_id=None, target_id="goblin",
            details={},
        )
        _feed(screen, [event], now=1000)
        assert screen._downed_hold == set()


class TestEffectDeferral:
    def test_same_source_effect_lands_at_impact(self, monkeypatch):
        # A cast's blast ring / shove trail rides the impact beat
        screen = _make_screen(monkeypatch)
        cast = CombatEvent(
            CombatEventType.INFO, "casts",
            source_id="archer", target_id="goblin",
            details={"animation": "firebolt", "is_effect_use": True},
        )
        push = CombatEvent(
            CombatEventType.FORCED_MOVEMENT, "pushed",
            source_id="archer", target_id="goblin",
            details={"from_hex": (4, 0), "to_hex": (5, 0)},
        )
        _feed(screen, [cast, push], now=1000)
        screen._director.update(1000)
        # Neither effect has spawned yet (cast's own ring + the push)
        assert screen.spawned_effects == []

        hold = screen._animation_hold_ms(cast)
        screen._director.update(1000 + hold)
        assert [e.event_type for e, _ in screen.spawned_effects] == [
            CombatEventType.INFO,
            CombatEventType.FORCED_MOVEMENT,
        ]

    def test_groupless_effect_spawns_immediately(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        teleport = CombatEvent(
            CombatEventType.TELEPORT, "teleports",
            source_id="archer", target_id="archer",
            details={"from_hex": (0, 0), "to_hex": (3, 3)},
        )
        _feed(screen, [teleport], now=1000)
        assert [e.event_type for e, _ in screen.spawned_effects] == [
            CombatEventType.TELEPORT
        ]


class TestLogRevealSync:
    def test_log_lines_reveal_with_their_beats(self, monkeypatch):
        # Batch: attack(0), damage(1), turn_end(2). The attack line
        # shows at the swing, damage at impact, and the trailing
        # turn-end line must not run ahead of the impact.
        screen = _make_screen(monkeypatch)
        events = _ranged_hit() + [
            CombatEvent(CombatEventType.TURN_END, "turn ends"),
        ]
        _feed(screen, events, now=1000)
        assert screen._log_reveal_index == 0

        screen._director.update(1000)  # swing launches
        assert screen._log_reveal_index == 1  # attack line only

        screen._director.update(1000 + PROJECTILE_TRAVEL_MS)  # impact
        assert screen._log_reveal_index == 3  # damage + turn-end lines

    def test_groupless_events_reveal_immediately(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        event = CombatEvent(CombatEventType.TURN_START, "turn starts")
        screen._sequence_event(event, 5, HEX_SIZE, 1000)
        assert screen._log_reveal_index == 6

    def test_reveal_is_monotonic(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        screen._reveal_log_to(10)
        screen._reveal_log_to(3)
        assert screen._log_reveal_index == 10


class TestHealing:
    def test_healing_floater_is_immediate(self, monkeypatch):
        screen = _make_screen(monkeypatch)
        heal = CombatEvent(
            CombatEventType.HEALING, "heals",
            source_id="archer", target_id="wolf",
            details={"healing": 5},
        )
        _feed(screen, [heal], now=1000)
        assert [ft.text for ft in screen._floating_texts] == ["+5"]
        assert screen._floating_texts[0].color == (60, 255, 60)
