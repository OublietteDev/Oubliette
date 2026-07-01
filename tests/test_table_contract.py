"""The table contract: a per-campaign tone + content-boundary agreement.

It's configuration the code owns (event-sourced, replay-safe) and feeds into the
DM's resolve prompt every turn — the DM honors it, never sets it. These tests
cover the rendering, normalization, persistence/replay, and the prompt wiring.
"""

from __future__ import annotations

import asyncio

from oubliette.dm.brain import ASSESS_SYSTEM, RESOLVE_SYSTEM, Brain
from oubliette.enums import Tier, Verb
from oubliette.llm.client import ActResult, Msg
from oubliette.record.rng import Rng
from oubliette.record.store import InMemoryEventStore, SqliteEventStore
from oubliette.runtime.loop import TurnLoop
from oubliette.runtime.session import Session
from oubliette.schemas import Intent, TurnAssessment
from oubliette.table import (DEFAULT_TABLE, TONE_PRESETS, TableContract,
                             normalize_contract, render_table_prompt)


# --- rendering --------------------------------------------------------------
def test_default_table_renders_nothing():
    assert render_table_prompt(DEFAULT_TABLE) == ""


def test_tone_preset_renders():
    out = render_table_prompt(TableContract(tone_label="Gritty"))
    assert "TONE:" in out
    assert TONE_PRESETS["Gritty"] in out


def test_lines_veils_freeform_render():
    out = render_table_prompt(TableContract(
        lines=["graphic torture"], veils=["romance"], freeform="keep it PG-13"))
    assert "LINES" in out and "graphic torture" in out
    assert "VEILS" in out and "romance" in out
    assert "keep it PG-13" in out
    # boundaries present → the force_end_session backstop is mentioned
    assert "force_end_session" in out


def test_freeform_only_skips_boundary_backstop():
    out = render_table_prompt(TableContract(freeform="lots of tavern songs"))
    assert "lots of tavern songs" in out
    assert "force_end_session" not in out   # no lines/veils → no boundary-enforcement note


# --- normalization ----------------------------------------------------------
def test_normalize_snaps_preset_tone_text():
    stored = normalize_contract(TableContract(tone_label="Ominous", tone_text="ignored"))
    assert stored.tone_text == TONE_PRESETS["Ominous"]


def test_normalize_keeps_custom_tone_text():
    stored = normalize_contract(TableContract(tone_label="Custom", tone_text="  noir, terse  "))
    assert stored.tone_label == "Custom"
    assert stored.tone_text == "noir, terse"


def test_normalize_drops_blanks_and_unknown_label():
    stored = normalize_contract(TableContract(
        tone_label="Nonsense", lines=["  ", "real one", ""], veils=[], freeform="  "))
    assert stored.tone_label == "Balanced"
    assert stored.lines == ["real one"]
    assert stored.freeform == ""


# --- persistence / replay ---------------------------------------------------
def test_contract_persists_across_reload(tmp_path):
    db = str(tmp_path / "save.sqlite")
    store = SqliteEventStore(db)
    session = Session.open(store)
    session.emit_contract(TableContract(tone_label="Cinematic", lines=["self-harm"]))
    store.close()

    reopened = Session.open(SqliteEventStore(db))
    assert reopened.table.tone_label == "Cinematic"
    assert reopened.table.tone_text == TONE_PRESETS["Cinematic"]
    assert reopened.table.lines == ["self-harm"]


def test_last_contract_wins_on_replay():
    store = InMemoryEventStore()
    session = Session.open(store)
    session.emit_contract(TableContract(tone_label="Gritty"))
    session.emit_contract(TableContract(tone_label="Whimsical", veils=["gore"]))
    reopened = Session.open(store)
    assert reopened.table.tone_label == "Whimsical"
    assert reopened.table.veils == ["gore"]


# --- prompt wiring (full loop) ----------------------------------------------
class _CapturingClient:
    """An LLMClient double that records the system prompt of each call and returns
    a benign, roll-free assessment then a trivial resolution."""

    def __init__(self) -> None:
        self.assess_system = ""
        self.resolve_system = ""

    async def complete(self, *, system, messages, schema, on_text=None):
        if schema is TurnAssessment:
            self.assess_system = system
            return TurnAssessment(
                intent=Intent(raw_text="look", verb=Verb.SKILL_CHECK),
                tier=Tier.FREESTYLE, requires_roll=False)
        raise AssertionError(f"unexpected schema {schema}")

    async def act(self, *, system, messages, tools, on_text=None):
        # The resolve turn is now the streaming, tool_choice:auto `act` call (W6).
        self.resolve_system = system
        return ActResult(narration="You take in the square.")


def test_contract_reaches_resolve_prompt_only():
    store = InMemoryEventStore()
    session = Session.open(store)
    session.emit_contract(TableContract(tone_label="Gritty", lines=["graphic torture"]))
    client = _CapturingClient()
    loop = TurnLoop(session, Rng(seed=1, record=session.emit_log), Brain(client))

    asyncio.run(loop.take_turn("I look around the square."))

    # tone + boundaries land in the resolve system prompt, atop the base prompt
    assert RESOLVE_SYSTEM in client.resolve_system
    assert TONE_PRESETS["Gritty"] in client.resolve_system
    assert "graphic torture" in client.resolve_system
    # assess stays lean — classification needs no tone/boundaries
    assert client.assess_system == ASSESS_SYSTEM
    assert "graphic torture" not in client.assess_system
