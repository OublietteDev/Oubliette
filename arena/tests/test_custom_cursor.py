"""The custom cursor as the one shared table pointer — headless unit tests.

The cursor is drawn where the last positioned mouse EVENT said, not where
``pygame.mouse.get_pos()`` claims: remote players' input arrives as
synthesized events via the multiplayer bridge, and the OS-level cursor warp
can't reach an unfocused or covered window (the wand used to freeze in the
top-left corner for everyone watching from a browser). These tests pin the
event-fed contract at both ends of the seam: the manager draws at the noted
position, and every positioned event the bridge synthesizes carries a ``pos``
for the App to feed it.
"""

from __future__ import annotations

import pygame
import pytest

from arena.gui.custom_cursor import CustomCursorManager
from arena.stream import Bridge


@pytest.fixture(autouse=True, scope="module")
def _pygame():
    pygame.init()          # event synthesis + surfaces (dummy driver)
    yield


RED = (255, 0, 0, 255)


def _manager_with_cursor() -> CustomCursorManager:
    """A manager holding a tiny solid-red cursor, no assets folder needed."""
    mgr = CustomCursorManager("Random", animations_enabled=False)
    cur = pygame.Surface((4, 4), pygame.SRCALPHA)
    cur.fill(RED)
    mgr._cursor_surface = cur
    return mgr


def test_cursor_draws_at_the_noted_position():
    mgr = _manager_with_cursor()
    board = pygame.Surface((64, 64), pygame.SRCALPHA)
    mgr.note_pos(20, 30)
    mgr.render(board)
    assert board.get_at((20, 30)) == RED           # drawn where the event said
    assert board.get_at((0, 0)) != RED             # not stuck in the corner


def test_noting_a_new_position_moves_the_cursor():
    mgr = _manager_with_cursor()
    mgr.note_pos(20, 30)
    mgr.note_pos(50, 10)                           # whoever moved last, wins
    board = pygame.Surface((64, 64), pygame.SRCALPHA)
    mgr.render(board)
    assert board.get_at((50, 10)) == RED
    assert board.get_at((20, 30)) != RED


def test_every_positioned_bridge_event_can_feed_the_cursor():
    """The App's plumbing is `if hasattr(event, "pos"): note_pos(*event.pos)` —
    so the bridge's synthesized clicks and moves must all carry one."""
    b = Bridge("ws://127.0.0.1:1/ws/arena?token=t")
    mgr = _manager_with_cursor()
    for msg in ({"k": "down", "x": 100, "y": 200, "b": 1},
                {"k": "up", "x": 100, "y": 200, "b": 1},
                {"k": "move", "x": 300, "y": 40}):
        for event in b._events_for(msg):
            assert hasattr(event, "pos")
            mgr.note_pos(*event.pos)
        assert mgr._pos == (msg["x"], msg["y"])
