"""Application settings with JSON persistence.

Provides a singleton AppSettings object that all modules can import
via get_settings(). Settings are loaded from data/settings.json on
first access, falling back to defaults if the file is missing or corrupt.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


SETTINGS_PATH = Path("data") / "settings.json"


class GameplaySettings(BaseModel):
    """Gameplay-related settings."""

    ai_step_delay: int = Field(default=500, ge=100, le=2000)
    ai_thinking_delay: int = Field(default=300, ge=100, le=2000)
    ai_randomness: float = Field(default=0.1, ge=0.0, le=1.0)
    show_ai_thinking: bool = True


class DisplaySettings(BaseModel):
    """Display-related settings."""

    show_hex_coordinates: bool = False
    # Battle-map background image opacity (%). Players turn it down when the
    # art makes terrain hexes hard to read; 0 = plain field.
    battle_background_opacity: int = Field(default=100, ge=0, le=100)
    default_hex_size: int = Field(default=40, ge=20, le=80)
    zoom_speed: float = Field(default=1.1, ge=1.01, le=1.5)
    token_radius: int = Field(default=26, ge=8, le=40)
    cursor: str = "Random"
    cursor_animations: bool = True


class AudioSettings(BaseModel):
    """Audio-related settings (for future sound system)."""

    master_volume: int = Field(default=80, ge=0, le=100)
    sfx_volume: int = Field(default=80, ge=0, le=100)
    music_volume: int = Field(default=50, ge=0, le=100)


class SystemSettings(BaseModel):
    """System-related settings."""

    resolution: str = "1280x720"
    auto_scroll_combat_log: bool = True


class AppSettings(BaseModel):
    """Top-level settings container."""

    gameplay: GameplaySettings = Field(default_factory=GameplaySettings)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    system: SystemSettings = Field(default_factory=SystemSettings)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    """Get the global settings singleton. Loads from disk on first access."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def load_settings() -> AppSettings:
    """Load settings from data/settings.json, returning defaults on failure."""
    global _settings
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _settings = AppSettings.model_validate(data)
        except Exception:
            _settings = AppSettings()
    else:
        _settings = AppSettings()
    return _settings


def save_settings() -> None:
    """Persist current settings to data/settings.json."""
    settings = get_settings()
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings.model_dump(mode="json"), f, indent=2)


def reset_settings() -> AppSettings:
    """Reset all settings to defaults and return the fresh object."""
    global _settings
    _settings = AppSettings()
    return _settings
