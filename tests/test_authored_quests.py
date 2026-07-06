"""Authored quests: pack-defined quests offered during play (designed in The Forge).

This module grows with the feature; Phase 1 covers the authoring SCHEMAS + validators
(content/schemas.py). Later phases add loader/linter, the accept_quest runtime, branching
replay-stability (quest/offers.py), and the two-tier DM context surfacing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from oubliette.content.loader import PackValidationError, load_pack
from oubliette.content.schemas import AuthoredQuest, QuestBranch, QuestReward


# --- AuthoredQuest source rules ---------------------------------------------
def test_npc_giver_quest_is_valid():
    q = AuthoredQuest(id="q1", title="A Favor", hook="help me", giver_npc="bromley")
    assert q.giver_npc == "bromley" and q.giver_place is None


def test_place_giver_quest_needs_a_discovery_note():
    ok = AuthoredQuest(id="q1", title="Bounty", giver_place="coin_quarter",
                       discovery="a notice board")
    assert ok.giver_place == "coin_quarter"
    with pytest.raises(ValidationError):
        AuthoredQuest(id="q1", title="Bounty", giver_place="coin_quarter")  # no discovery


def test_exactly_one_source_required():
    with pytest.raises(ValidationError):                       # both
        AuthoredQuest(id="q1", title="X", giver_npc="b", giver_place="p", discovery="board")
    with pytest.raises(ValidationError):                       # neither
        AuthoredQuest(id="q1", title="X")


def test_discovery_only_for_place_givers():
    with pytest.raises(ValidationError):
        AuthoredQuest(id="q1", title="X", giver_npc="bromley", discovery="a board")


# --- QuestReward shape ------------------------------------------------------
def test_reward_at_most_one_of_gold_item():
    assert QuestReward(gold=50).gold == 50
    assert QuestReward(item="healing_potion", qty=2).item == "healing_potion"
    assert QuestReward(note="the captain's gratitude").note            # note-only is fine
    with pytest.raises(ValidationError):
        QuestReward(gold=50, item="potion")                            # both
    with pytest.raises(ValidationError):
        QuestReward()                                                  # nothing at all
    with pytest.raises(ValidationError):
        QuestReward(gold=0)                                            # non-positive


# --- level gate (difficulty S2) ---------------------------------------------
def test_min_party_level_hides_a_quest_until_the_party_qualifies():
    from oubliette.quest.store import QuestStore

    authored = {
        "easy": AuthoredQuest(id="easy", title="Rats in the Cellar", hook="clear them",
                              giver_npc="innkeep", root=True),
        "hard": AuthoredQuest(id="hard", title="The Lich's Vault", hook="dare it",
                              giver_npc="sage", root=True, min_party_level=5),
    }
    events, quests = [], QuestStore()

    # A level-1 party sees only the ungated quest — the gated one is invisible.
    assert offers.offerable_ids(authored, events, quests, party_level=1) == {"easy"}
    # Still hidden just below the threshold...
    assert offers.offerable_ids(authored, events, quests, party_level=4) == {"easy"}
    # ...and it opens exactly at the gate.
    assert offers.offerable_ids(authored, events, quests, party_level=5) == {"easy", "hard"}
    # Default party_level (1) keeps a gated quest hidden — safe for any caller.
    assert offers.offerable_ids(authored, events, quests) == {"easy"}


def test_min_party_level_defaults_to_no_gate():
    q = AuthoredQuest(id="q1", title="A Favor", hook="help", giver_npc="bromley")
    assert q.min_party_level is None


# --- chains / branches assemble ---------------------------------------------
def test_branching_quest_assembles():
    q = AuthoredQuest(
        id="q1", title="The Bandit", hook="deal with the bandit", giver_npc="reeve",
        root=True, chain="kings_road",
        branches=[QuestBranch(outcome="spared", to="q2"),
                  QuestBranch(outcome="killed", to="q3")],
        reward=QuestReward(gold=40, note="and the reeve's thanks"))
    assert {b.outcome for b in q.branches} == {"spared", "killed"}
    assert q.root and q.reward.gold == 40


# --- loader + cross-reference linter ----------------------------------------
def _pack_with_quests(quests: list) -> dict:
    """A small valid pack (town > dock/market; Bromley lives at the dock) plus a
    quests.json the test supplies. Tests mutate `quests` to exercise linter rules."""
    return {
        "pack.json": {"id": "t", "schema_version": 1, "name": "Test", "version": "1.0.0",
                      "entry_scenario": "s"},
        "items.json": [{"id": "potion", "name": "potion", "category": "consumable"}],
        "statblocks.json": [],
        "npcs.json": [{"id": "bromley", "name": "Bromley", "home_location": "dock"},
                      {"id": "drifter", "name": "Drifter"}],   # no home_location
        "places.json": [
            {"id": "town", "name": "Town", "description": "a town", "exits": []},
            {"id": "dock", "name": "Dock", "description": "the dock", "parent": "town", "exits": []},
            {"id": "market", "name": "Market", "description": "the market", "parent": "town", "exits": []},
            {"id": "wilds", "name": "Wilds", "description": "the wilds", "exits": []},      # 2nd region
            {"id": "cave", "name": "Cave", "description": "a cave", "parent": "wilds", "exits": []},
        ],
        "scenarios.json": [{"id": "s", "name": "S", "start_location": "town",
                            "party_source": "default",
                            "default_party": [{"id": "pc", "name": "PC", "kind": "pc"}]}],
        "quests.json": quests,
    }


def _write_pack(root: Path, files: dict) -> Path:
    d = root / "t"
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(json.dumps(content), encoding="utf-8")
    return root


def _load_quests(tmp_path, quests):
    return load_pack("t", packs_root=_write_pack(tmp_path, _pack_with_quests(quests)))


def _expect_error(tmp_path, quests, needle):
    with pytest.raises(PackValidationError) as exc:
        _load_quests(tmp_path, quests)
    assert any(needle in e for e in exc.value.errors), exc.value.errors


def test_valid_branching_chain_loads(tmp_path):
    world = _load_quests(tmp_path, [
        {"id": "q1", "title": "Missing Cargo", "hook": "find the cargo", "giver_npc": "bromley",
         "root": True, "branches": [{"outcome": "recovered", "to": "q2"}],
         "reward": {"item": "potion", "qty": 1}},
        {"id": "q2", "title": "The Smuggler", "hook": "confront them",
         "giver_place": "market", "discovery": "a notice board"},
    ])
    assert {q.id for q in world.quests} == {"q1", "q2"}


def test_quest_unknown_giver_npc(tmp_path):
    _expect_error(tmp_path, [{"id": "q1", "title": "X", "giver_npc": "ghost", "root": True}],
                  "unknown npc 'ghost'")


def test_quest_giver_without_home_is_rejected(tmp_path):
    _expect_error(tmp_path, [{"id": "q1", "title": "X", "giver_npc": "drifter", "root": True}],
                  "no home_location")


def test_quest_unknown_place_and_reward_item(tmp_path):
    _expect_error(tmp_path, [{"id": "q1", "title": "X", "giver_place": "void",
                              "discovery": "a board", "root": True}], "unknown place 'void'")
    _expect_error(tmp_path, [{"id": "q1", "title": "X", "giver_npc": "bromley", "root": True,
                              "reward": {"item": "nonexistent"}}], "unknown item 'nonexistent'")


def test_quest_branch_to_unknown(tmp_path):
    _expect_error(tmp_path, [{"id": "q1", "title": "X", "giver_npc": "bromley", "root": True,
                              "branches": [{"outcome": "o", "to": "q9"}]}],
                  "unknown quest 'q9'")


def test_quest_self_branch(tmp_path):
    _expect_error(tmp_path, [{"id": "q1", "title": "X", "giver_npc": "bromley", "root": True,
                              "branches": [{"outcome": "loop", "to": "q1"}]}],
                  "branches to itself")


def test_quest_unreachable_node(tmp_path):
    # q2 is neither a root nor unlocked by any branch → unreachable.
    _expect_error(tmp_path, [
        {"id": "q1", "title": "X", "giver_npc": "bromley", "root": True},
        {"id": "q2", "title": "Orphan", "giver_place": "market", "discovery": "a board"},
    ], "unreachable")


def test_missing_quests_file_is_fine(tmp_path):
    files = _pack_with_quests([])
    del files["quests.json"]                      # absent → empty, world still loads
    world = load_pack("t", packs_root=_write_pack(tmp_path, files))
    assert world.quests == ()


# --- runtime: offers, accept_quest, branching, replay -----------------------
from oubliette.dm.context import build_context                             # noqa: E402
from oubliette.quest import offers                                          # noqa: E402
from oubliette.record.store import InMemoryEventStore                       # noqa: E402
from oubliette.runtime.session import Session                              # noqa: E402
from oubliette.tools.dispatch import Dispatcher, ToolApplyError            # noqa: E402
from oubliette.tools.schemas import AcceptQuest                            # noqa: E402

# A 3-node branching chain: Bromley (at the dock) offers q1; "spared" → q2 (at the
# market), "killed" → q3 (back to Bromley).
_CHAIN = [
    {"id": "q1", "title": "Missing Cargo", "hook": "find the cargo", "giver_npc": "bromley",
     "rumor": "dockworkers grumble about missing cargo",
     "briefing": "the harbormaster is the real thief", "root": True,
     "branches": [{"outcome": "spared", "to": "q2"}, {"outcome": "killed", "to": "q3"}]},
    {"id": "q2", "title": "The Fence", "hook": "track the goods",
     "giver_place": "market", "discovery": "a notice board"},
    {"id": "q3", "title": "The Reckoning", "hook": "answer for it", "giver_npc": "bromley"},
]


def _session(tmp_path, monkeypatch, quests, store=None):
    from oubliette.content import loader as loader_mod
    _write_pack(tmp_path, _pack_with_quests(quests))
    monkeypatch.setattr(loader_mod, "_PACKS_ROOT", tmp_path)
    return Session.open(store or InMemoryEventStore(), pack_id="t")


def _eligible(session):
    return offers.offerable_ids(session.authored_quests, session.store.read_all(), session.quests)


def test_root_quest_offered_only_at_its_source(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    assert _eligible(s) == {"q1"}                      # root, chain-eligible
    # at the town (Bromley not present) it's eligible but not offered HERE
    present_town = {n.id for n in s.repo.npcs() if n.home_location == s.location}
    assert offers.offered_here(_eligible(s), s.authored_quests, s.location, present_town) == set()
    # at the dock, Bromley is present → it's offerable here
    s.location = "dock"
    present_dock = {n.id for n in s.repo.npcs() if n.home_location == "dock"}
    assert offers.offered_here(_eligible(s), s.authored_quests, "dock", present_dock) == {"q1"}


def test_accept_seeds_runtime_quest_linked_to_authored(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    q = s.emit_quest_accept(s.authored_quests["q1"], "the party agrees")
    assert q.authored_id == "q1" and q.title == "Missing Cargo" and q.status == "active"
    assert s.quests.active()[0].authored_id == "q1"
    assert _eligible(s) == set()                       # started → no longer offerable


def test_dispatcher_gates_accept(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    disp = Dispatcher(s.repo, s.canon, s.places, s.quests, authored_quests=s.authored_quests)
    disp.offered_here = {"q1"}
    with pytest.raises(ToolApplyError):                                  # unknown id
        disp.resolve(AcceptQuest(quest_id="ghost", reason="r"))
    disp.offered_here = set()
    with pytest.raises(ToolApplyError):                                  # not offered here
        disp.resolve(AcceptQuest(quest_id="q1", reason="r"))
    disp.offered_here = {"q1"}
    assert disp.resolve(AcceptQuest(quest_id="q1", reason="r")).quest_accept is not None
    # once one is active, a second accept is refused
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    disp.offered_here = {"q3"}
    with pytest.raises(ToolApplyError):
        disp.resolve(AcceptQuest(quest_id="q3", reason="r"))


def test_branch_outcome_unlocks_next_node(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    qid = s.quests.active()[0].id
    s.emit_quest_update(qid, status="completed", outcome="spared", reason="r")
    assert _eligible(s) == {"q2"}                      # spared → q2 only (q3 stays locked)


def test_failed_quest_does_not_unlock_or_re_offer(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    qid = s.quests.active()[0].id
    s.emit_quest_update(qid, status="failed", reason="r")
    assert _eligible(s) == set()                       # q1 started (failed) ≠ re-offer; nothing unlocked


def test_offer_set_is_byte_identical_on_reload(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    s.emit_quest_update(s.quests.active()[0].id, status="completed", outcome="killed", reason="r")
    before = _eligible(s)
    assert before == {"q3"}
    reloaded = Session.open(s.store, pack_id="t")      # same log, fresh replay
    assert _eligible(reloaded) == before


# --- two-tier context surfacing ---------------------------------------------
def _ctx(session, location):
    session.location = location
    authored = session.authored_quests
    eligible = offers.offerable_ids(authored, session.store.read_all(), session.quests)
    present = {n.id for n in session.repo.npcs() if n.home_location == location}
    here = offers.offered_here(eligible, authored, location, present)
    return build_context(session.repo, location=location, places=session.places,
                         authored_quests=authored, offerable=eligible, offered_here=here)


def test_at_source_shows_full_offer_with_secret_briefing(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    ctx = _ctx(s, "dock")                              # Bromley is here
    assert "QUESTS OFFERED HERE" in ctx
    assert "Missing Cargo" in ctx and "find the cargo" in ctx       # title + hook
    assert "harbormaster" in ctx                                    # the DM-only briefing
    assert "spared" in ctx and "killed" in ctx                      # branch outcomes
    assert "WORK AVAILABLE IN THE REGION" not in ctx                # it's offered here, not afar


def test_in_region_signpost_leaks_no_details(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, _CHAIN)
    ctx = _ctx(s, "market")                            # same town, Bromley NOT present
    assert "QUESTS OFFERED HERE" not in ctx
    assert "WORK AVAILABLE IN THE REGION" in ctx
    assert "Dock" in ctx and "dockworkers grumble about missing cargo" in ctx   # location + rumor
    assert "find the cargo" not in ctx                 # the hook is NOT leaked at range
    assert "harbormaster" not in ctx                   # nor the secret briefing


def test_region_awareness_does_not_cross_regions(tmp_path, monkeypatch):
    quests = [
        {"id": "qa", "title": "Market Job", "hook": "h", "giver_place": "market",
         "discovery": "a board", "root": True, "rumor": "market rumor"},
        {"id": "qb", "title": "Cave Job", "hook": "h", "giver_place": "cave",
         "discovery": "a carving", "root": True, "rumor": "cave rumor"},
    ]
    s = _session(tmp_path, monkeypatch, quests)
    ctx = _ctx(s, "dock")                              # region = Town
    assert "market rumor" in ctx                       # Market is in this town
    assert "cave rumor" not in ctx and "Cave Job" not in ctx        # the Wilds are a different region


# --- chain robustness + post-acceptance context (regression: playtest 2026-06-17) ---
def test_single_branch_step_advances_without_an_outcome(tmp_path, monkeypatch):
    """A linear step (one branch) must advance on completion even when the DM omits the
    outcome — a one-path step shouldn't require an artificial label (the bug that stalled
    'The Empty Nets' → 'Salt and Suspicion' in playtesting)."""
    quests = [
        {"id": "q1", "title": "Step One", "giver_npc": "bromley", "root": True,
         "branches": [{"outcome": "onward", "to": "q2"}]},
        {"id": "q2", "title": "Step Two", "giver_place": "market", "discovery": "a board"},
    ]
    s = _session(tmp_path, monkeypatch, quests)
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    s.emit_quest_update(s.quests.active()[0].id, status="completed", outcome=None, reason="r")
    assert _eligible(s) == {"q2"}                      # advanced with no outcome supplied


def test_fork_still_requires_the_matching_outcome(tmp_path, monkeypatch):
    """A genuine fork (>1 branch) must NOT auto-advance — completing with no outcome
    unlocks nothing (the DM has to report which way it went)."""
    s = _session(tmp_path, monkeypatch, _CHAIN)        # q1 forks spared/killed
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    s.emit_quest_update(s.quests.active()[0].id, status="completed", outcome=None, reason="r")
    assert _eligible(s) == set()


def test_active_authored_quest_retains_briefing_and_reward(tmp_path, monkeypatch):
    """Once accepted, an authored quest keeps its secret briefing + intended reward in the
    DM's context for the quest's whole life — not just while it was on offer."""
    chain = [{"id": "q1", "title": "The Job", "hook": "do it", "briefing": "the secret truth",
              "giver_npc": "bromley", "root": True, "reward": {"gold": 30, "note": "a favor owed"}}]
    s = _session(tmp_path, monkeypatch, chain)
    s.emit_quest_accept(s.authored_quests["q1"], "r")
    ctx = build_context(s.repo, location="dock", places=s.places,
                        authored_quests=s.authored_quests, offerable=set(), offered_here=set(),
                        quests=s.quests.active())
    assert "ACTIVE QUESTS" in ctx
    assert "the secret truth" in ctx                   # briefing retained
    assert "30 gp" in ctx and "favor owed" in ctx      # intended reward retained
