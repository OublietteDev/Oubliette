"""The narrator engines — one loaded model, keyed by the `tts_model` config key.

`tts_model` in oubliette-config.json is the single source of truth (players set
it via setup's picker in N2; a dev with several models downloaded flips the one
value). The engine loads whatever the key names and never assumes only one tier
is on disk. Every failure path returns an honest reason instead of raising —
narration must never block a turn, or the app from opening.

Backends:
  kokoro     — Kokoro 82M ONNX, any CPU (N1, live)
  qwen-1.7b  — Qwen3-TTS 1.7B GGUF via our own llama.cpp engine (N3, not yet)
"""

from __future__ import annotations

import io
import os
import threading
import wave
from pathlib import Path

from oubliette.llm.providers import load_config, save_config

DEFAULT_VOICE = "af_heart"

# Model artifacts live under models/<tier>/ beside the save (overridable with
# OUBLIETTE_MODELS, mirroring OUBLIETTE_DB/OUBLIETTE_CONFIG for tests and odd
# install layouts). setup.bat's picker downloads into this layout in N2.
def models_root() -> Path:
    return Path(os.environ.get("OUBLIETTE_MODELS", "models"))


# --- config keys -----------------------------------------------------------

def tts_model(cfg: dict | None = None) -> str | None:
    """The chosen narration tier, or None (= narration off, the game as today)."""
    cfg = load_config() if cfg is None else cfg
    model = cfg.get("tts_model")
    return model if isinstance(model, str) and model else None


def tts_voice(model: str, cfg: dict | None = None) -> str | None:
    """The saved narrator voice for a tier (rosters differ per model, so voices
    are stored per-model — surviving a tier switch and switch-back)."""
    cfg = load_config() if cfg is None else cfg
    voice = (cfg.get("tts_voices") or {}).get(model)
    return voice if isinstance(voice, str) and voice else None


def set_tts_voice(model: str, voice: str) -> None:
    cfg = load_config()
    voices = dict(cfg.get("tts_voices") or {})
    voices[model] = voice
    cfg["tts_voices"] = voices
    save_config(cfg)


def set_tts_model(model: str | None) -> None:
    """Write the chosen tier (setup's picker owns this; None = narration off).
    "Off" is stored as an explicit null — so the picker can tell a deliberate
    "no narration" apart from "never been asked" and default accordingly.
    Drops the cached engine so a running server notices the change."""
    cfg = load_config()
    cfg["tts_model"] = model
    save_config(cfg)
    invalidate()


# --- backends ---------------------------------------------------------------

class KokoroBackend:
    """Tier 1 — Kokoro 82M via kokoro-onnx on plain CPU. RTF ~0.2 measured
    (N0): the voice comfortably outruns the reader."""

    id = "kokoro"
    MODEL_FILE = "kokoro-v1.0.onnx"
    VOICES_FILE = "voices-v1.0.bin"

    def __init__(self, root: Path):
        from kokoro_onnx import Kokoro   # deferred: the [tts] extra may be absent
        self._kokoro = Kokoro(str(root / self.MODEL_FILE), str(root / self.VOICES_FILE))
        # One synthesis at a time — the ONNX session isn't ours to parallelize,
        # and at ~5× real-time a queue never builds anyway.
        self._lock = threading.Lock()
        # English voices only (a=American, b=British) — synthesis runs lang=en-us;
        # the other-language voices in the bin would read English badly.
        self._voices = sorted(v for v in self._kokoro.get_voices()
                              if v[:1] in ("a", "b"))

    @property
    def default_voice(self) -> str:
        return DEFAULT_VOICE if DEFAULT_VOICE in self._voices else self._voices[0]

    def voices(self) -> list[str]:
        return list(self._voices)

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> bytes:
        """One sentence → one mono 16-bit WAV. Raises on failure — the caller
        owns the never-block-a-turn promise."""
        import numpy as np   # guaranteed present: kokoro-onnx depends on it
        with self._lock:
            samples, sr = self._kokoro.create(
                text, voice=voice, speed=speed, lang="en-us")
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()

    @classmethod
    def probe(cls, root: Path) -> str | None:
        """Why this backend can't load right now, or None if it should."""
        if not (root / cls.MODEL_FILE).is_file() or not (root / cls.VOICES_FILE).is_file():
            return (f"the Kokoro voice model isn't downloaded "
                    f"(expected {cls.MODEL_FILE} + {cls.VOICES_FILE} in {root})")
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return "the narration packages aren't installed (pip extra: [tts])"
        return None


class QwenPlaceholder:
    """Tier 2 — arrives in slice N3 (our own thin llama.cpp engine). The key is
    recognized now so a dev config naming it degrades honestly, not confusingly."""

    id = "qwen-1.7b"

    @classmethod
    def probe(cls, root: Path) -> str | None:
        return "the Qwen narrator arrives in a later update"


BACKENDS = {"kokoro": KokoroBackend, "qwen-1.7b": QwenPlaceholder}


# --- the loaded engine (lazy, cached per config value) ----------------------

_UNLOADED = object()   # initial cache key — must never equal a real tts_model value (incl. None)
_cache: dict = {"key": _UNLOADED, "engine": None, "reason": None}
_cache_lock = threading.Lock()


def get_engine() -> tuple[object | None, str | None]:
    """(backend, None) when narration can run, else (None, honest reason).
    Loads lazily on first ask and re-loads only when `tts_model` changes."""
    model = tts_model()
    with _cache_lock:
        if _cache["key"] == model:
            return _cache["engine"], _cache["reason"]
        engine, reason = None, None
        if model is None:
            reason = "no narrator is configured (tts_model is unset)"
        elif model not in BACKENDS:
            reason = f"unknown tts_model '{model}'"
        else:
            cls = BACKENDS[model]
            root = models_root() / model
            reason = cls.probe(root)
            if reason is None:
                try:
                    engine = cls(root)
                except Exception as e:   # a broken model must never break the game
                    reason = f"the narrator failed to load: {e!r}"
        _cache.update(key=model, engine=engine, reason=reason)
        return engine, reason


def invalidate() -> None:
    """Forget the cached engine (tests; a future in-app model switch)."""
    with _cache_lock:
        _cache.update(key=_UNLOADED, engine=None, reason=None)


def active_voice(cfg: dict | None = None) -> str | None:
    """The narrator voice synthesis should use right now: the saved choice if
    it's on the loaded model's roster, else the model's default."""
    engine, _ = get_engine()
    if engine is None:
        return None
    saved = tts_voice(engine.id, cfg)
    if saved and saved in engine.voices():
        return saved
    return engine.default_voice


def status() -> dict:
    """What the Settings UI needs: can narration run, with what voices, and if
    not — why, in words a player can act on."""
    engine, reason = get_engine()
    return {
        "enabled": engine is not None,
        "model": tts_model(),
        "reason": reason,
        "voices": engine.voices() if engine else [],
        "voice": active_voice(),
        "default_voice": engine.default_voice if engine else None,
    }
