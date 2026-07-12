"""Session cost meter: the Anthropic adapter tallies each response's `usage` tail
(tokens the API reports exactly) and prices the total from the published per-MTok
rates (dollars the API does NOT report — that part is our arithmetic).

All offline: the meter folds canned usage dicts / a canned SSE byte stream; no network.
"""

from __future__ import annotations

import datetime
import json

from oubliette.llm.anthropic_client import AnthropicLLMClient, estimate_cost_usd


def _client() -> AnthropicLLMClient:
    return AnthropicLLMClient(api_key="test-key")


# --- the accumulator ---------------------------------------------------------
def test_meter_starts_at_zero():
    u = _client().usage
    assert u == {"input_tokens": 0, "output_tokens": 0,
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                 "calls": 0}


def test_record_usage_accumulates_across_calls():
    c = _client()
    c._record_usage({"input_tokens": 1200, "output_tokens": 300,
                     "cache_read_input_tokens": 5000})
    c._record_usage({"input_tokens": 800, "output_tokens": 150,
                     "cache_creation_input_tokens": 2000})
    assert c.usage["input_tokens"] == 2000
    assert c.usage["output_tokens"] == 450
    assert c.usage["cache_read_input_tokens"] == 5000
    assert c.usage["cache_creation_input_tokens"] == 2000
    assert c.usage["calls"] == 2


def test_record_usage_never_breaks_on_junk():
    # The meter must never be able to crash a turn — odd shapes are ignored.
    c = _client()
    c._record_usage(None)
    c._record_usage("not a dict")
    c._record_usage({"input_tokens": "12", "output_tokens": None, "bogus": 9})
    assert c.usage["input_tokens"] == 0 and c.usage["output_tokens"] == 0


# --- streaming capture (message_start carries input, message_delta the final output) ---
class _FakeResp:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


def _sse(events) -> list[bytes]:
    lines: list[bytes] = []
    for e in events:
        lines.append(f"event: {e['type']}\n".encode())
        lines.append(f"data: {json.dumps(e)}\n".encode())
        lines.append(b"\n")
    return lines


def test_stream_records_usage_from_start_and_delta(monkeypatch):
    events = [
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 4000, "output_tokens": 2,
            "cache_read_input_tokens": 1500, "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "You step into the hall."}},
        {"type": "content_block_stop", "index": 0},
        # message_delta's output count is CUMULATIVE — the last one is the bill
        {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 60}},
        {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 240}},
        {"type": "message_stop"},
    ]
    import oubliette.llm.anthropic_client as ac
    monkeypatch.setattr(ac.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(_sse(events)))
    c = _client()
    narration, tools, thinking = c._post_stream_act({}, lambda t: None)
    assert narration == "You step into the hall."
    assert c.usage["input_tokens"] == 4000
    assert c.usage["output_tokens"] == 240          # the final cumulative value, not the sum
    assert c.usage["cache_read_input_tokens"] == 1500
    assert c.usage["calls"] == 1


def test_nonstream_post_records_usage(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "ok"}],
                               "usage": {"input_tokens": 900, "output_tokens": 50}}).encode()

    import oubliette.llm.anthropic_client as ac
    monkeypatch.setattr(ac.urllib.request, "urlopen", lambda req, timeout=0: _Resp())
    c = _client()
    c._post({"model": "x"})
    assert c.usage == {"input_tokens": 900, "output_tokens": 50,
                       "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                       "calls": 1}


# --- the price arithmetic ----------------------------------------------------
_MTOK = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def test_sonnet5_intro_pricing_inside_the_window():
    cost = estimate_cost_usd("claude-sonnet-5", _MTOK, on=datetime.date(2026, 7, 11))
    assert cost["input"] == 2.0 and cost["output"] == 10.0    # launch price
    assert cost["total"] == 12.0


def test_sonnet5_standard_pricing_after_the_window():
    cost = estimate_cost_usd("claude-sonnet-5", _MTOK, on=datetime.date(2026, 9, 1))
    assert cost["input"] == 3.0 and cost["output"] == 15.0
    assert cost["total"] == 18.0


def test_opus_and_haiku_families_price_from_the_table():
    on = datetime.date(2026, 7, 11)
    assert estimate_cost_usd("claude-opus-4-8", _MTOK, on=on)["total"] == 30.0    # 5 + 25
    assert estimate_cost_usd("claude-haiku-4-5", _MTOK, on=on)["total"] == 6.0    # 1 + 5
    # legacy Opus ids keep their old (higher) rates — matched BEFORE generic "opus"
    assert estimate_cost_usd("claude-opus-4-1", _MTOK, on=on)["total"] == 90.0    # 15 + 75


def test_cache_tokens_price_at_their_own_rates():
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_creation_input_tokens": 1_000_000,
             "cache_read_input_tokens": 1_000_000}
    cost = estimate_cost_usd("claude-sonnet-4-6", usage)   # non-5 sonnet: no intro window
    assert cost["cache_write"] == 3.75 and cost["cache_read"] == 0.3


def test_unknown_model_returns_none_not_a_guess():
    assert estimate_cost_usd("somebody-elses-model", _MTOK) is None
    assert estimate_cost_usd("", _MTOK) is None


# --- custom pricing (the front door's optional fields) -----------------------

def test_custom_pricing_beats_the_table():
    # Even inside the sonnet-5 intro window, the player's own prices win.
    cost = estimate_cost_usd("claude-sonnet-5", _MTOK, on=datetime.date(2026, 7, 11),
                             custom={"input": 4.0, "output": 20.0})
    assert cost["input"] == 4.0 and cost["output"] == 20.0
    assert cost["total"] == 24.0


def test_custom_pricing_prices_a_model_the_table_never_heard_of():
    cost = estimate_cost_usd("claude-brand-new-model", _MTOK,
                             custom={"input": 1.5, "output": 7.5})
    assert cost["total"] == 9.0


def test_custom_pricing_derives_cache_rates_from_input():
    # Anthropic's standard ratios: cache write = 1.25x input, cache read = 0.1x.
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_creation_input_tokens": 1_000_000,
             "cache_read_input_tokens": 1_000_000}
    cost = estimate_cost_usd("claude-sonnet-5", usage, custom={"input": 4.0, "output": 20.0})
    assert cost["cache_write"] == 5.0 and cost["cache_read"] == 0.4


def test_malformed_custom_pricing_falls_back_to_the_table():
    on = datetime.date(2026, 7, 11)
    good = estimate_cost_usd("claude-haiku-4-5", _MTOK, on=on)
    assert estimate_cost_usd("claude-haiku-4-5", _MTOK, on=on,
                             custom={"input": "x", "output": 5}) == good
    assert estimate_cost_usd("claude-haiku-4-5", _MTOK, on=on, custom={}) == good
