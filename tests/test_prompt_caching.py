"""Prompt caching (Anthropic-only): the stable prompt prefix — the standing system
prompt + tool schemas, and the session-stable STORY SO FAR block — carries
`cache_control` markers so repeated turns bill it at cache rates instead of full
price. 1-HOUR TTL by design: players step away into Arena fights for well over
the default 5 minutes.

All offline: payloads are captured before the wire; no network.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from oubliette.llm.anthropic_client import AnthropicLLMClient, _system_blocks
from oubliette.llm.client import Msg
from oubliette.llm.openai_compat import OpenAICompatClient

_MARK = {"type": "ephemeral", "ttl": "1h"}


class _Out(BaseModel):
    note: str = "ok"


class _Wave(BaseModel):
    """Wave."""
    tool: str = "wave"


def _capture_complete(client, **kwargs):
    """Run complete() against a canned wire reply, returning the payload sent."""
    seen: dict = {}

    def fake_post(payload):
        seen.update(payload)
        return {"content": [{"type": "tool_use", "input": {"note": "hi"}}]}

    client._post = fake_post
    asyncio.run(client.complete(messages=[Msg(role="user", content="hi")],
                                schema=_Out, **kwargs))
    return seen


def _capture_act(client, **kwargs):
    seen: dict = {}

    def fake_post(payload):
        seen.update(payload)
        return {"content": [{"type": "text", "text": "A tale."}]}

    client._post = fake_post
    asyncio.run(client.act(messages=[Msg(role="user", content="hi")],
                           tools=[_Wave], **kwargs))
    return seen


# --- the system blocks (both call shapes) ------------------------------------
def test_complete_marks_the_system_prompt_for_caching():
    payload = _capture_complete(AnthropicLLMClient(api_key="k"), system="SYS")
    assert payload["system"] == [
        {"type": "text", "text": "SYS", "cache_control": _MARK}]


def test_act_marks_the_system_prompt_for_caching():
    payload = _capture_act(AnthropicLLMClient(api_key="k"), system="SYS")
    assert payload["system"] == [
        {"type": "text", "text": "SYS", "cache_control": _MARK}]


def test_stable_context_rides_as_its_own_cached_block():
    payload = _capture_act(AnthropicLLMClient(api_key="k"), system="SYS",
                           stable_context="STORY SO FAR: the cult lives.")
    assert payload["system"] == [
        {"type": "text", "text": "SYS", "cache_control": _MARK},
        {"type": "text", "text": "STORY SO FAR: the cult lives.", "cache_control": _MARK}]


def test_empty_stable_context_adds_no_block():
    assert len(_system_blocks("SYS", "")) == 1


# --- non-Anthropic providers: the notes still reach the DM (no cache, no loss) --
def test_openai_compat_folds_stable_context_into_the_system_message():
    msgs = OpenAICompatClient._messages(
        "SYS", [Msg(role="user", content="hi")], "STORY SO FAR: the cult lives.")
    assert msgs[0]["role"] == "system"
    assert "SYS" in msgs[0]["content"] and "the cult lives" in msgs[0]["content"]
    # and without notes the system message is untouched
    assert OpenAICompatClient._messages("SYS", [])[0]["content"] == "SYS"


# --- the brain threads it through ---------------------------------------------
def test_brain_passes_stable_context_to_both_call_shapes():
    from oubliette.dm.brain import Brain
    from oubliette.llm.client import ActResult
    from oubliette.schemas import Intent, Tier, TurnAssessment, Verb

    seen: dict = {}

    class _Recorder:
        async def complete(self, *, system, messages, schema, on_text=None,
                           stable_context=""):
            seen["complete"] = stable_context
            return TurnAssessment(intent=Intent(raw_text="hi", verb=Verb.SKILL_CHECK),
                                  tier=Tier.FREESTYLE, resolution_hint="")

        async def act(self, *, system, messages, tools, on_text=None,
                      effort=None, stable_context=""):
            seen["act"] = stable_context
            return ActResult(narration="A tale.")

    brain = Brain(_Recorder())
    assessment = asyncio.run(brain.assess("hi", "CTX", stable_context="NOTES"))
    asyncio.run(brain.resolve("hi", assessment, None, "CTX", stable_context="NOTES"))
    assert seen == {"complete": "NOTES", "act": "NOTES"}
