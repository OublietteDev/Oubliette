"""Voiced narration (N1): sentence chunking, the engine front door, and the
audio events riding the turn stream.

No real TTS model here — a fake backend stands in, so these tests prove the
plumbing (chunk → synthesize → announce → serve) without the [tts] extra
installed. The never-block-a-turn promise is the through-line: every
unavailable/broken path must leave the text flowing exactly as today.
"""

from __future__ import annotations

import json
import os
import tempfile

# Must be set BEFORE importing the server (it builds the game at import time).
os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "test.sqlite"))
os.environ.setdefault("OUBLIETTE_CONFIG", os.path.join(tempfile.mkdtemp(), "cfg.json"))
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the scripted client

from fastapi.testclient import TestClient  # noqa: E402

from oubliette.app.server import app  # noqa: E402
from oubliette.tts import engine as tts_engine  # noqa: E402
from oubliette.tts.chunker import SentenceChunker, clean_for_speech  # noqa: E402

client = TestClient(app)


# --- the chunker -----------------------------------------------------------

def test_chunker_assembles_sentences_across_deltas():
    c = SentenceChunker()
    deltas = ["The door ", "creaks open. The hall", " beyond is dark. What", " do you do?"]
    out = []
    for d in deltas:
        out.extend(c.feed(d))
    out.extend(c.flush())
    texts = [t for t, _ in out]
    assert texts == ["The door creaks open. ", "The hall beyond is dark. ", "What do you do?"]
    # upto offsets are cumulative raw-character positions — monotonic, and the
    # last one covers every char that streamed (movie mode's reveal allowance).
    uptos = [u for _, u in out]
    assert uptos == sorted(uptos)
    assert uptos[-1] == sum(len(d) for d in deltas)


def test_chunker_upto_counts_raw_markdown_chars():
    c = SentenceChunker()
    raw = "**The Vault** opens! Inside, _gold_."
    out = c.feed(raw) + c.flush()
    assert out[-1][1] == len(raw)          # offsets index the RAW text the client shows


def test_chunker_force_splits_a_breathless_runon():
    c = SentenceChunker(max_sentence=80)
    out = c.feed("word " * 40)             # 200 chars, no terminal punctuation
    assert out                             # split happened without waiting for a period
    assert all(len(t) <= 80 for t, _ in out)


def test_chunker_skips_whitespace_only_segments():
    c = SentenceChunker()
    assert c.feed("   \n\n") == []
    assert c.flush() == []


def test_chunker_fed_counts_buffered_text_too():
    # A single sentence with no trailing whitespace sits in the buffer until
    # flush — `consumed` stays 0 but `fed` must not, or the server's
    # nothing-streamed fallback re-feeds the text and the voice reads the turn
    # TWICE (caught live, 2026-07-09).
    c = SentenceChunker()
    text = "You make your way to the market square."
    assert c.feed(text) == []
    assert c.consumed == 0 and c.fed == len(text)
    out = c.flush()
    assert [t for t, _ in out] == [text]
    assert out[-1][1] == len(text)


def test_clean_for_speech_strips_markdown_to_words():
    md = "# Dawn\n\nThe **iron** door bears a [warning](x.png): *turn back*. `run`"
    assert clean_for_speech(md) == "Dawn The iron door bears a warning: turn back. run"


# --- the engine front door -------------------------------------------------

def _use_config(monkeypatch, tmp_path, data: dict):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("OUBLIETTE_CONFIG", str(p))
    tts_engine.invalidate()


def test_status_honest_when_no_model_configured(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {})
    s = tts_engine.status()
    assert s["enabled"] is False and "tts_model" in s["reason"]
    tts_engine.invalidate()


def test_status_honest_on_unknown_model(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"tts_model": "elevenlabs"})
    s = tts_engine.status()
    assert s["enabled"] is False and "elevenlabs" in s["reason"]
    tts_engine.invalidate()


def test_qwen_tier_is_recognized_but_not_yet_live(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"tts_model": "qwen-1.7b"})
    s = tts_engine.status()
    assert s["enabled"] is False and "later update" in s["reason"]
    tts_engine.invalidate()


def test_kokoro_reports_missing_model_files(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"tts_model": "kokoro"})
    monkeypatch.setenv("OUBLIETTE_MODELS", str(tmp_path / "models"))
    tts_engine.invalidate()
    s = tts_engine.status()
    assert s["enabled"] is False and "downloaded" in s["reason"]
    tts_engine.invalidate()


def test_voice_saved_per_model(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path, {"tts_model": "kokoro"})
    tts_engine.set_tts_voice("kokoro", "bm_george")
    assert tts_engine.tts_voice("kokoro") == "bm_george"
    assert tts_engine.tts_voice("qwen-1.7b") is None      # rosters don't bleed across tiers
    tts_engine.invalidate()


# --- the server: audio events on the turn stream ---------------------------

class FakeBackend:
    """Synthesizes a real (silent) WAV instantly — the plumbing under test,
    including the benchmark's duration parsing."""
    id = "kokoro"
    default_voice = "af_heart"

    def __init__(self):
        self.spoken = []

    def voices(self):
        return ["af_heart", "am_puck", "bm_george"]

    def synthesize(self, text, voice, speed=1.0):
        import io
        import wave
        self.spoken.append((text, voice))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\0\0" * 2400)          # 0.1 s of silence
        return buf.getvalue()


def _fake_engine(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(tts_engine, "get_engine", lambda: (fake, None))
    return fake


def _stream_events(payload: dict) -> list[dict]:
    events = []
    with client.stream("POST", "/api/turn/stream", json=payload) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def test_stream_announces_audio_clips_then_done(monkeypatch):
    _fake_engine(monkeypatch)
    client.post("/api/new")
    events = _stream_events({"text": "I look around the market.", "narrate": True})

    audio = [e for e in events if e["t"] == "audio"]
    assert audio, "narration requested and available — clips must be announced"
    assert events[-1]["t"] == "done" and "tts_off" not in events[-1]

    # every clip landed inside the stream, offsets cover the full narration
    streamed = "".join(e["v"] for e in events if e["t"] == "delta")
    uptos = [e["upto"] for e in audio]
    assert uptos == sorted(uptos) and uptos[-1] == len(streamed)

    # the announced clips are fetchable and carry the synthesized bytes
    for e in audio:
        r = client.get(e["url"])
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/wav")
        assert r.content.startswith(b"RIFF")


def test_stream_without_narrate_has_no_audio_events(monkeypatch):
    _fake_engine(monkeypatch)
    client.post("/api/new")
    events = _stream_events({"text": "I look around the market."})
    assert not [e for e in events if e["t"] == "audio"]
    assert "tts_off" not in events[-1]                    # nobody asked — nothing to explain


def test_stream_narrate_unavailable_is_honest_and_harmless(monkeypatch):
    monkeypatch.setattr(tts_engine, "get_engine",
                        lambda: (None, "no narrator is configured (tts_model is unset)"))
    client.post("/api/new")
    events = _stream_events({"text": "I look around the market.", "narrate": True})
    done = events[-1]
    assert done["t"] == "done" and done["narration"]      # the turn itself is untouched
    assert "tts_model" in done["tts_off"]
    assert not [e for e in events if e["t"] == "audio"]


def test_put_voice_validates_and_persists(monkeypatch):
    _fake_engine(monkeypatch)
    r = client.put("/api/tts", json={"voice": "am_puck"})
    assert r.status_code == 200 and r.json()["voice"] == "am_puck"
    assert client.put("/api/tts", json={"voice": "not_a_voice"}).status_code == 400


def test_put_voice_refused_when_no_engine(monkeypatch):
    monkeypatch.setattr(tts_engine, "get_engine", lambda: (None, "no narrator"))
    assert client.put("/api/tts", json={"voice": "af_heart"}).status_code == 409


def test_unknown_clip_is_404():
    assert client.get("/api/tts/clip/deadbeef").status_code == 404


def test_benchmark_measures_and_hands_back_a_preview(monkeypatch, tmp_path):
    monkeypatch.setenv("OUBLIETTE_CONFIG", str(tmp_path / "cfg.json"))  # no saved voice bleeding in
    fake = _fake_engine(monkeypatch)
    r = client.post("/api/tts/benchmark", json={})
    assert r.status_code == 200
    d = r.json()
    assert d["verdict"] == "fast"                     # instant fake → outruns real time
    assert d["audio_seconds"] > 0 and d["voice"] == "af_heart"
    assert client.get(d["url"]).status_code == 200    # the measurement IS the preview
    # it warmed up first, then measured the real sentence
    texts = [t for t, _ in fake.spoken]
    assert texts[0] == "Ready." and "drowned pilings" in texts[1]


def test_benchmark_respects_a_requested_voice(monkeypatch):
    _fake_engine(monkeypatch)
    d = client.post("/api/tts/benchmark", json={"voice": "am_puck"}).json()
    assert d["voice"] == "am_puck"


def test_benchmark_refused_when_no_engine(monkeypatch):
    monkeypatch.setattr(tts_engine, "get_engine", lambda: (None, "no narrator"))
    assert client.post("/api/tts/benchmark", json={}).status_code == 409
