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

def test_registry_marks_only_anthropic_implemented():
    view = {p["id"]: p for p in providers.registry_view()}
    assert view["anthropic"]["implemented"] is True
    for pid in ("openai", "google", "local"):
        assert view[pid]["implemented"] is False
        assert view[pid]["note"]              # an unselectable provider explains itself


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


def test_selected_provider_falls_back_for_an_unimplemented_choice():
    # Even if the config names a not-yet-wired provider, selection resolves to the
    # default wired one so the game never tries to drive a phantom client.
    providers.save_config({"provider": "openai"})
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
