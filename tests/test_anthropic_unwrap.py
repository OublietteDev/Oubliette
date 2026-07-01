"""Regression: the Anthropic adapter tolerates a bogus single-key tool-input envelope.

As of 2026-07, claude-sonnet-5 intermittently wraps its forced-tool input under a lone
key ('parameters'/'parameter') instead of returning the schema's fields at top level. That
broke EVERY live turn (assess + resolve both go through the forced `emit` tool). `_coerce_input`
unwraps one such envelope when the direct shape doesn't validate; here we pin that behavior
without touching the network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oubliette.llm.anthropic_client import _coerce_input
from oubliette.schemas import TurnAssessment, TurnResolution


def _assessment_fields() -> dict:
    return {"intent": {"raw_text": "I look around the market.", "verb": "skill_check",
                       "skill": "perception"}, "tier": "authored", "requires_roll": False}


def test_well_formed_input_validates_unchanged():
    got = _coerce_input(TurnAssessment, _assessment_fields())
    assert got.intent.raw_text == "I look around the market."
    assert got.tier.value == "authored"


def test_parameters_envelope_is_unwrapped():
    wrapped = {"parameters": _assessment_fields()}          # the exact live shape observed
    got = _coerce_input(TurnAssessment, wrapped)
    assert got.intent.verb.value == "skill_check"


def test_singular_parameter_envelope_is_unwrapped():
    wrapped = {"parameter": _assessment_fields()}           # the key name is not even stable
    assert _coerce_input(TurnAssessment, wrapped).tier.value == "authored"


def test_resolution_envelope_is_unwrapped():
    wrapped = {"parameters": {"narration": "The market bustles.", "tool_calls": []}}
    assert _coerce_input(TurnResolution, wrapped).narration == "The market bustles."


def test_genuinely_invalid_input_still_raises():
    # A single-key envelope whose contents are ALSO wrong must not be silently accepted.
    with pytest.raises(ValidationError):
        _coerce_input(TurnAssessment, {"parameters": {"nonsense": 1}})
    with pytest.raises(ValidationError):
        _coerce_input(TurnAssessment, {"intent": "not-an-object"})
