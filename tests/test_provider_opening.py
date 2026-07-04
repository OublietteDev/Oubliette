"""v0.9 provider opening: four providers, free-text model names, a real ping.

The DM speaks through two adapters now — the native Anthropic client and ONE
OpenAI-compatible client that covers OpenAI, Gemini (Google's compatibility
endpoint) and local servers. The model name is free text (no dropdown to keep
current); the protection against typos is `connect.ping` — a real forced-tool
call — and the front door's rule that settings only SAVE after the ping passes.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
from typing import Literal

import pytest
from pydantic import BaseModel

from oubliette.llm import connect, providers
from oubliette.llm.anthropic_client import AnthropicLLMClient
from oubliette.llm.client import Msg
from oubliette.llm.openai_compat import (GEMINI_BASE_URL, OPENAI_BASE_URL,
                                         OpenAICompatClient)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OUBLIETTE_CONFIG", str(tmp_path / "cfg.json"))
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield


class Answer(BaseModel):
    ok: bool


class Zap(BaseModel):
    """Zap a target with crackling power."""

    tool: Literal["zap"] = "zap"
    target: str
    power: int


# --- the OpenAI-compatible adapter -------------------------------------------------

def _client(**kw) -> OpenAICompatClient:
    return OpenAICompatClient(model="test-model", api_key="sk-test", **kw)


def _chat_response(content=None, tool_calls=None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


def test_complete_forces_and_validates(monkeypatch):
    c = _client()
    seen = {}
    monkeypatch.setattr(c, "_post", lambda payload: seen.update(payload) or _chat_response(
        tool_calls=[{"function": {"name": "emit", "arguments": '{"ok": true}'}}]))
    result = asyncio.run(c.complete(system="sys", messages=[Msg(role="user", content="hi")],
                                    schema=Answer))
    assert result.ok is True
    assert seen["messages"][0] == {"role": "system", "content": "sys"}   # OpenAI shape
    assert seen["tool_choice"] == {"type": "function", "function": {"name": "emit"}}


def test_complete_tolerates_envelope_and_retries_duds(monkeypatch):
    c = _client()
    responses = iter([
        _chat_response(content="no tool call at all"),                      # dud
        _chat_response(tool_calls=[{"function": {
            "name": "emit", "arguments": '{"parameters": {"ok": true}}'}}]),  # envelope
    ])
    monkeypatch.setattr(c, "_post", lambda payload: next(responses))
    assert asyncio.run(c.complete(system="s", messages=[], schema=Answer)).ok is True


def test_act_collects_narration_and_tool_calls(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_post", lambda payload: _chat_response(
        content="The wand hums.",
        tool_calls=[{"function": {"name": "zap",
                                  "arguments": '{"target": "rat", "power": 3}'}}]))
    result = asyncio.run(c.act(system="s", messages=[Msg(role="user", content="zap the rat")],
                               tools=[Zap]))
    assert result.narration == "The wand hums."
    (call,) = result.tool_calls
    assert isinstance(call, Zap) and call.target == "rat" and call.power == 3


class _FakeSSE:
    """A urllib response double: iterable SSE byte lines + context manager."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = [l.encode() for l in lines]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_act_streams_text_and_accumulates_tool_fragments(monkeypatch):
    def chunk(delta: dict) -> str:
        return "data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n"

    lines = [
        chunk({"content": "The wand "}),
        chunk({"content": "hums."}),
        # one tool call, arguments split across three fragments
        chunk({"tool_calls": [{"index": 0, "function": {"name": "zap", "arguments": '{"tar'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'get": "rat", "pow'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'er": 3}'}}]}),
        "data: [DONE]\n",
    ]
    monkeypatch.setattr("oubliette.llm.openai_compat.urllib.request.urlopen",
                        lambda req, timeout=0: _FakeSSE(lines))
    c = _client()
    streamed: list[str] = []
    result = asyncio.run(c.act(system="s", messages=[], tools=[Zap],
                               on_text=streamed.append))
    assert "".join(streamed) == "The wand hums." == result.narration
    (call,) = result.tool_calls
    assert call.target == "rat" and call.power == 3


def test_local_servers_need_no_key():
    c = OpenAICompatClient(model="llama3.1", base_url="http://localhost:11434/v1")
    assert "authorization" not in c._headers()
    assert _client()._headers()["authorization"] == "Bearer sk-test"


def test_a_missing_model_name_is_refused():
    with pytest.raises(RuntimeError, match="model"):
        OpenAICompatClient(model="", api_key="sk-test")


# --- the factory: one place settings become a client --------------------------------

def test_build_client_routes_each_provider():
    a = connect.build_client("anthropic", "sk-ant-x", "claude-sonnet-5", None)
    assert isinstance(a, AnthropicLLMClient) and a._model == "claude-sonnet-5"
    o = connect.build_client("openai", "sk-x", "some-gpt", None)
    assert isinstance(o, OpenAICompatClient)
    assert o._url == OPENAI_BASE_URL + "/chat/completions"
    g = connect.build_client("google", "AI-x", "some-gemini", None)
    assert g._url == GEMINI_BASE_URL + "/chat/completions"
    l = connect.build_client("local", None, "llama3.1", "http://localhost:1234/v1")
    assert l._url == "http://localhost:1234/v1/chat/completions"


def test_build_client_refuses_missing_pieces():
    with pytest.raises(RuntimeError, match="model"):
        connect.build_client("openai", "sk-x", "", None)     # no model, no default
    with pytest.raises(RuntimeError, match="key"):
        connect.build_client("openai", None, "some-gpt", None)
    # anthropic still has its default model; local needs no key
    assert isinstance(connect.build_client("anthropic", "sk-ant-x"), AnthropicLLMClient)
    assert isinstance(connect.build_client("local", None, "llama3.1"), OpenAICompatClient)


# --- the ping: prove the settings before trusting them -------------------------------

class _StubClient:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result, self._error = result, error

    async def complete(self, *, system, messages, schema, on_text=None):
        if self._error:
            raise self._error
        return schema(ok=True) if self._result is None else self._result


def test_ping_passes_on_a_real_tool_answer():
    ok, err = asyncio.run(connect.ping(_StubClient()))
    assert ok is True and err is None


@pytest.mark.parametrize("detail, expect", [
    ("Anthropic API HTTP 404: model: not_found_error clade-sonnet-5", "doesn't exist"),
    ("API HTTP 401: invalid api key", "rejected that API key"),
    ("API HTTP 429: rate limit exceeded", "rate limit"),
    ("API HTTP 500: internal", "having trouble"),
    ("API connection error: <urlopen error [Errno 111] refused>", "couldn't reach"),
    ("model did not emit the forced structured-output call", "tool-calling"),
])
def test_ping_turns_wire_errors_into_sentences(detail, expect):
    ok, err = asyncio.run(connect.ping(_StubClient(error=RuntimeError(detail))))
    assert ok is False and expect in err


# --- config + registry ---------------------------------------------------------------

def test_all_four_providers_are_wired():
    view = providers.registry_view()
    assert [p["id"] for p in view] == ["anthropic", "openai", "google", "local"]
    assert all(p["implemented"] for p in view)
    local = next(p for p in view if p["id"] == "local")
    assert local["needs_base_url"] and local["key_optional"]
    assert local["base_url"] == "http://localhost:11434/v1"


def test_model_and_base_url_round_trip():
    providers.set_provider_key("openai", "sk-x", model="some-gpt")
    providers.set_provider_key("local", None, model="llama3.1",
                               base_url="http://localhost:1234/v1")
    assert providers.stored_model("openai") == "some-gpt"
    assert providers.stored_model("local") == "llama3.1"
    assert providers.stored_base_url("local") == "http://localhost:1234/v1"
    # blank model clears back to the provider default
    providers.set_provider_key("anthropic", "sk-ant-x", model="")
    assert providers.stored_model("anthropic") == "claude-sonnet-5"
    # keys never appear in the registry view
    assert "sk-x" not in json.dumps(providers.registry_view())


def test_pick_client_goes_live_per_provider():
    from oubliette.app.repl import _pick_client
    providers.set_provider_key("openai", "sk-x", model="some-gpt")
    client, name = _pick_client(force_scripted=False)
    assert isinstance(client, OpenAICompatClient) and name == "openai"
    providers.set_provider_key("local", None, model="llama3.1")
    client, name = _pick_client(force_scripted=False)
    assert isinstance(client, OpenAICompatClient) and name == "local"


def test_pick_client_falls_back_without_enough_settings():
    from oubliette.app.repl import _pick_client
    providers.set_provider_key("openai", None, model="some-gpt")   # key required
    _client_, name = _pick_client(force_scripted=False)
    assert name == "scripted"
    providers.set_provider_key("local", None, model="")            # local needs a model
    _client_, name = _pick_client(force_scripted=False)
    assert name == "scripted"


# --- the front-door endpoints: save only after the ping passes ------------------------

@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    import os
    import tempfile
    os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "prov-test.sqlite"))
    from fastapi.testclient import TestClient
    from oubliette.app import server as appserver
    return TestClient(appserver.app)


def _fake_ping(result: tuple[bool, str | None]):
    async def ping(client):
        return result
    return ping


def test_save_persists_only_after_the_ping_passes(app_client, monkeypatch):
    monkeypatch.setattr("oubliette.llm.connect.ping", _fake_ping((True, None)))
    res = app_client.post("/api/providers", json={
        "provider": "openai", "api_key": "sk-x", "model": "some-gpt"}).json()
    assert res["ok"] is True and res["online"] is True and res["client"] == "openai"
    assert res["model"] == "some-gpt"                     # the badge echoes the typed id
    assert providers.stored_model("openai") == "some-gpt"

    monkeypatch.setattr("oubliette.llm.connect.ping",
                        _fake_ping((False, "the provider says that model doesn't exist")))
    bad = app_client.post("/api/providers", json={
        "provider": "openai", "api_key": "sk-x", "model": "clade-gpt"})
    assert bad.status_code == 400
    assert "doesn't exist" in bad.json()["error"]
    assert providers.stored_model("openai") == "some-gpt"   # the typo never saved


def test_test_endpoint_pings_without_saving(app_client, monkeypatch):
    monkeypatch.setattr("oubliette.llm.connect.ping", _fake_ping((True, None)))
    res = app_client.post("/api/providers/test", json={
        "provider": "google", "api_key": "AI-x", "model": "some-gemini"}).json()
    assert res["ok"] is True
    assert providers.stored_key("google") is None            # nothing persisted


def test_disconnect_clears_the_key_and_goes_offline(app_client, monkeypatch):
    monkeypatch.setattr("oubliette.llm.connect.ping", _fake_ping((True, None)))
    app_client.post("/api/providers", json={
        "provider": "openai", "api_key": "sk-x", "model": "some-gpt"})
    res = app_client.post("/api/providers", json={
        "provider": "openai", "disconnect": True, "model": "some-gpt"}).json()
    assert res["ok"] is True and res["online"] is False
    assert providers.stored_key("openai") is None
    assert providers.stored_model("openai") == "some-gpt"    # settings kept for next time
