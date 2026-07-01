"""The shared house-style tokens (UI pass, Stage 1): BOTH web servers serve the
SAME oubliette/ui/tokens.css as /tokens.css, and each page <link>s it instead of
carrying its own :root palette — so the two UIs cannot drift apart palette-first.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from oubliette.app.server import app as play_app
from oubliette.creator.server import app as forge_app

TOKENS = (Path(__file__).resolve().parents[1] / "oubliette" / "ui" / "tokens.css").read_text(encoding="utf-8")


def _check(client: TestClient) -> None:
    r = client.get("/tokens.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert r.text == TOKENS                       # byte-identical: the ONE file, both doors


def test_play_app_serves_the_shared_tokens():
    _check(TestClient(play_app))


def test_forge_serves_the_shared_tokens():
    _check(TestClient(forge_app))


def test_tokens_carry_the_house_palette():
    for token in ("--gold:", "--accent:", "--bad-soft:", "--btn-grad:",
                  "--opacity-disabled:", "--serif:"):
        assert token in TOKENS


def test_neither_page_redefines_the_palette_inline():
    """The :root block lives ONLY in tokens.css — an inline copy in either page
    would shadow the shared file and reopen the drift this stage closed."""
    for page in ("oubliette/app/static/index.html", "oubliette/creator/static/index.html"):
        html = (Path(__file__).resolve().parents[1] / page).read_text(encoding="utf-8")
        assert '<link rel="stylesheet" href="/tokens.css" />' in html
        assert ":root {" not in html
