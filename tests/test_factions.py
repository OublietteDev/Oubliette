"""Living-world W2 — factions: a code-owned standing score per faction, spoken
in five tiers, that the LLM never holds.

The contract: standing is a pure derivation (authored default + quest deltas
read from the quest log + the DM's bounded adjust_standing nudges), replay-safe
byte-for-byte; discovery is derivable (known_from_start, any standing event,
or an earned quest delta); min_standing hides quests like min_party_level; the
DM tool clamps to ±5 and rejects unknown factions; the player endpoint redacts
unknown factions to bare rows and ships tier WORDS, never scores.
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "factions.sqlite"))
os.environ.pop("ANTHROPIC_API_KEY", None)   # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import app  # noqa: E402
from oubliette.content.loader import _lint_factions, load_pack  # noqa: E402
from oubliette.content.schemas import (  # noqa: E402
    NPC,
    AuthoredQuest,
    Faction,
    MinStanding,
    QuestStanding,
    StatBlock,
)
from oubliette.dm.brain import Brain  # noqa: E402
from oubliette.dm.context import build_context  # noqa: E402
from oubliette.llm.scripted import ScriptedLLMClient  # noqa: E402
from oubliette.record.events import EventKind  # noqa: E402
from oubliette.record.rng import Rng  # noqa: E402
from oubliette.record.store import InMemoryEventStore  # noqa: E402
from oubliette.runtime.loop import TurnLoop  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402
from oubliette.tools.dispatch import Dispatcher, ToolApplyError  # noqa: E402
from oubliette.tools.schemas import AdjustStanding  # noqa: E402
from oubliette.world.factions import (  # noqa: E402
    clamp_dm_delta,
    filter_offerable,
    known_ids,
    standing_map,
    tier_at_least,
    tier_for,
)

client = TestClient(app)


def _faction(fid="watch", default=0, known=False):
    return Faction(id=fid, name=fid.title(), default_standing=default,
                   known_from_start=known)


def _quest(qid="patrol", giver="maren", standing=(), min_standing=None, branches=()):
    return AuthoredQuest(id=qid, title=qid.title(), giver_npc=giver, root=True,
                         standing=list(standing), min_standing=min_standing,
                         branches=list(branches))


def _session() -> Session:
    return Session.open(InMemoryEventStore())


def _nudge(s, faction, delta, reason="test"):
    s.emit_log(EventKind.FACTION_STANDING_CHANGED,
               faction=faction, delta=delta, reason=reason)


# --- tiers ---------------------------------------------------------------------

def test_tiers_and_ordering():
    assert tier_for(-50) == "hostile" and tier_for(-31) == "hostile"
    assert tier_for(-30) == "unfriendly" and tier_for(-10) == "neutral"
    assert tier_for(0) == "neutral" and tier_for(10) == "friendly"
    assert tier_for(30) == "allied" and tier_for(50) == "allied"
    assert tier_at_least("friendly", "neutral")
    assert not tier_at_least("neutral", "friendly")
    assert not tier_at_least("nonsense", "neutral")


def test_dm_delta_clamps():
    assert clamp_dm_delta(3) == 3 and clamp_dm_delta(0) == 0
    assert clamp_dm_delta(40) == 5 and clamp_dm_delta(-40) == -5


# --- the derivation --------------------------------------------------------------

def test_standing_sums_default_quests_and_nudges():
    s = _session()
    factions = {"watch": _faction("watch")}
    quest = _quest(standing=[QuestStanding(faction="watch", delta=20, when="accepted")])
    authored = {"patrol": quest}
    assert standing_map(factions, authored, s.store.read_all(), s.quests) == {"watch": 0}
    s.emit_quest_accept(quest, "took the patrol job")
    _nudge(s, "watch", 5)
    _nudge(s, "watch", -2)
    assert standing_map(factions, authored, s.store.read_all(), s.quests) == {"watch": 23}


def test_completion_delta_respects_the_outcome_filter():
    s = _session()
    factions = {"watch": _faction(), "hand": _faction("hand")}
    quest = AuthoredQuest(
        id="smuggler", title="The Smuggler", giver_npc="maren", root=True,
        branches=[{"outcome": "spared", "to": "next_a"}, {"outcome": "hanged", "to": "next_b"}],
        standing=[QuestStanding(faction="watch", delta=15, outcome="hanged"),
                  QuestStanding(faction="hand", delta=-20, outcome="hanged"),
                  QuestStanding(faction="hand", delta=10, outcome="spared")])
    authored = {"smuggler": quest}
    s.emit_quest_accept(quest, "on the trail")
    q = s.quests.active()[0]
    s.emit_quest_update(q.id, status="completed", outcome="spared", reason="mercy")
    scores = standing_map(factions, authored, s.store.read_all(), s.quests)
    assert scores == {"watch": 0, "hand": 10}      # only the 'spared' delta landed


def test_scores_clamp_to_the_range():
    s = _session()
    factions = {"watch": _faction(default=45)}
    for _ in range(4):
        _nudge(s, "watch", 5)
    assert standing_map(factions, {}, s.store.read_all(), s.quests) == {"watch": 50}


# --- discovery -------------------------------------------------------------------

def test_known_from_start_reveal_and_earned_delta():
    s = _session()
    factions = {"watch": _faction("watch", known=True),
                "hand": _faction("hand"),
                "cult": _faction("cult")}
    quest = _quest(standing=[QuestStanding(faction="hand", delta=10, when="accepted")])
    authored = {"patrol": quest}
    assert known_ids(factions, authored, s.store.read_all(), s.quests) == {"watch"}
    s.emit_quest_accept(quest, "hired by a stranger")      # earning standing reveals
    _nudge(s, "cult", 0, reason="their sigil is recognized")   # the delta-0 reveal
    assert known_ids(factions, authored, s.store.read_all(), s.quests) == {
        "watch", "hand", "cult"}


# --- the offer gate ---------------------------------------------------------------

def test_min_standing_hides_and_reveals_quests():
    gated = _quest("inner_circle",
                   min_standing=MinStanding(faction="watch", tier="friendly"))
    open_q = _quest("errand")
    authored = {"inner_circle": gated, "errand": open_q}
    eligible = {"inner_circle", "errand"}
    assert filter_offerable(eligible, authored, {"watch": "neutral"}) == {"errand"}
    assert filter_offerable(eligible, authored, {"watch": "friendly"}) == eligible
    # A gate on a faction with no computed tier (ripped-out module) stays closed
    # rather than crashing — modularity contract.
    assert filter_offerable(eligible, authored, {}) == {"errand"}


# --- the DM tool -------------------------------------------------------------------

def test_adjust_standing_validates_and_clamps():
    s = _session()
    disp = Dispatcher(s.repo, factions={"watch": _faction("watch")})
    with pytest.raises(ToolApplyError):
        disp.resolve(AdjustStanding(faction="no_such", delta=2, reason="x"))
    rt = disp.resolve(AdjustStanding(faction="watch", delta=5, reason="helped a guard"))
    assert rt.standing_faction == "watch" and rt.standing_delta == 5
    rt0 = disp.resolve(AdjustStanding(faction="watch", delta=0, reason="revealed"))
    assert rt0.standing_faction == "watch" and rt0.standing_delta == 0


# --- context -----------------------------------------------------------------------

def test_context_speaks_tiers_secrets_and_unknowns():
    s = _session()
    ctx = build_context(
        s.repo, scene="the gate",
        factions=[{"id": "watch", "name": "The Watch", "agenda": "find the mole",
                   "score": 12, "tier": "friendly", "known": True},
                  {"id": "hand", "name": "The Gray Hand", "agenda": "dig the tunnel",
                   "score": -20, "tier": "unfriendly", "known": False}])
    assert "FACTION STANDING" in ctx
    assert "The Watch (id: watch) — friendly (+12)" in ctx
    assert "Agenda (secret): find the mole" in ctx
    assert "UNKNOWN to the party" in ctx and "adjust_standing delta 0" in ctx


# --- the loop end-to-end ------------------------------------------------------------

def test_loop_gates_offers_by_standing():
    s = _session()
    s.factions = {"watch": _faction("watch", known=True)}
    s.authored_quests = {
        "inner": _quest("inner", min_standing=MinStanding(faction="watch", tier="friendly")),
        "errand": _quest("errand")}
    loop = TurnLoop(s, Rng(seed=7, record=s.emit_log), Brain(ScriptedLLMClient()))
    _, eligible, _ = loop._compute_offers()
    assert eligible == {"errand"}
    _nudge(s, "watch", 5)
    _nudge(s, "watch", 5)                     # +10 → friendly
    _, eligible, _ = loop._compute_offers()
    assert eligible == {"errand", "inner"}


# --- the player endpoint (redaction) -------------------------------------------------

def test_api_factions_redacts_unknowns_and_ships_tier_words():
    data = client.get("/api/factions").json()
    rows = data["factions"]
    assert rows, "brightvale ships testbed factions"
    known = [r for r in rows if r["known"]]
    unknown = [r for r in rows if not r["known"]]
    assert any(r["name"] == "The Brightvale Watch" and r["tier"] == "neutral"
               for r in known)
    # The Gray Hand exists but the party hasn't met it: a bare row, nothing else.
    assert unknown and all(set(r.keys()) == {"known"} for r in unknown)
    # No score number ever ships — tiers only.
    assert all("score" not in r and "agenda" not in r for r in rows)


# --- the pack linter ------------------------------------------------------------------

def test_lint_catches_unknown_faction_refs():
    errors: list[str] = []
    fac = [Faction(id="watch", name="Watch")]
    npc = [NPC(id="m", name="M", faction="ghost")]
    sb = [StatBlock(id="b", name="B", hp=5, armor_class=10, faction="ghost")]
    q = [_quest(standing=[QuestStanding(faction="ghost", delta=5)],
                min_standing=MinStanding(faction="ghost"))]
    _lint_factions(fac, npc, sb, q, errors)
    assert len([e for e in errors if "ghost" in e]) == 4


def test_brightvale_testbed_factions_load():
    world = load_pack("brightvale")
    ids = {f.id for f in world.factions}
    assert ids == {"brightvale_watch", "gray_hand"}
    maren = next(c for c in world.repository.npcs() if c.id == "gate_guard_maren")
    assert maren.faction == "brightvale_watch"
    bandit = next(s for s in world.statblocks if s.id == "road_bandit")
    assert bandit.faction == "gray_hand"
