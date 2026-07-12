"""Provider registry + local config + client picker (the front-door "connect your
AI" step for outside-machine playtesting).

Every test isolates the config to a tmp file via OUBLIETTE_CONFIG and clears any
ambient ANTHROPIC_API_KEY, so nothing here reads or writes the developer's real
key/config.
"""

from __future__ import annotations

import pytest

from oubliette.llm import providers


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OUBLIETTE_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


# --- registry -------------------------------------------------------------

def test_registry_marks_all_four_providers_wired():
    """v0.9 provider opening: every roster row is selectable — Anthropic natively,
    the other three through the OpenAI-compatible adapter."""
    view = {p["id"]: p for p in providers.registry_view()}
    for pid in ("anthropic", "openai", "google", "local"):
        assert view[pid]["implemented"] is True


def test_registry_reports_has_key_but_never_the_key():
    providers.set_provider_key("anthropic", "sk-ant-secret")
    view = {p["id"]: p for p in providers.registry_view()}
    assert view["anthropic"]["has_key"] is True
    # The secret must not appear anywhere in the surfaced roster.
    assert "sk-ant-secret" not in repr(providers.registry_view())


# --- config round-trip ----------------------------------------------------

def test_set_then_read_key_roundtrips():
    providers.set_provider_key("anthropic", "sk-ant-abc")
    assert providers.stored_key("anthropic") == "sk-ant-abc"
    assert providers.selected_provider() == "anthropic"


def test_empty_key_clears_the_stored_one():
    providers.set_provider_key("anthropic", "sk-ant-abc")
    providers.set_provider_key("anthropic", "")          # save with the box empty
    assert providers.stored_key("anthropic") is None


def test_selected_provider_falls_back_for_an_unknown_choice():
    # A config naming a provider that doesn't exist (hand-edited, or from a future
    # version) resolves to the default so the game never drives a phantom client.
    providers.save_config({"provider": "closedai"})
    assert providers.selected_provider() == "anthropic"


def test_stored_key_prefers_config_then_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert providers.stored_key("anthropic") == "sk-env"     # env when nothing saved
    providers.set_provider_key("anthropic", "sk-config")
    assert providers.stored_key("anthropic") == "sk-config"  # saved key wins


def test_corrupt_config_is_tolerated(tmp_path, monkeypatch):
    bad = tmp_path / "broken.json"
    bad.write_text("not json{", encoding="utf-8")
    monkeypatch.setenv("OUBLIETTE_CONFIG", str(bad))
    assert providers.load_config() == {}                     # never raises


# --- custom meter pricing ---------------------------------------------------

def test_pricing_roundtrips_and_surfaces_in_the_registry():
    providers.set_provider_key("anthropic", "sk-ant-abc",
                               pricing={"input": 2.5, "output": 12.0})
    assert providers.stored_pricing("anthropic") == {"input": 2.5, "output": 12.0}
    view = {p["id"]: p for p in providers.registry_view()}
    assert view["anthropic"]["pricing"] == {"input": 2.5, "output": 12.0}
    assert view["openai"]["pricing"] is None


def test_blank_pricing_clears_back_to_the_table():
    providers.set_provider_key("anthropic", "sk-ant-abc",
                               pricing={"input": 2.5, "output": 12.0})
    providers.set_provider_key("anthropic", "sk-ant-abc")   # saved with fields blank
    assert providers.stored_pricing("anthropic") is None


def test_junk_pricing_reads_as_no_custom_pricing():
    # A hand-edited/corrupt entry must never break the meter — it just means
    # "use the built-in table". Zero/negative prices are junk too.
    for junk in ("cheap", {"input": "x", "output": 5},
                 {"input": 0, "output": 5}, {"input": -1, "output": 5},
                 {"output": 5}):
        providers.save_config({"pricing": {"anthropic": junk}})
        assert providers.stored_pricing("anthropic") is None


# --- the client picker ----------------------------------------------------

def test_pick_client_goes_live_with_a_saved_anthropic_key():
    from oubliette.app.repl import _pick_client
    providers.set_provider_key("anthropic", "sk-ant-live")
    client, name = _pick_client(force_scripted=False)
    assert name == "anthropic"
    assert client.__class__.__name__ == "AnthropicLLMClient"


def test_pick_client_is_offline_without_a_key():
    from oubliette.app.repl import _pick_client
    client, name = _pick_client(force_scripted=False)
    assert name == "scripted"


def test_pick_client_honours_force_scripted_even_with_a_key():
    from oubliette.app.repl import _pick_client
    providers.set_provider_key("anthropic", "sk-ant-live")
    _, name = _pick_client(force_scripted=True)
    assert name == "scripted"
