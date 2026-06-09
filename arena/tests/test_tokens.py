"""Tests for token rendering, image caching, and condition display."""

import os
import tempfile

import pygame
import pytest

from arena.gui.token_cache import (
    get_token_image,
    clear_cache,
    get_cache_size,
    _scale_and_clip_circle,
)
from arena.gui.tokens import _get_initials
from arena.models.character import Creature
from arena.models.conditions import Condition, AppliedCondition
from arena.util.constants import CONDITION_DISPLAY, COLORS


@pytest.fixture(autouse=True)
def init_pygame():
    """Initialize and teardown pygame for each test."""
    pygame.init()
    pygame.display.set_mode((1, 1))  # Needed for convert_alpha()
    yield
    clear_cache()
    pygame.quit()


# ------------------------------------------------------------------
# _get_initials
# ------------------------------------------------------------------


class TestGetInitials:
    """Tests for the _get_initials helper."""

    def test_single_word_name(self):
        assert _get_initials("Goblin") == "G"

    def test_two_word_name(self):
        assert _get_initials("Thorin Ironforge") == "TI"

    def test_multi_word_name_uses_first_and_last(self):
        """Multi-word names should use first and last initials."""
        assert _get_initials("Grak the Sneaky") == "GS"

    def test_empty_name_returns_question_mark(self):
        assert _get_initials("") == "?"


# ------------------------------------------------------------------
# Token image cache
# ------------------------------------------------------------------


class TestTokenImageCache:
    """Tests for the token image cache module."""

    def test_cache_starts_empty(self):
        clear_cache()
        assert get_cache_size() == 0

    def test_nonexistent_path_returns_none(self):
        result = get_token_image("nonexistent/path/image.png", 36)
        assert result is None

    def test_nonexistent_path_is_cached(self):
        """Failed loads should be cached to prevent repeated disk I/O."""
        clear_cache()
        get_token_image("nonexistent/path/image.png", 36)
        assert get_cache_size() == 1

    def test_clear_cache_empties_all(self):
        get_token_image("nonexistent/file.png", 36)
        assert get_cache_size() > 0
        clear_cache()
        assert get_cache_size() == 0

    def test_different_sizes_cached_separately(self):
        """Same path at different diameters should produce separate entries."""
        clear_cache()
        get_token_image("nonexistent/file.png", 36)
        get_token_image("nonexistent/file.png", 72)
        assert get_cache_size() == 2

    def test_same_key_hits_cache(self):
        """Repeated calls with identical args should not add entries."""
        clear_cache()
        get_token_image("nonexistent/file.png", 36)
        get_token_image("nonexistent/file.png", 36)
        assert get_cache_size() == 1

    def test_valid_image_returns_surface(self):
        """A valid image file should load and return a Surface."""
        # Create a temporary PNG image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # Create a small test image and save it
            test_surf = pygame.Surface((20, 20), pygame.SRCALPHA)
            test_surf.fill((255, 0, 0, 255))
            pygame.image.save(test_surf, tmp_path)

            clear_cache()
            result = get_token_image(tmp_path, 36)
            assert result is not None
            assert isinstance(result, pygame.Surface)
            assert result.get_size() == (36, 36)
        finally:
            os.unlink(tmp_path)

    def test_valid_image_is_cached(self):
        """A successfully loaded image should be cached."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            test_surf = pygame.Surface((20, 20), pygame.SRCALPHA)
            test_surf.fill((0, 255, 0, 255))
            pygame.image.save(test_surf, tmp_path)

            clear_cache()
            get_token_image(tmp_path, 36)
            assert get_cache_size() == 1
        finally:
            os.unlink(tmp_path)

    def test_zero_diameter_returns_none(self):
        """Diameter below 1 should return None immediately."""
        result = get_token_image("any_path.png", 0)
        assert result is None


# ------------------------------------------------------------------
# _scale_and_clip_circle
# ------------------------------------------------------------------


class TestScaleAndClipCircle:
    """Tests for the image scaling and circular clipping helper."""

    def test_output_size_matches_diameter(self):
        source = pygame.Surface((100, 100), pygame.SRCALPHA)
        source.fill((255, 0, 0, 255))
        result = _scale_and_clip_circle(source, 36)
        assert result.get_size() == (36, 36)

    def test_output_has_alpha_channel(self):
        source = pygame.Surface((50, 50), pygame.SRCALPHA)
        source.fill((255, 0, 0, 255))
        result = _scale_and_clip_circle(source, 36)
        assert result.get_flags() & pygame.SRCALPHA

    def test_corners_are_transparent(self):
        """Corners should be fully transparent (outside the circle)."""
        source = pygame.Surface((100, 100), pygame.SRCALPHA)
        source.fill((255, 0, 0, 255))
        result = _scale_and_clip_circle(source, 40)
        corner = result.get_at((0, 0))
        assert corner.a == 0

    def test_center_is_opaque(self):
        """Center pixel should be opaque (inside the circle)."""
        source = pygame.Surface((100, 100), pygame.SRCALPHA)
        source.fill((255, 0, 0, 255))
        result = _scale_and_clip_circle(source, 40)
        center = result.get_at((20, 20))
        assert center.a > 0

    def test_non_square_image_preserves_aspect(self):
        """A non-square source should scale within the diameter."""
        source = pygame.Surface((200, 100), pygame.SRCALPHA)
        source.fill((0, 255, 0, 255))
        result = _scale_and_clip_circle(source, 50)
        assert result.get_size() == (50, 50)

    def test_minimum_diameter_clamps_to_one(self):
        """Diameter of 0 should clamp to 1x1."""
        source = pygame.Surface((10, 10), pygame.SRCALPHA)
        result = _scale_and_clip_circle(source, 0)
        assert result.get_size() == (1, 1)


# ------------------------------------------------------------------
# Condition display metadata
# ------------------------------------------------------------------


class TestConditionDisplay:
    """Tests for the CONDITION_DISPLAY constant."""

    def test_all_conditions_have_display_entry(self):
        """Every Condition enum value should have a CONDITION_DISPLAY entry."""
        for cond in Condition:
            assert cond.value in CONDITION_DISPLAY, (
                f"Missing CONDITION_DISPLAY entry for '{cond.value}'"
            )

    def test_abbreviations_are_one_or_two_chars(self):
        for cond_value, (abbrev, _) in CONDITION_DISPLAY.items():
            assert 1 <= len(abbrev) <= 2, (
                f"Abbreviation '{abbrev}' for '{cond_value}' is not 1-2 chars"
            )

    def test_color_keys_exist_in_colors(self):
        for cond_value, (_, color_key) in CONDITION_DISPLAY.items():
            assert color_key in COLORS, (
                f"Color key '{color_key}' for '{cond_value}' not found in COLORS"
            )

    def test_debuff_conditions_use_debuff_color(self):
        debuffs = ["blinded", "poisoned", "stunned", "paralyzed", "frightened"]
        for d in debuffs:
            _, color_key = CONDITION_DISPLAY[d]
            assert color_key == "condition_debuff"

    def test_buff_conditions_use_buff_color(self):
        buffs = ["dodging", "helped"]
        for b in buffs:
            _, color_key = CONDITION_DISPLAY[b]
            assert color_key == "condition_buff"


# ------------------------------------------------------------------
# Hover tooltip data flow
# ------------------------------------------------------------------


class TestHoverTooltipData:
    """Tests for the data extraction used by hover tooltips."""

    def test_creature_conditions_produce_names(self):
        """Active conditions should be extractable as capitalized names."""
        creature = Creature(
            name="Test",
            max_hit_points=20,
            active_conditions=[
                AppliedCondition(condition=Condition.POISONED, source="Spider"),
                AppliedCondition(condition=Condition.PRONE, source="Trip"),
            ],
        )
        cond_names = [
            ac.condition.value.capitalize()
            for ac in creature.active_conditions
        ]
        assert cond_names == ["Poisoned", "Prone"]

    def test_creature_without_conditions_gives_empty_list(self):
        creature = Creature(name="Test", max_hit_points=20)
        assert len(creature.active_conditions) == 0
