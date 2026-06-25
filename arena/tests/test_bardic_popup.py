"""Event-handling tests for the Bardic Inspiration spend popup (GUI).

Rendering needs a display, so only the input mapping is exercised here — the
manager-side pause/resume is covered in test_bardic.py (TestBardicAttackPrompt).
"""
import pygame
import pytest

from arena.gui.bardic_popup import BardicInspirationPopup, BardicChoice

pygame.init()


@pytest.fixture
def popup():
    p = BardicInspirationPopup("Fighter", die_size=8, total_roll=14, target_ac=16)
    p.reposition((400, 300))
    return p


def _click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


def test_clicking_spend_returns_use_true(popup):
    assert popup.handle_event(_click(popup._get_use_rect().center)) == BardicChoice(use=True)


def test_clicking_skip_returns_use_false(popup):
    assert popup.handle_event(_click(popup._get_skip_rect().center)) == BardicChoice(use=False)


def test_clicking_outside_is_skip(popup):
    assert popup.handle_event(_click((5, 5))) == BardicChoice(use=False)


def test_escape_is_skip(popup):
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    assert popup.handle_event(esc) == BardicChoice(use=False)


def test_motion_keeps_popup_open(popup):
    motion = pygame.event.Event(pygame.MOUSEMOTION, pos=popup._get_use_rect().center, rel=(0, 0), buttons=(0, 0, 0))
    assert popup.handle_event(motion) is None
    assert popup._hovered_use is True
