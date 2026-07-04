"""Provider selection + the player's local config (the front-door "connect your AI"
step, added for outside-machine playtesting).

The game speaks to exactly ONE provider per session through the `LLMClient`
protocol. This module holds two things:

1. The provider **registry** the front-door UI renders — which services exist and
   which are actually *wired up*. Only `implemented` providers are selectable; the
   rest show greyed-out as "coming later" so the menu reads as a roadmap.
2. A tiny **local config** file (the chosen provider + per-provider API keys),
   stored in plaintext beside the save. It is the user's own key on their own
   machine — gitignored, never logged — the normal posture for a local
   single-player tool. We never send a stored key back over the API; the UI only
   learns whether one is *present*.

Keeping this provider-neutral (no concrete client import here) means the registry
is the single place to flip a provider to `implemented=True` once its adapter
lands.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    implemented: bool
    key_label: str = "API key"
    key_hint: str = ""          # placeholder shown in the key field
    env_var: str = ""           # env var the live client also reads (back-compat)
    note: str = ""              # shown under a not-yet-wired provider
    # v0.9 provider opening: the model is FREE TEXT (the exact id the provider's
    # API takes) — no dropdown to keep current, and day-one access to new models.
    # The connection test (llm/connect.py) is what protects against typos.
    default_model: str = ""     # used when the player hasn't typed one
    model_hint: str = ""        # placeholder shown in the model field
    key_optional: bool = False  # local servers usually need no key
    needs_base_url: bool = False   # show the server-address field (local)
    default_base_url: str = ""


# The order here is the order the front door shows them. All four are wired
# (v0.9): Anthropic natively; OpenAI, Gemini and local servers through the one
# OpenAI-compatible adapter (Gemini via Google's official compatibility
# endpoint; local = Ollama/LM Studio/llama.cpp, which all speak the same API).
PROVIDERS: tuple[Provider, ...] = (
    Provider("anthropic", "Anthropic — Claude", True,
             key_label="Anthropic API key", key_hint="sk-ant-…",
             env_var="ANTHROPIC_API_KEY",
             default_model="claude-sonnet-5", model_hint="claude-sonnet-5"),
    Provider("openai", "OpenAI — GPT", True,
             key_label="OpenAI API key", key_hint="sk-…",
             env_var="OPENAI_API_KEY",
             model_hint="the exact model id from OpenAI's docs"),
    Provider("google", "Google — Gemini", True,
             key_label="Gemini API key", key_hint="AI…",
             env_var="GEMINI_API_KEY",
             model_hint="the exact model id from Google's docs"),
    Provider("local", "Local model (on your machine)", True,
             key_label="API key (most local servers need none)", key_optional=True,
             model_hint="the model name your server loads, e.g. llama3.1",
             needs_base_url=True, default_base_url="http://localhost:11434/v1",
             note="Works with any OpenAI-compatible server: Ollama, LM Studio, llama.cpp…"),
)

_BY_ID = {p.id: p for p in PROVIDERS}
DEFAULT_PROVIDER = "anthropic"


def get_provider(pid: str | None) -> Provider | None:
    return _BY_ID.get(pid or "")


def is_implemented(pid: str | None) -> bool:
    p = get_provider(pid)
    return bool(p and p.implemented)


# --- local config ---------------------------------------------------------

CONFIG_NAME = "oubliette-config.json"


def config_path() -> Path:
    """Where the player's provider/key config lives. Beside the save by default
    (overridable with OUBLIETTE_CONFIG, mirroring OUBLIETTE_DB) so tests and odd
    install layouts can redirect it."""
    return Path(os.environ.get("OUBLIETTE_CONFIG", CONFIG_NAME))


def load_config() -> dict:
    """The stored config, or an empty dict. Tolerant of a missing/corrupt file —
    a broken config must never stop the app from opening (it just falls back to
    offline mode)."""
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def selected_provider(cfg: dict | None = None) -> str:
    cfg = load_config() if cfg is None else cfg
    pid = cfg.get("provider")
    return pid if is_implemented(pid) else DEFAULT_PROVIDER


def stored_key(provider: str, cfg: dict | None = None) -> str | None:
    """The saved key for a provider (config first, then the provider's env var so
    a key in a .env / the environment still works without re-entering it)."""
    cfg = load_config() if cfg is None else cfg
    key = (cfg.get("keys") or {}).get(provider)
    if key:
        return key
    p = get_provider(provider)
    if p and p.env_var:
        return os.environ.get(p.env_var) or None
    return None


def stored_model(provider: str, cfg: dict | None = None) -> str:
    """The model id saved for a provider, else the provider's default (which is
    empty for everyone but Anthropic — the free-text field is the source)."""
    cfg = load_config() if cfg is None else cfg
    model = (cfg.get("models") or {}).get(provider)
    if model:
        return model
    p = get_provider(provider)
    return p.default_model if p else ""


def stored_base_url(provider: str, cfg: dict | None = None) -> str:
    """The server address saved for a provider (only `local` uses one), else the
    provider's default."""
    cfg = load_config() if cfg is None else cfg
    url = (cfg.get("base_urls") or {}).get(provider)
    if url:
        return url
    p = get_provider(provider)
    return p.default_base_url if p else ""


def set_provider_key(provider: str, api_key: str | None,
                     model: str | None = None,
                     base_url: str | None = None) -> dict:
    """Persist the selected provider and (optionally) its key, model name and
    server address. An empty key clears the stored one (revert to offline);
    empty model/base_url clear back to the provider defaults. Returns the
    saved config."""
    cfg = load_config()
    cfg["provider"] = provider

    def _bucket(name: str, value: str | None) -> None:
        entries = dict(cfg.get(name) or {})
        if value and value.strip():
            entries[provider] = value.strip()
        else:
            entries.pop(provider, None)
        cfg[name] = entries

    _bucket("keys", api_key)
    _bucket("models", model)
    _bucket("base_urls", base_url)
    save_config(cfg)
    return cfg


def registry_view() -> list[dict]:
    """The provider list for the front-door UI. NEVER includes key material — only
    whether a key is on file (`has_key`) so the form can say 'key saved'."""
    cfg = load_config()
    out = []
    for p in PROVIDERS:
        out.append({
            "id": p.id,
            "label": p.label,
            "implemented": p.implemented,
            "note": p.note,
            "key_label": p.key_label,
            "key_hint": p.key_hint,
            "key_optional": p.key_optional,
            "model_hint": p.model_hint,
            "model": stored_model(p.id, cfg),
            "needs_base_url": p.needs_base_url,
            "base_url": stored_base_url(p.id, cfg),
            "has_key": bool(stored_key(p.id, cfg)) if p.implemented else False,
        })
    return out
