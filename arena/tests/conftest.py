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
import sys

import pytest

# Headless pygame: set before any pygame import happens during collection.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Keep numpy OUT of the test process. pygame eagerly imports numpy when it can
# (optional array support), and pygame 2.6.1 + numpy 2.x in one process corrupts
# memory — SDL_ttf font calls start access-violating several init/quit cycles
# later (surfaced 2026-07-09 when the narration arc's kokoro-onnx brought numpy
# into the venv; the crash reproduced with numpy installed and vanished without
# it). The Arena itself never imports numpy, and the game runs the Arena in its
# own subprocess, so blocking it here changes nothing but the tests' stability.
# (A None entry makes `import numpy` raise ImportError; pygame degrades cleanly.)
# The block is needed only while pygame IMPORTS: its optional numpy support
# binds at pygame-import time and never re-probes. Every arena test module
# imports pygame during collection, so once collection ends the quarantine can
# lift — Oubliette tests that need real numpy (the qwen narrator's, N3) then
# import it freely, and pygame stays numpy-blind for the whole run. (Verified
# 2026-07-09: the SDL_ttf font crash stays gone with the post-collection lift;
# it was pygame's numpy binding, not mere coexistence.)
if "numpy" not in sys.modules:
    sys.modules["numpy"] = None  # type: ignore[assignment]
    _numpy_quarantined = True
else:
    _numpy_quarantined = False


def pytest_collection_finish(session):
    if _numpy_quarantined and sys.modules.get("numpy") is None:
        del sys.modules["numpy"]     # pygame is loaded (numpy-blind) — safe now

# The Arena package root (this file is arena/tests/conftest.py → parent.parent = arena/).
_ARENA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _arena_cwd(monkeypatch):
    """Run every Arena test with cwd at the Arena root so ``Path("data")`` /
    ``Path("assets")`` resolve. monkeypatch.chdir auto-reverts after each test, so
    Oubliette's cwd-root tests are unaffected."""
    monkeypatch.chdir(_ARENA_ROOT)
