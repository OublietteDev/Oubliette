"""W6 resolve restructure: narration is a streaming assistant TEXT channel and state
changes ride `tool_choice: auto` tool calls (no forced `emit`).

These cover the new `act()` seam end to end without a live model: the scripted double's
`act`, the Anthropic adapter's pure stream/collect/tool-def helpers, and the new
`set_environment` tool flowing through the dispatcher and the loop.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import Brain
from oubliette.llm.anthropic_client import AnthropicLLMClient, _tool_def, _tool_name

_collect_act = AnthropicLLMClient._collect_act
from oubliette.llm.client import ActResult
from oubliette.llm.scripted import ScriptedLLMClient
from oubliette.record.events import EventKind
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.tools.dispatch import Dispatcher
from oubliette.tools.schemas import CreateEntity, SetEnvironment, Transact


# --- the scripted double's act() --------------------------------------------
def test_scripted_act_returns_narration_and_tools():
    client = ScriptedLLMClient()
    messages = _resolve_messages("VERB: skill_check\nPLAYER: I approach the old woman at the well.")
    result = asyncio.run(client.act(system="", messages=messages, tools=[]))
    assert isinstance(result, ActResult)
    assert result.narration                      # narration is plain text now
    assert any(isinstance(c, CreateEntity) for c in result.tool_calls)


def test_scripted_act_streams_narration_word_by_word():
    client = ScriptedLLMClient()
    chunks: list[str] = []
    messages = _resolve_messages("VERB: skill_check\nSKILL: perception\nPLAYER: I look around.")
    result = asyncio.run(client.act(system="", messages=messages, tools=[], on_text=chunks.append))
    assert "".join(chunks) == result.narration    # the stream reconstructs the full text
    assert len(chunks) > 1                         # actually streamed in pieces


# --- the Anthropic adapter's pure helpers (no network) ----------------------
def test_tool_def_strips_the_discriminator():
    d = _tool_def(Transact)
    assert d["name"] == "transact" == _tool_name(Transact)
    assert "tool" not in d["input_schema"].get("properties", {})
    assert "tool" not in d["input_schema"].get("required", [])
    assert d["description"]                         # the docstring becomes the tool description


def test_collect_act_splits_text_thinking_and_tool_use():
    data = {"content": [
        {"type": "thinking", "thinking": "The lock is simple; the rogue succeeds."},
        {"type": "text", "text": "You "},
        {"type": "text", "text": "step inside."},
        {"type": "tool_use", "name": "give", "input": {"to": "pc"}},
    ]}
    narration, raw, thinking = _collect_act(data)
    assert narration == "You step inside."
    assert raw == [{"name": "give", "input": {"to": "pc"}}]
    assert thinking == "The lock is simple; the rogue succeeds."


# --- the set_environment tool -----------------------------------------------
def test_set_environment_requires_a_change():
    import pytest
    with pytest.raises(ValueError):
        SetEnvironment()                            # neither field set → invalid


def test_dispatch_resolves_set_environment():
    s = Session.open(InMemoryEventStore())
    disp = Dispatcher(s.repo)
    rt = disp.resolve(SetEnvironment(time_of_day="night", weather="rain", reason="camp"))
    assert rt.env_time == "night" and rt.env_weather == "rain"
    assert rt.ops == []                             # env isn't protected StateOp state


class _EnvBrain(Brain):
    """Real scripted assess; resolve returns a fixed ActResult (with any tool calls)."""

    def __init__(self, client, tool_calls):
        super().__init__(client)
        self._tool_calls = tool_calls

    async def resolve(self, *a, on_text=None, **k):
        narration = "The light shifts as the hour turns."
        if on_text is not None:
            on_text(narration)
        return ActResult(narration=narration, tool_calls=list(self._tool_calls))


def _env_events(store) -> list:
    return [e for e in store.read_all() if e.kind == EventKind.ENVIRONMENT_CHANGED]


def test_loop_applies_set_environment():
    s = Session.open(InMemoryEventStore())
    assert (s.time_of_day, s.weather) == ("day", "clear")
    loop = TurnLoop(s, Rng(1, record=s.emit_log),
                    _EnvBrain(ScriptedLLMClient(),
                              [SetEnvironment(time_of_day="night", weather="rain", reason="camp")]))
    report = asyncio.run(loop.take_turn("I tend the small fire."))
    assert (s.time_of_day, s.weather) == ("night", "rain")
    assert len(_env_events(s.store)) == 1
    # the durable beat notes the environment turn
    assert any("environment" in b for b in loop.history)


def test_loop_set_environment_noop_when_unchanged():
    s = Session.open(InMemoryEventStore())          # already day/clear
    loop = TurnLoop(s, Rng(1, record=s.emit_log),
                    _EnvBrain(ScriptedLLMClient(),
                              [SetEnvironment(time_of_day="day", reason="still daylight")]))
    asyncio.run(loop.take_turn("I glance at the sky."))
    assert (s.time_of_day, s.weather) == ("day", "clear")
    assert _env_events(s.store) == []               # no redundant environment event


def _resolve_messages(content: str):
    from oubliette.llm.client import Msg
    return [Msg(role="user", content=content)]


# --- the SSE stream parser against a canned Anthropic byte stream -----------
class _FakeResp:
    """A stand-in urllib response: a context manager that iterates SSE byte lines."""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


def _sse(events) -> list[bytes]:
    import json
    lines: list[bytes] = []
    for e in events:
        lines.append(f"event: {e['type']}\n".encode())
        lines.append(f"data: {json.dumps(e)}\n".encode())
        lines.append(b"\n")
    return lines


def test_complete_retries_on_empty_forced_emit(monkeypatch):
    """Sonnet-5 sometimes returns an empty `emit({})`; `complete` (assess/wrap) has no
    upstream retry loop, so it must regenerate on a validation failure rather than crash
    the turn."""
    from oubliette.enums import Tier
    from oubliette.schemas import TurnAssessment

    client = AnthropicLLMClient(api_key="test-key")
    calls = {"n": 0}

    def fake_post(payload):
        calls["n"] += 1
        if calls["n"] == 1:                                   # first generation: empty dud
            return {"content": [{"type": "tool_use", "name": "emit", "input": {}}]}
        return {"content": [{"type": "tool_use", "name": "emit", "input": {
            "intent": {"raw_text": "I look around.", "verb": "skill_check"},
            "tier": "freestyle"}}]}

    monkeypatch.setattr(client, "_post", fake_post)
    from oubliette.llm.client import Msg
    result = asyncio.run(client.complete(
        system="", messages=[Msg(role="user", content="x")], schema=TurnAssessment))
    assert calls["n"] == 2                                    # retried past the empty emit
    assert result.tier == Tier.FREESTYLE


def test_post_stream_act_parses_thinking_text_and_tool_use(monkeypatch):
    events = [
        {"type": "message_start", "message": {}},
        # a leading extended-thinking block (W4) — captured, but NEVER streamed to the player
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "The door is unlocked; "}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "no check needed."}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "signature_delta", "signature": "abc123"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": "You step "}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": "into the hall."}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2,
         "content_block": {"type": "tool_use", "id": "t1", "name": "give", "input": {}}},
        {"type": "content_block_delta", "index": 2,
         "delta": {"type": "input_json_delta", "partial_json": '{"to":"p'}},
        {"type": "content_block_delta", "index": 2,
         "delta": {"type": "input_json_delta", "partial_json": 'c","items":[]}'}},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {}},
        {"type": "message_stop"},
    ]
    import oubliette.llm.anthropic_client as ac
    monkeypatch.setattr(ac.urllib.request, "urlopen", lambda req, timeout=0: _FakeResp(_sse(events)))

    client = AnthropicLLMClient(api_key="test-key")
    chunks: list[str] = []
    narration, tools, thinking = client._post_stream_act({}, chunks.append)

    assert narration == "You step into the hall."
    assert chunks == ["You step ", "into the hall."]     # ONLY narration streamed to the player
    assert thinking == "The door is unlocked; no check needed."   # captured, not streamed
    assert tools == [{"name": "give", "input": {"to": "pc", "items": []}}]


def test_act_uses_adaptive_thinking_and_complete_disables_it(monkeypatch):
    """The resolve turn (`act`) opts into ADAPTIVE thinking + effort with `tool_choice: auto`
    (sonnet-5's shape — the old `budget_tokens` form 400s); the forced-tool `complete`
    (assess/wrap) explicitly DISABLES thinking (incompatible with a forced tool, and
    classification doesn't want the pause)."""
    from oubliette.enums import Tier
    from oubliette.llm.client import Msg
    from oubliette.schemas import TurnAssessment
    from oubliette.tools.schemas import TOOL_MODELS

    client = AnthropicLLMClient(api_key="test-key", effort="low")
    seen = {}

    def fake_post(payload):
        seen.clear(); seen.update(payload)
        if payload.get("tool_choice", {}).get("type") == "tool":
            return {"content": [{"type": "tool_use", "name": "emit", "input": {
                "intent": {"raw_text": "x", "verb": "skill_check"}, "tier": "freestyle"}}]}
        return {"content": [{"type": "text", "text": "You look about."}]}

    monkeypatch.setattr(client, "_post", fake_post)

    asyncio.run(client.act(system="", messages=[Msg(role="user", content="x")],
                           tools=list(TOOL_MODELS)))
    assert seen["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert seen["output_config"] == {"effort": "low"}
    assert seen["tool_choice"] == {"type": "auto"}
    assert seen["max_tokens"] >= 4096                     # room for thinking + narration + tools

    asyncio.run(client.complete(system="", messages=[Msg(role="user", content="x")],
                                schema=TurnAssessment))
    assert seen["thinking"] == {"type": "disabled"}       # forced-tool call never thinks
    assert "output_config" not in seen


def test_effort_by_tier():
    from oubliette.dm.brain import _effort_for
    from oubliette.enums import Tier, Verb
    from oubliette.schemas import Intent, TurnAssessment

    def a(tier):
        return TurnAssessment(intent=Intent(raw_text="x", verb=Verb.SKILL_CHECK), tier=tier)

    assert _effort_for(a(Tier.RECOMBINED)) == "high"   # clever/edge-case adjudication → think
    assert _effort_for(a(Tier.DENIED)) == "high"       # bald claim to refuse → think
    assert _effort_for(a(Tier.FREESTYLE)) is None       # routine narration → no thinking
    assert _effort_for(a(Tier.AUTHORED)) is None        # scripted content → no thinking


def test_brain_resolve_passes_per_turn_effort():
    from oubliette.dm.brain import Brain
    from oubliette.enums import Tier, Verb
    from oubliette.schemas import Intent, TurnAssessment

    captured = {}

    class _Cap:
        async def act(self, *, system, messages, tools, on_text=None, effort=None):
            captured["effort"] = effort
            return ActResult(narration="ok")

        async def complete(self, **k):  # pragma: no cover - resolve never calls it
            raise AssertionError

    brain = Brain(_Cap())
    contested = TurnAssessment(intent=Intent(raw_text="I con the merchant", verb=Verb.SKILL_CHECK),
                               tier=Tier.RECOMBINED)
    asyncio.run(brain.resolve("I con the merchant", contested, roll_result="success"))
    assert captured["effort"] == "high"

    routine = TurnAssessment(intent=Intent(raw_text="I look around", verb=Verb.SKILL_CHECK),
                             tier=Tier.FREESTYLE)
    asyncio.run(brain.resolve("I look around", routine, roll_result=None))
    assert captured["effort"] is None


def test_effort_none_disables_thinking(monkeypatch):
    from oubliette.llm.client import Msg
    from oubliette.tools.schemas import TOOL_MODELS

    client = AnthropicLLMClient(api_key="test-key", effort=None)
    seen = {}
    monkeypatch.setattr(client, "_post", lambda p: (seen.update(p),
        {"content": [{"type": "text", "text": "ok"}]})[1])
    asyncio.run(client.act(system="", messages=[Msg(role="user", content="x")],
                           tools=list(TOOL_MODELS)))
    assert "thinking" not in seen and "output_config" not in seen
