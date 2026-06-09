"""Sound manager with lazy loading and graceful degradation."""

from __future__ import annotations

from pathlib import Path

from arena.util.settings import get_settings

SOUNDS_DIR = Path("assets") / "sounds"
MUSIC_DIR = Path("assets") / "music"

# Sentinel to distinguish "not yet looked up" from "looked up and missing"
_NOT_LOADED = object()


class SoundManager:
    """Manages sound loading, caching, and playback.

    Gracefully handles missing sound files and unavailable audio
    devices — the game works silently when no audio is present.
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        # Cache: sound_id -> Sound object, or None if file missing
        self._cache: dict[str, object] = {}
        self._current_track: str | None = None
        self._init_mixer()

    def _init_mixer(self) -> None:
        """Initialize pygame.mixer. Silently disables audio on failure."""
        try:
            import pygame.mixer
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._initialized = True
        except Exception:
            self._initialized = False

    def _load_sound(self, sound_id: str) -> object | None:
        """Load and cache a sound file. Returns None if missing."""
        if sound_id in self._cache:
            return self._cache[sound_id]

        if not self._initialized:
            self._cache[sound_id] = None
            return None

        import pygame.mixer

        # Try .wav first, then .ogg, then .mp3
        for ext in (".wav", ".ogg", ".mp3"):
            path = SOUNDS_DIR / f"{sound_id}{ext}"
            if path.exists():
                try:
                    sound = pygame.mixer.Sound(str(path))
                    self._cache[sound_id] = sound
                    return sound
                except Exception:
                    pass

        # File not found or failed to load
        self._cache[sound_id] = None
        return None

    def play_sfx(self, sound_id: str) -> None:
        """Play a sound effect at the current SFX volume.

        Silently does nothing if the sound file is missing or
        the audio system is unavailable.
        """
        if not self._initialized:
            return

        sound = self._load_sound(sound_id)
        if sound is None:
            return

        volume = self._get_sfx_volume()
        sound.set_volume(volume)
        sound.play()

    @property
    def current_track(self) -> str | None:
        """The filename of the currently playing music track, or None."""
        return self._current_track

    def play_music(self, filename: str, loops: int = -1) -> None:
        """Start background music (looping by default).

        Args:
            filename: Filename inside assets/music/ (e.g. "menu_music.mp3").
            loops: Number of repeats (-1 for infinite).
        """
        if not self._initialized:
            return

        import pygame.mixer

        path = MUSIC_DIR / filename
        if not path.exists():
            return

        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self._get_music_volume())
            pygame.mixer.music.play(loops)
            self._current_track = filename
        except Exception:
            pass

    def stop_music(self) -> None:
        """Stop any currently playing background music."""
        if not self._initialized:
            return

        import pygame.mixer

        try:
            pygame.mixer.music.stop()
            self._current_track = None
        except Exception:
            pass

    def _get_sfx_volume(self) -> float:
        """Calculate effective SFX volume: (master/100) * (sfx/100)."""
        s = get_settings().audio
        return (s.master_volume / 100.0) * (s.sfx_volume / 100.0)

    def _get_music_volume(self) -> float:
        """Calculate effective music volume: (master/100) * (music/100)."""
        s = get_settings().audio
        return (s.master_volume / 100.0) * (s.music_volume / 100.0)


_manager: SoundManager | None = None


def get_sound_manager() -> SoundManager:
    """Get or create the global SoundManager singleton."""
    global _manager
    if _manager is None:
        _manager = SoundManager()
    return _manager
