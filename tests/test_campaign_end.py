"""Difficulty S4 — the campaign-over ritual: on a hardcore table, a total party
defeat truly ends the campaign. The DM writes the ending and the chronicle's
final entry (sealed like any wrap), a CAMPAIGN_ENDED event locks the table
permanently (it folds back on reload), and softer tables are untouched — a
lost fight there stays what it always was, a lost fight.
"""

from __future__ import annotations

import asyncio

from oubliette.combat import arena_launch
from oubliette.difficulty import DifficultySettings
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session


def _canned_defeat(pending) -> dict:
    """A lost fight: every player combatant downed, the enemy left standing."""
    combatants = []
    for c in pending.plan.encounter.combatants:
        cd = c.creature_data
        enemy = c.team == "enemy"
        combatants.append({
            "id": c.name_override, "name": c.name_override, "team": c.team,
            "is_pc": c.team == "player",
            "hp": cd.max_hit_points if enemy else 0,
            "max_hp": cd.max_hit_points, "temp_hp": 0, "conditions": [],
            "is_conscious": enemy, "xp": 0,
        })
    return {"schema": 1, "winner": "enemy", "outcome": "defeat",
            "rounds": 2, "combatants": combatants}


def _lost_fight(preset: str, monkeypatch):
    """Play one fight to defeat on a table at `preset`; return (session, report)."""
    session = Session.open(InMemoryEventStore())
    session.emit_difficulty(DifficultySettings(preset=preset), reason="test")
    loop = TurnLoop(session, Rng(seed=1234, record=session.emit_log),
                    Brain(ScriptedLLMClient()))
    monkeypatch.setattr(arena_launch, "run_arena", _canned_defeat)
    asyncio.run(loop.take_turn("I draw my knife and attack the raiders."))
    report = asyncio.run(loop.enter_combat())
    return session, report


def test_hardcore_tpk_ends_the_campaign_for_good(monkeypatch):
    session, report = _lost_fight("hardcore", monkeypatch)

    assert report.session_force_ended is True
    assert "[scripted ending]" in report.narration       # the DM's goodbye reached the player
    assert session.campaign_ended is True and session.force_ended is True

    events = session.store.read_all()
    kinds = [e.kind for e in events]
    assert EventKind.CAMPAIGN_ENDED.value in kinds
    ended = next(e for e in events if e.kind == EventKind.CAMPAIGN_ENDED.value)
    assert ended.payload["cause"] == "tpk" and ended.payload["narration"]
    # The final notes sealed like any wrap, just before the terminal event.
    wraps = [e for e in events if e.kind == EventKind.SESSION_MARKER.value
             and e.payload.get("marker") == "wrap"]
    assert wraps and "[scripted chronicle]" in wraps[-1].payload["player_facing"]

    # The end is permanent: reloading the save folds the lock back.
    reopened = Session.open(session.store)
    assert reopened.campaign_ended is True and reopened.force_ended is True


def test_a_lost_fight_on_a_softer_table_is_just_a_lost_fight(monkeypatch):
    session, report = _lost_fight("adventure", monkeypatch)
    assert report.session_force_ended is False
    assert session.campaign_ended is False and session.force_ended is False
    assert not any(e.kind == EventKind.CAMPAIGN_ENDED.value
                   for e in session.store.read_all())


def test_a_hardcore_victory_ends_nothing(monkeypatch):
    session = Session.open(InMemoryEventStore())
    session.emit_difficulty(DifficultySettings(preset="hardcore"), reason="test")
    loop = TurnLoop(session, Rng(seed=1234, record=session.emit_log),
                    Brain(ScriptedLLMClient()))

    def _canned_victory(pending):
        combatants = []
        for c in pending.plan.encounter.combatants:
            cd = c.creature_data
            enemy = c.team == "enemy"
            combatants.append({
                "id": c.name_override, "name": c.name_override, "team": c.team,
                "is_pc": c.team == "player",
                "hp": 0 if enemy else max(1, cd.max_hit_points - 3),
                "max_hp": cd.max_hit_points, "temp_hp": 0, "conditions": [],
                "is_conscious": not enemy,
                "xp": int(getattr(cd, "experience_points", 0) or 0),
            })
        return {"schema": 1, "winner": "player", "outcome": "victory",
                "rounds": 2, "combatants": combatants}

    monkeypatch.setattr(arena_launch, "run_arena", _canned_victory)
    asyncio.run(loop.take_turn("I draw my knife and attack the raiders."))
    report = asyncio.run(loop.enter_combat())
    assert report.session_force_ended is False
    assert session.campaign_ended is False
