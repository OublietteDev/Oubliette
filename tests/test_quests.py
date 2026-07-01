"""Emergent quest tracking: the DM starts/advances/closes quests; code owns the
state and event-sources it (so a reload rebuilds quests exactly). Simple shape — a
goal with a status + running notes; rewards stay ordinary give/transact tools.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.dm.context import build_context
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.quest.models import Quest
from oubliette.quest.store import QuestStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.state.models import Character
from oubliette.state.repository import InMemoryRepository
from oubliette.tools.dispatch import Dispatcher, ToolApplyError
from oubliette.tools.schemas import StartQuest, UpdateQuest

import pytest


# --- store ------------------------------------------------------------------
def test_quest_store_status_notes_and_active():
    qs = QuestStore()
    q = Quest(id=qs.next_id(), title="Find the cat")     # quest-0
    qs.add(q)
    assert qs.next_id() == "quest-1"                      # counter advanced
    qs.update("quest-0", note="found a paw print")
    qs.update("quest-0", status="completed", note="cat in hand")
    done = qs.get("quest-0")
    assert done.status == "completed" and done.notes == ["found a paw print", "cat in hand"]
    assert qs.active() == []                              # completed isn't active


# --- dispatcher -------------------------------------------------------------
def test_dispatcher_starts_and_updates_quests():
    qs = QuestStore()
    qs.add(Quest(id="quest-0", title="An errand", status="completed"))  # not active → won't block a new start
    disp = Dispatcher(None, None, None, qs)

    started = disp.resolve(StartQuest(title="A new goal", text="do the thing", reason="r"))
    assert started.quest_start.title == "A new goal"

    updated = disp.resolve(UpdateQuest(quest_id="quest-0", status="completed", reason="r"))
    assert updated.quest_update.status == "completed"

    with pytest.raises(ToolApplyError):
        disp.resolve(UpdateQuest(quest_id="quest-999", note="nope", reason="r"))


def test_only_one_active_quest_at_a_time():
    qs = QuestStore()
    qs.add(Quest(id="quest-0", title="The current job", status="active"))
    disp = Dispatcher(None, None, None, qs)
    with pytest.raises(ToolApplyError):
        disp.resolve(StartQuest(title="A second job", reason="r"))   # already one active
    # once it's done, a new one is allowed
    qs.update("quest-0", status="completed")
    assert disp.resolve(StartQuest(title="A second job", reason="r")).quest_start is not None


# --- session + replay -------------------------------------------------------
def test_quests_rebuild_byte_identical_on_reload(tmp_path):
    db = str(tmp_path / "quests.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    q = s.emit_quest_start("Find the captain", "Locate Bromley at the docks.", "intro")
    s.emit_quest_update(q.id, note="asked around the market")
    s.emit_quest_update(q.id, status="completed", note="found him aboard his boat")
    store.close()

    reloaded = Session.open(SqliteEventStore(db))
    rq = reloaded.quests.get(q.id)
    assert rq is not None
    assert rq.title == "Find the captain" and rq.status == "completed"
    assert rq.notes == ["asked around the market", "found him aboard his boat"]


# --- end-to-end through the loop (scripted) ---------------------------------
def test_scripted_quest_lifecycle():
    s = Session.open(InMemoryEventStore())
    loop = TurnLoop(s, Rng(1, record=s.emit_log), Brain(ScriptedLLMClient()))

    asyncio.run(loop.take_turn("I accept the task."))
    quests = s.quests.all()
    assert len(quests) == 1 and quests[0].id == "quest-0" and quests[0].status == "active"

    asyncio.run(loop.take_turn("Good news — the job is done."))
    assert s.quests.get("quest-0").status == "completed"
    assert s.quests.active() == []


# --- context ----------------------------------------------------------------
def test_active_quests_appear_in_context():
    repo = InMemoryRepository([Character(id="pc", name="You", kind="pc")], [], "pc")
    q = Quest(id="quest-0", title="Find the captain", text="Locate Bromley.",
              notes=["asked at the docks"])
    ctx = build_context(repo, "scene", quests=[q])
    assert "ACTIVE QUESTS" in ctx
    assert "Find the captain" in ctx and "quest-0" in ctx
    assert "asked at the docks" in ctx          # the latest note is surfaced


# --- keep-until-paid: a reward stays in view until the DM settles it ---------
def test_reward_pending_tracks_completed_unsettled_quests():
    qs = QuestStore()
    qs.add(Quest(id="quest-0", title="Slay the wolf", status="active"))
    assert qs.reward_pending() == []                    # active → nothing owed yet
    qs.update("quest-0", status="completed")
    assert [q.id for q in qs.reward_pending()] == ["quest-0"]   # done but unpaid
    qs.update("quest-0", reward_settled=True)
    assert qs.reward_pending() == []                    # settled → cleared
    qs.add(Quest(id="quest-1", title="A doomed errand", status="failed"))
    assert qs.reward_pending() == []                    # a failed quest owes nothing


def test_dispatcher_passes_reward_settled():
    qs = QuestStore()
    qs.add(Quest(id="quest-0", title="A job", status="completed"))
    disp = Dispatcher(None, None, None, qs)
    updated = disp.resolve(UpdateQuest(quest_id="quest-0", reward_settled=True, reason="paid"))
    assert updated.quest_update.reward_settled is True


def test_reward_settled_survives_reload(tmp_path):
    db = str(tmp_path / "reward.sqlite")
    store = SqliteEventStore(db)
    s = Session.open(store)
    q = s.emit_quest_start("Deliver the letter", "Take it to the governor.", "intro")
    s.emit_quest_update(q.id, status="completed", note="delivered")
    assert [x.id for x in s.quests.reward_pending()] == [q.id]
    s.emit_quest_update(q.id, reward_settled=True, reason="paid 50g")
    assert s.quests.reward_pending() == []
    store.close()

    reloaded = Session.open(SqliteEventStore(db))
    assert reloaded.quests.get(q.id).reward_settled is True
    assert reloaded.quests.reward_pending() == []       # settled state rebuilds on reload


def test_completed_quest_reward_stays_in_context_until_settled():
    # The bug this fixes: a promised reward must not vanish from the DM's view the
    # moment a quest completes — deferred or renegotiated payouts need it to persist.
    repo = InMemoryRepository([Character(id="pc", name="You", kind="pc")], [], "pc")
    q = Quest(id="quest-0", title="Recover the heirloom",
              text="Bring back the locket.", status="completed",
              notes=["locket recovered — she still owes the promised 200g"])
    ctx = build_context(repo, "scene", quests=[], pending_rewards=[q])
    assert "REWARDS PENDING" in ctx
    assert "quest-0" in ctx and "Recover the heirloom" in ctx
    assert "200g" in ctx                                # the promised reward is still visible
    # once the DM settles it, nothing lingers
    assert "REWARDS PENDING" not in build_context(repo, "scene", quests=[], pending_rewards=[])
