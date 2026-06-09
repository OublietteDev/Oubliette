"""Test fixtures for The Arena's suite.

The Arena reads its content and assets via cwd-relative paths (``Path("data")``,
``Path("assets")``) — a holdover from when it ran standalone with cwd at its project
root. Rather than rewrite ~68 test files, we pin cwd to the Arena package root for the
duration of each Arena test, so a single ``pytest`` run from the repo root works for
both Oubliette (cwd-root) and Arena (cwd-arena) suites. (Source-side path anchoring,
needed to launch the Arena from an arbitrary cwd, lands in the integration stage.)

We also force pygame's dummy video/audio drivers before pygame is imported, so the
GUI/audio tests run headless on a machine with no display or sound device.
"""

import os

import pytest

# Headless pygame: set before any pygame import happens during collection.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# The Arena package root (this file is arena/tests/conftest.py → parent.parent = arena/).
_ARENA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _arena_cwd(monkeypatch):
    """Run every Arena test with cwd at the Arena root so ``Path("data")`` /
    ``Path("assets")`` resolve. monkeypatch.chdir auto-reverts after each test, so
    Oubliette's cwd-root tests are unaffected."""
    monkeypatch.chdir(_ARENA_ROOT)
