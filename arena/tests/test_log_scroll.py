"""Regression: combat-log mouse-wheel direction (OublietteDev, 2026-07-01).

The log's `scroll_offset` is anchored to the BOTTOM (0 = newest event visible,
larger = further back in history) — unlike the top-anchored creature-info panel.
The wheel handler originally subtracted `event.y` (the top-anchored convention),
which inverted the feel: wheel-up walked TOWARD the newest entry. Wheel-up must
scroll BACK into history (offset grows); wheel-down must return to the live tail.
"""

import pygame

from arena.gui.panels.log import CombatLogPanel


class _FakeLog:
    """Only `events` (its length, under the ALL filter) matters to scrolling."""

    def __init__(self, n: int) -> None:
        self.events = [None] * n


def _panel(events: int = 100) -> CombatLogPanel:
    panel = CombatLogPanel(pygame.Rect(0, 0, 300, 120))
    panel.set_log(_FakeLog(events))
    return panel


def _wheel(panel: CombatLogPanel, y: int, monkeypatch) -> None:
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: panel.rect.center)
    panel.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, {"y": y}))


def test_wheel_up_scrolls_back_into_history(monkeypatch):
    panel = _panel()
    _wheel(panel, +1, monkeypatch)          # wheel up = away from the user
    assert panel.scroll_offset > 0          # older events come into view


def test_wheel_down_returns_toward_the_newest(monkeypatch):
    panel = _panel()
    panel.scroll_offset = 6                 # somewhere back in history
    _wheel(panel, -1, monkeypatch)
    assert panel.scroll_offset < 6


def test_wheel_down_at_the_tail_stays_at_the_tail(monkeypatch):
    panel = _panel()
    _wheel(panel, -1, monkeypatch)
    assert panel.scroll_offset == 0         # never negative


def test_wheel_up_clamps_at_the_oldest_event(monkeypatch):
    # A 120px panel shows 5 lines (92px content — title bar + bottom pad —
    # / 16px lines): 10 events leave exactly 5 lines of history to scroll
    # back through, and no further.
    panel = _panel(events=10)
    for _ in range(50):
        _wheel(panel, +1, monkeypatch)
    assert panel.scroll_offset == 5

    panel = _panel(events=3)                # everything fits -> nothing to scroll
    for _ in range(50):
        _wheel(panel, +1, monkeypatch)
    assert panel.scroll_offset == 0
