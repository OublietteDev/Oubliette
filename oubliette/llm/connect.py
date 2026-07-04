"""Build a live DM client from provider settings, and PROVE it works.

The v0.9 provider opening made the model name free text — the exact id the
provider's API takes — which trades the impossible-to-maintain model dropdown
for one new failure mode: a typo (`clade-sonnet-5`) that would otherwise sit
silently until the first turn crashed. This module is the answer:

- `build_client(...)` is the ONE place provider settings become a concrete
  `LLMClient` (the front door's save/test paths and the game's `_pick_client`
  all come through here, so they can never disagree).
- `ping(client)` makes a real, tiny API call — a FORCED tool call, because
  structured tool output is the DM's hardest requirement; a model that chats
  fine but can't call tools can't run the game. Pass = this exact key + model
  + address combination can genuinely be the Phantom.
- `friendly_error(...)` turns the wire error into a sentence a player can act
  on ("no model called 'clade-sonnet-5'" beats an HTTP traceback).

The front door only SAVES settings after ping passes, so a typo can never
enter the config through the UI.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .client import LLMClient, Msg
from .openai_compat import (GEMINI_BASE_URL, LOCAL_BASE_URL, OPENAI_BASE_URL,
                            OpenAICompatClient)
from . import providers


def build_client(provider: str, api_key: str | None, model: str | None = None,
                 base_url: str | None = None) -> LLMClient:
    """A concrete client for a provider row. Raises RuntimeError with a
    player-facing message when the settings can't even construct one (no key
    where one is required, no model name)."""
    p = providers.get_provider(provider)
    if p is None or not p.implemented:
        raise RuntimeError(f"unknown provider {provider!r}")
    model = (model or "").strip() or p.default_model
    if not model:
        raise RuntimeError("enter the model's exact API id (e.g. claude-sonnet-5)")
    if not api_key and not p.key_optional:
        raise RuntimeError(f"no {p.key_label} set")
    if provider == "anthropic":
        from .anthropic_client import AnthropicLLMClient
        return AnthropicLLMClient(model=model, api_key=api_key)
    bases = {"openai": OPENAI_BASE_URL, "google": GEMINI_BASE_URL, "local": LOCAL_BASE_URL}
    base = (base_url or "").strip() or providers.stored_base_url(provider) or bases[provider]
    return OpenAICompatClient(model=model, api_key=api_key, base_url=base)


class _Ping(BaseModel):
    """Connection test: call this tool with ok=true."""

    ok: bool = Field(description="true — this call is the whole test")


async def ping(client: LLMClient) -> tuple[bool, str | None]:
    """One tiny REAL call through the client's own structured-output path.
    Returns (ok, player-facing error). Costs a fraction of a cent; proves the
    key, the model id, the address, and — critically — that the model can do
    the forced tool-calling the DM is built on."""
    try:
        result = await client.complete(
            system="This is an automated connection test. Call the tool with ok=true.",
            messages=[Msg(role="user", content="Connection test.")],
            schema=_Ping)
        if getattr(result, "ok", False):
            return True, None
        return False, "the model answered, but not the way the game needs — try another model"
    except Exception as e:                       # every failure becomes a sentence
        return False, friendly_error(str(e))


def friendly_error(detail: str) -> str:
    """Map a wire error onto what the player should actually do about it."""
    low = detail.lower()
    code = re.search(r"http (\d{3})", low)
    status = int(code.group(1)) if code else None
    if status in (401, 403) or "authentication" in low or "invalid x-api-key" in low:
        return "the provider rejected that API key — check it and try again"
    if status == 404 or "not_found" in low or "does not exist" in low or "not found" in low:
        return "the provider says that model doesn't exist — check the model id for typos"
    if status == 429 or "rate limit" in low or "quota" in low or "credit" in low:
        return "the provider accepted the key but refused the call (rate limit or no credit)"
    if status is not None and status >= 500:
        return "the provider is having trouble right now — try again in a minute"
    if "connection error" in low or "urlopen" in low or "refused" in low or "timed out" in low:
        return "couldn't reach the server — check the address (and that the server is running)"
    if "did not emit" in low or "validation error" in low:
        return "that model can't do the tool-calling the game is built on — try another model"
    return detail[:200]
