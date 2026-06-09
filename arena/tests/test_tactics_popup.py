"""Tests for the tactics popup."""

import pytest
import pygame

from arena.gui.tactics_popup import TacticsPopup, _TACTICS


class TestTacticsPopup:
    """Test the tactics popup panel."""

    @pytest.fixture(autouse=True)
    def init_pygame(self):
        pygame.init()
        pygame.display.set_mode((1, 1))
        yield
        pygame.quit()

    def test_all_six_tactics_present(self):
        """All six standard tactical actions should be listed."""
        names = [name for name, _ in _TACTICS]
        assert "Dash" in names
        assert "Disengage" in names
        assert "Dodge" in names
        assert "Help" in names
        assert "Hide" in names
        assert "Shove" in names
        assert len(names) == 6

    def test_popup_creation(self):
        popup = TacticsPopup(action_used=False)
        assert popup.rect.width == TacticsPopup.WIDTH
        assert popup.hovered_index is None

    def test_popup_creation_disabled(self):
        popup = TacticsPopup(action_used=True)
        assert popup.action_used is True

    def test_reposition_right_side(self):
        popup = TacticsPopup(action_used=False, screen_width=1280, screen_height=720)
        popup.reposition((400, 300), 100)
        # Should be to the right of center
        assert popup.rect.x > 400

    def test_reposition_flips_left_near_edge(self):
        popup = TacticsPopup(action_used=False, screen_width=1280, screen_height=720)
        popup.reposition((1200, 300), 100)
        # Should flip to the left side
        assert popup.rect.x < 1200

    def test_entry_at_returns_correct_index(self):
        popup = TacticsPopup(action_used=False)
        popup.reposition((400, 300), 100)

        # Click on first entry area
        entry_y = popup.rect.y + popup.TITLE_HEIGHT + 5
        idx = popup._entry_at((popup.rect.x + 10, entry_y))
        assert idx == 0

    def test_entry_at_returns_none_outside(self):
        popup = TacticsPopup(action_used=False)
        popup.reposition((400, 300), 100)
        idx = popup._entry_at((0, 0))
        assert idx is None
