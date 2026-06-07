"""The Forge — C1 (open & check). In-process tests via FastAPI's TestClient.

Pins the C1 contract: list worlds, open one read-only, and report validity using
the GAME's loader — so The Forge's ✓/⚠ and the game's load agree by construction.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from oubliette.creator.server import app

client = TestClient(app)


def test_lists_brightvale_as_ready():
    r = client.get("/api/packs")
    assert r.status_code == 200
    packs = {p["id"]: p for p in r.json()["packs"]}
    assert "brightvale" in packs
    bv = packs["brightvale"]
    assert bv["ok"] is True and bv["issue_count"] == 0
    assert bv["name"] == "The Brightvale Market"


def test_open_pack_returns_contents_and_validation():
    r = client.get("/api/pack/brightvale")
    assert r.status_code == 200
    data = r.json()
    assert data["validation"]["ok"] is True
    # the five world pieces are present and readable
    c = data["contents"]
    assert any(it["id"] == "merchant_thom" for it in c["npcs"])
    assert any(it["id"] == "boots" for it in c["items"])
    assert c["pack"]["name"] == "The Brightvale Market"


def test_unknown_pack_is_404():
    assert client.get("/api/pack/does_not_exist").status_code == 404


def test_path_traversal_is_refused():
    # an id that tries to climb out of the packs root must not resolve
    assert client.get("/api/pack/..").status_code == 404


def test_broken_pack_reports_issues(tmp_path, monkeypatch):
    """Point The Forge at a temp packs root holding a deliberately broken world;
    the validity report must surface the loader's aggregated issues."""
    d = tmp_path / "broken"
    d.mkdir()
    (d / "pack.json").write_text(json.dumps({
        "id": "broken", "schema_version": 1, "name": "Broken World",
        "version": "0.1.0", "entry_scenario": "missing"}), encoding="utf-8")
    (d / "npcs.json").write_text(json.dumps([
        {"id": "n", "name": "N", "home_location": "nowhere"}]), encoding="utf-8")
    monkeypatch.setenv("OUBLIETTE_PACKS_ROOT", str(tmp_path))

    listing = {p["id"]: p for p in client.get("/api/packs").json()["packs"]}
    assert listing["broken"]["ok"] is False
    assert listing["broken"]["issue_count"] >= 1

    report = client.get("/api/pack/broken").json()["validation"]
    assert report["ok"] is False
    assert any("nowhere" in i for i in report["issues"])
