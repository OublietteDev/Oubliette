"""Difficulty settings (S1) — the model, the event-sourced persistence, and the
HTTP surface.

The contract: a preset label always means exactly its dial bundle (normalize
snaps them), hand-set dials store as 'custom', the settings survive reload via
DIFFICULTY_SET fold (last write wins), and the app exposes GET/PUT plus the
New Game path — changeable mid-campaign by design, including out of hardcore.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "difficulty-api.sqlite"))
os.environ.pop("ANTHROPIC_API_KEY", None)   # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import app  # noqa: E402
from oubliette.difficulty import (  # noqa: E402
    DEFAULT_DIFFICULTY,
    PRESET_DIALS,
    DifficultySettings,
    normalize_difficulty,
    preset_settings,
)
from oubliette.record.store import InMemoryEventStore  # noqa: E402
from oubliette.runtime.session import Session  # noqa: E402

client = TestClient(app)


# --- the model -------------------------------------------------------------

def test_default_is_adventure():
    assert DEFAULT_DIFFICULTY.preset == "adventure"
    assert DEFAULT_DIFFICULTY.encounter_challenge == "standard"
    assert DEFAULT_DIFFICULTY.rest_strictness == "gated"
    assert not DEFAULT_DIFFICULTY.hardcore


def test_a_preset_label_always_means_its_bundle():
    """A stored 'hardcore' can never secretly play like 'story': normalize snaps
    the dials to the label's bundle, whatever dials were sent alongside it."""
    lying = DifficultySettings(preset="hardcore", encounter_challenge="gentle",
                               rest_strictness="free", hardcore=False)
    stored = normalize_difficulty(lying)
    assert stored.preset == "hardcore"
    assert stored.encounter_challenge == "punishing"
    assert stored.rest_strictness == "dangerous"
    assert stored.pc_death and stored.companion_death and stored.hardcore


def test_custom_keeps_its_dials_and_unknown_labels_become_custom():
    mixed = DifficultySettings(preset="custom", encounter_challenge="punishing",
                               rest_strictness="free", pc_death=True)
    stored = normalize_difficulty(mixed)
    assert stored.preset == "custom"
    assert stored.encounter_challenge == "punishing" and stored.rest_strictness == "free"
    assert stored.pc_death and not stored.hardcore

    weird = normalize_difficulty(DifficultySettings(preset="nightmare", hardcore=True))
    assert weird.preset == "custom" and weird.hardcore


def test_every_preset_resolves_to_a_valid_settings_object():
    for name in PRESET_DIALS:
        s = preset_settings(name)
        assert s.preset == name
        assert s == normalize_difficulty(s)      # bundles are already normal
    assert preset_settings("no_such_thing").preset == "adventure"


# --- event-sourced persistence ----------------------------------------------

def test_difficulty_survives_reload_last_write_wins():
    store = InMemoryEventStore()
    session = Session.open(store)
    assert session.difficulty.preset == "adventure"    # the default, pre-choice

    session.emit_difficulty(DifficultySettings(preset="hardcore"), reason="new game")
    session.emit_difficulty(DifficultySettings(preset="story"), reason="settings edit")

    reopened = Session.open(store)
    assert reopened.difficulty.preset == "story"       # the LAST write is the law
    assert reopened.difficulty.rest_strictness == "free"


# --- the HTTP surface --------------------------------------------------------

def test_get_difficulty_serves_settings_and_presets():
    d = client.get("/api/difficulty").json()
    assert d["difficulty"]["preset"]
    assert set(PRESET_DIALS) <= set(d["presets"])
    assert "custom" in d["presets"]
    assert d["presets"]["hardcore"]["dials"]["hardcore"] is True
    assert d["presets"]["hardcore"]["blurb"]


def test_new_game_records_the_chosen_difficulty():
    res = client.post("/api/new", json={"difficulty": {"preset": "challenge"}}).json()
    assert res["ok"]
    d = client.get("/api/difficulty").json()["difficulty"]
    assert d["preset"] == "challenge"
    assert d["encounter_challenge"] == "punishing" and not d["hardcore"]


def test_debug_log_endpoint_serves_entries():
    assert client.post("/api/new", json={}).json()["ok"]
    d = client.get("/api/debug/log").json()
    assert "entries" in d and isinstance(d["entries"], list)


def test_settings_change_mid_campaign_including_out_of_hardcore():
    assert client.post("/api/new", json={"difficulty": {"preset": "hardcore"}}).json()["ok"]
    assert client.get("/api/difficulty").json()["difficulty"]["hardcore"] is True

    # "This isn't Elden Ring": the table may soften mid-campaign, hardcore included.
    res = client.put("/api/difficulty", json={"preset": "adventure"}).json()
    assert res["ok"] and res["difficulty"]["preset"] == "adventure"
    assert client.get("/api/difficulty").json()["difficulty"]["hardcore"] is False

    # A custom mix stores as sent, labeled custom.
    res = client.put("/api/difficulty", json={
        "preset": "custom", "encounter_challenge": "gentle",
        "rest_strictness": "dangerous", "pc_death": True,
        "companion_death": False, "hardcore": False}).json()
    got = res["difficulty"]
    assert got["preset"] == "custom" and got["encounter_challenge"] == "gentle"
    assert got["rest_strictness"] == "dangerous" and got["pc_death"] is True
