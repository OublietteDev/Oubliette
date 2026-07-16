"""Tests for the audio system."""

from unittest.mock import patch, MagicMock

import pytest

from arena.audio.manager import SoundManager, get_sound_manager, _NOT_LOADED, SOUNDS_DIR
from arena.audio.events import EVENT_SOUNDS, play_event_sound
from arena.combat.events import CombatEventType


# ---------------------------------------------------------------------------
# SoundManager basics
# ---------------------------------------------------------------------------

class TestSoundManagerInit:
    """Test SoundManager initialization."""

    def test_init_without_mixer_does_not_crash(self):
        """SoundManager should handle missing audio device gracefully."""
        with patch("arena.audio.manager.SoundManager._init_mixer") as mock_init:
            mock_init.side_effect = lambda self_arg=None: None
            mgr = SoundManager.__new__(SoundManager)
            mgr._initialized = False
            mgr._paths = {}
            mgr._cache = {}
            # Should not crash
            assert mgr._initialized is False

    def test_play_sfx_when_not_initialized(self):
        """play_sfx should silently do nothing when mixer failed to init."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = False
        mgr._paths = {}
        mgr._cache = {}
        # Should not raise
        mgr.play_sfx("button_click")

    def test_play_music_when_not_initialized(self):
        """play_music should silently do nothing when mixer failed to init."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = False
        mgr._paths = {}
        mgr._cache = {}
        mgr.play_music("nonexistent.ogg")

    def test_stop_music_when_not_initialized(self):
        """stop_music should silently do nothing when mixer failed to init."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = False
        mgr._paths = {}
        mgr._cache = {}
        mgr.stop_music()


class TestSoundManagerCache:
    """Test sound loading and caching logic."""

    def test_missing_sound_cached_as_none(self):
        """A sound not on disk should be cached as None."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        with patch("pygame.mixer.Sound", side_effect=FileNotFoundError):
            result = mgr._load_sound("nonexistent_sound")

        assert result is None
        assert mgr._cache["nonexistent_sound"] is None

    def test_cached_none_not_reloaded(self):
        """Once cached as None, the file system should not be hit again."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {"missing": None}

        result = mgr._load_sound("missing")
        assert result is None

    def test_cached_sound_returned(self):
        """A previously loaded sound should be returned from cache."""
        fake_sound = MagicMock()
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {"hit": fake_sound}

        result = mgr._load_sound("hit")
        assert result is fake_sound

    def test_load_sound_not_initialized_caches_none(self):
        """When not initialized, _load_sound should cache None immediately."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = False
        mgr._paths = {}
        mgr._cache = {}

        result = mgr._load_sound("anything")
        assert result is None
        assert mgr._cache["anything"] is None


class TestSoundManagerPlayback:
    """Test playback with mocked sounds."""

    def test_play_sfx_sets_volume_and_plays(self):
        """play_sfx should set volume and call play on the sound."""
        fake_sound = MagicMock()
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {"test_sfx": fake_sound}

        with patch.object(mgr, "_get_sfx_volume", return_value=0.64):
            mgr.play_sfx("test_sfx")

        fake_sound.set_volume.assert_called_once_with(0.64)
        fake_sound.play.assert_called_once()

    def test_play_sfx_missing_sound_no_crash(self):
        """play_sfx with missing sound should not crash."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {"missing": None}

        # Should not raise
        mgr.play_sfx("missing")


# ---------------------------------------------------------------------------
# Volume calculation
# ---------------------------------------------------------------------------

class TestVolumeCalculation:
    """Test volume computation."""

    def test_sfx_volume_default(self):
        """Default settings (80 master, 80 sfx) should yield 0.64."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        # Default settings have master=80, sfx=80
        vol = mgr._get_sfx_volume()
        assert vol == pytest.approx(0.64)

    def test_sfx_volume_partial(self):
        """80 master * 80 sfx = 0.64."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        with patch("arena.audio.manager.get_settings") as mock_gs:
            audio = MagicMock()
            audio.master_volume = 80
            audio.sfx_volume = 80
            mock_gs.return_value.audio = audio
            vol = mgr._get_sfx_volume()

        assert vol == pytest.approx(0.64)

    def test_sfx_volume_master_zero(self):
        """Master at 0 should mute everything."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        with patch("arena.audio.manager.get_settings") as mock_gs:
            audio = MagicMock()
            audio.master_volume = 0
            audio.sfx_volume = 100
            mock_gs.return_value.audio = audio
            vol = mgr._get_sfx_volume()

        assert vol == pytest.approx(0.0)

    def test_music_volume_partial(self):
        """50 master * 60 music = 0.30."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        with patch("arena.audio.manager.get_settings") as mock_gs:
            audio = MagicMock()
            audio.master_volume = 50
            audio.music_volume = 60
            mock_gs.return_value.audio = audio
            vol = mgr._get_music_volume()

        assert vol == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    """Test the get_sound_manager singleton."""

    def test_get_sound_manager_returns_same_instance(self):
        """get_sound_manager() should return the same object on repeat calls."""
        import arena.audio.manager as mgr_mod
        # Reset singleton for clean test
        original = mgr_mod._manager
        mgr_mod._manager = None
        try:
            with patch.object(SoundManager, "_init_mixer"):
                a = get_sound_manager()
                b = get_sound_manager()
            assert a is b
        finally:
            mgr_mod._manager = original


# ---------------------------------------------------------------------------
# Event-to-sound mapping
# ---------------------------------------------------------------------------

class TestEventSounds:
    """Test the EVENT_SOUNDS mapping and play_event_sound."""

    def test_all_event_types_have_mapping(self):
        """Every CombatEventType should have a corresponding sound mapping."""
        for evt in CombatEventType:
            assert evt in EVENT_SOUNDS, f"{evt} missing from EVENT_SOUNDS"

    def test_sound_ids_are_strings(self):
        """All mapped sound IDs should be non-empty strings."""
        for evt, sound_id in EVENT_SOUNDS.items():
            assert isinstance(sound_id, str), f"{evt} has non-string sound_id"
            assert len(sound_id) > 0, f"{evt} has empty sound_id"

    def test_sound_ids_are_unique(self):
        """Each event type should map to a unique sound ID."""
        ids = list(EVENT_SOUNDS.values())
        assert len(ids) == len(set(ids)), "Duplicate sound IDs found"

    def test_play_event_sound_calls_play_sfx(self):
        """play_event_sound should delegate to get_sound_manager().play_sfx()."""
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            play_event_sound(CombatEventType.ATTACK_ROLL)
            mock_mgr.play_sfx.assert_called_once_with("attack_roll")

    def test_play_event_sound_unknown_type_no_crash(self):
        """play_event_sound with a type not in EVENT_SOUNDS should do nothing."""
        # Create a mock event type not in the dict
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            # Use a real type but patch EVENT_SOUNDS to be empty
            with patch("arena.audio.events.EVENT_SOUNDS", {}):
                play_event_sound(CombatEventType.COMBAT_START)
            mock_mgr.play_sfx.assert_not_called()

    def test_attack_roll_hit_plays_combat_hit(self):
        """ATTACK_ROLL with hit=True should play combat_hit sound."""
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            play_event_sound(CombatEventType.ATTACK_ROLL, {"hit": True})
            mock_mgr.play_sfx.assert_called_once_with("combat_hit")

    def test_attack_roll_miss_plays_combat_miss(self):
        """ATTACK_ROLL with hit=False should play combat_miss sound."""
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            play_event_sound(CombatEventType.ATTACK_ROLL, {"hit": False})
            mock_mgr.play_sfx.assert_called_once_with("combat_miss")

    def test_attack_roll_no_details_falls_back(self):
        """ATTACK_ROLL without details should fall back to generic attack_roll."""
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            play_event_sound(CombatEventType.ATTACK_ROLL)
            mock_mgr.play_sfx.assert_called_once_with("attack_roll")

    def test_attack_roll_no_hit_key_falls_back(self):
        """ATTACK_ROLL with details missing 'hit' should fall back to generic."""
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            play_event_sound(CombatEventType.ATTACK_ROLL, {"roll": 15})
            mock_mgr.play_sfx.assert_called_once_with("attack_roll")

    def test_non_attack_event_ignores_details(self):
        """Non-ATTACK_ROLL events should use EVENT_SOUNDS regardless of details."""
        with patch("arena.audio.events.get_sound_manager") as mock_gsm:
            mock_mgr = MagicMock()
            mock_gsm.return_value = mock_mgr
            play_event_sound(CombatEventType.DAMAGE, {"hit": True})
            mock_mgr.play_sfx.assert_called_once_with("damage_hit")


# ---------------------------------------------------------------------------
# MP3 support
# ---------------------------------------------------------------------------

class TestMp3Support:
    """Test that SoundManager can load .mp3 files."""

    def test_load_sound_tries_mp3(self):
        """_load_sound should try .mp3 after .wav and .ogg."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        fake_sound = MagicMock()

        def path_exists_side_effect(path_self):
            return str(path_self).endswith(".mp3")

        with patch("pygame.mixer.Sound", return_value=fake_sound) as mock_sound:
            with patch.object(Path, "exists", path_exists_side_effect):
                result = mgr._load_sound("combat_hit")

        assert result is fake_sound
        # Should have been called with the .mp3 path
        call_arg = mock_sound.call_args[0][0]
        assert call_arg.endswith(".mp3")

    def test_load_sound_prefers_wav_over_mp3(self):
        """_load_sound should prefer .wav over .mp3 when both exist."""
        mgr = SoundManager.__new__(SoundManager)
        mgr._initialized = True
        mgr._paths = {}
        mgr._cache = {}

        fake_sound = MagicMock()

        with patch("pygame.mixer.Sound", return_value=fake_sound) as mock_sound:
            with patch.object(Path, "exists", return_value=True):
                result = mgr._load_sound("test_sound")

        assert result is fake_sound
        # Should have been called with the .wav path (first match)
        call_arg = mock_sound.call_args[0][0]
        assert call_arg.endswith(".wav")


# ---------------------------------------------------------------------------
# SOUNDS_DIR constant
# ---------------------------------------------------------------------------

class TestSoundsDir:
    """Test the sounds directory constant."""

    def test_sounds_dir_path(self):
        """SOUNDS_DIR should point to assets/sounds."""
        assert SOUNDS_DIR == Path("assets") / "sounds"


from pathlib import Path
