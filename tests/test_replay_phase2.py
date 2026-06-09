"""Phase 2 acceptance — the replay contract (spec §4.2, D9).

Play a session to a real SQLite file, then reload it from scratch (seed the
authored baseline + replay the log) and prove the rebuilt authoritative state is
byte-identical. Replay never rolls and never calls a model — it only re-applies
the recorded ops.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from oubliette.combat import arena_launch
from oubliette.dm.brain import Brain
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind, replay
from oubliette.record.rng import Rng
from oubliette.record.store import SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.seed import seed_world
from oubliette.state.repository import Repository

TRANSCRIPT = [
    "I look around the market.",
    "I tell the merchant these worn boots are priceless dwarven heirlooms.",
    "Sold.",
    "I draw my knife and attack the bandit.",
]


def _snapshot(repo: Repository) -> str:
    """Deterministic JSON of the mutable protected state we care about."""
    out = {}
    for cid in ("pc", "merchant_thom"):
        c = repo.get_character(cid)
        out[cid] = {
            "gold": c.gold, "hp": c.hp, "xp": c.xp,
            "conditions": sorted(c.conditions),
            "inventory": sorted((s.item_id, s.qty) for s in c.inventory),
        }
    return json.dumps(out, sort_keys=True)


def _canned_victory(pending) -> dict:
    """Deterministic Arena result for the staged bandit fight: enemy down, PC up.
    Combat now stages (Stage 3) and is played in The Arena; here we stand in for
    that subprocess so the COMBAT_RESULT is recorded for the replay contract."""
    combatants = []
    for c in pending.plan.encounter.combatants:
        cd = c.creature_data
        enemy = c.team == "enemy"
        combatants.append({
            "id": c.name_override, "name": c.name_override, "team": c.team,
            "is_pc": c.team == "player",
            "hp": 0 if enemy else max(1, cd.max_hit_points - 4),
            "max_hp": cd.max_hit_points, "temp_hp": 0, "conditions": [],
            "is_conscious": not enemy,
            "xp": int(getattr(cd, "experience_points", 0) or 0),
        })
    return {"schema": 1, "winner": "player", "outcome": "victory",
            "rounds": 2, "combatants": combatants}


def _play(loop):
    for line in TRANSCRIPT:
        asyncio.run(loop.take_turn(line))
    # The closing line stages a fight; play it out (mocked Arena) so its single
    # COMBAT_RESULT lands in the log and replay can reproduce it.
    if loop.session.pending_combat is not None:
        with patch.object(arena_launch, "run_arena", _canned_victory):
            asyncio.run(loop.enter_combat())


def test_reload_rebuilds_byte_identical_state(tmp_path):
    db = str(tmp_path / "session.sqlite")

    # --- live session: play to a real SQLite-backed log ---
    store = SqliteEventStore(db)
    session = Session.open(store)
    rng = Rng(seed=1234, record=session.emit_log)
    _play(TurnLoop(session, rng, Brain(ScriptedLLMClient())))

    live_snapshot = _snapshot(session.repo)
    # sanity: the transcript actually moved state
    assert "265" in live_snapshot or '"gold": 273' in live_snapshot
    n_rolls = len(store.of_kind(EventKind.ROLL))
    assert n_rolls > 0
    assert len(store.of_kind(EventKind.TOOL_APPLIED)) == 1
    assert len(store.of_kind(EventKind.COMBAT_RESULT)) == 1
    store.close()

    # --- reload from disk: seed baseline + replay → must match byte-for-byte ---
    store2 = SqliteEventStore(db)
    reloaded = Session.open(store2)
    assert _snapshot(reloaded.repo) == live_snapshot

    # replay is deterministic and idempotent: do it again into a fresh repo
    repo3 = seed_world()
    replay(store2.read_all(), repo3)
    assert _snapshot(repo3) == live_snapshot

    # the log persisted intact across the reload (nothing lost, nothing re-rolled)
    assert len(store2.of_kind(EventKind.ROLL)) == n_rolls
    store2.close()


def test_replay_skips_rolls_for_state(tmp_path):
    """ROLL events are history, not state: stripping them from the log leaves the
    rebuilt protected state unchanged (rolls never mutate protected state)."""
    db = str(tmp_path / "s.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    rng = Rng(seed=1234, record=session.emit_log)
    _play(TurnLoop(session, rng, Brain(ScriptedLLMClient())))
    full = _snapshot(session.repo)

    events_without_rolls = [e for e in store.read_all() if e.kind != EventKind.ROLL.value]
    repo = seed_world()
    replay(events_without_rolls, repo)
    assert _snapshot(repo) == full
    store.close()
