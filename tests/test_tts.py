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


def test_qwen_reports_missing_model_files(monkeypatch, tmp_path):
    # N3: the tier is live — an empty models dir gets the honest "not fully
    # downloaded, re-run setup" reason, never a crash and never a stale
    # "later update".
    _use_config(monkeypatch, tmp_path, {"tts_model": "qwen-1.7b"})
    monkeypatch.setenv("OUBLIETTE_MODELS", str(tmp_path / "models"))
    tts_engine.invalidate()
    s = tts_engine.status()
    assert s["enabled"] is False
    assert "downloaded" in s["reason"] and "setup.bat" in s["reason"]
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
    # done lands as soon as the turn is ready; tail clips may ride AFTER it, and
    # the stream closes with the "end" sentinel once the voice has caught up.
    assert events[-1]["t"] == "end"
    done = next(e for e in events if e["t"] == "done")
    assert "tts_off" not in done

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


def test_slow_clips_ride_after_done_and_never_block_it(monkeypatch):
    """A slow tier (qwen, RTF ~0.6) can still be synthesizing when the turn text
    is finished. The turn payload must land IMMEDIATELY — chips, state, composer —
    while the tail clips ride after it and the stream closes with 'end' once the
    voice has caught up. (The old design waited up to 15s holding the game lock,
    then dropped whatever hadn't finished.)"""
    import time
    fake = _fake_engine(monkeypatch)
    quick = fake.synthesize

    def slow(text, voice, speed=1.0):
        time.sleep(0.3)
        return quick(text, voice, speed)

    monkeypatch.setattr(fake, "synthesize", slow)
    client.post("/api/new")
    events = _stream_events({"text": "I look around the market.", "narrate": True})
    types = [e["t"] for e in events]
    assert types[-1] == "end"
    done_i = types.index("done")
    tail_audio = [t for t in types[done_i:] if t == "audio"]
    assert tail_audio, "slow clips must arrive AFTER done, inside the open stream"


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
    done = next(e for e in events if e["t"] == "done")
    assert done["narration"]                              # the turn itself is untouched
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


# --- the qwen engine (N3): the pure parts, no model files -------------------

def test_qwen_speakers_contract():
    from oubliette.tts.qwen import SPEAKERS, QwenBackend
    assert list(SPEAKERS)[0] == "vivian"              # the locked default narrator
    assert len(SPEAKERS) == 9                         # the CustomVoice roster
    assert all(2800 <= sid <= 3071 for sid in SPEAKERS.values())


def test_qwen_prompt_layout():
    """The talker prompt is embedding SUMS in a fixed order: prefix rows, then
    think/lang/speaker (tts_pad + codec), TTS_BOS row, first-text row — and
    the rest of the text lands in the trailing pool with a TTS_EOS cap."""
    import numpy as np
    from oubliette.tts import qwen

    class StubAssets:
        def __init__(self):
            dim = 4
            self.codec = [np.arange(3072, dtype=np.float32)[:, None] * np.ones(dim)
                          for _ in range(16)]
            self.tts_pad = np.full(dim, 0.5, dtype=np.float32)

        def text_row(self, tid):
            return np.full(4, float(tid), dtype=np.float32)

        def text_rows(self, tids):
            import numpy as np
            return np.stack([self.text_row(t) for t in tids])

    a = StubAssets()
    text_ids = [11, 22, 33]
    prompt, trailing = qwen.build_prompt(a, [a.text_row(7)], text_ids, speaker_id=3065)

    # 1 prefix + 4 think/lang + 1 speaker + 1 TTS_BOS + 1 first-text = 8 rows
    assert prompt.shape == (8, 4)
    assert np.allclose(prompt[0], 7.0)                                  # the prefix row
    assert np.allclose(prompt[1], 0.5 + qwen.THINK)                     # tts_pad + codec row
    assert np.allclose(prompt[3], 0.5 + qwen.LANG_ENGLISH)              # english is baked in
    assert np.allclose(prompt[5], 0.5 + 3065)                           # the speaker row
    assert np.allclose(prompt[6], qwen.TTS_BOS + qwen.CODEC_PAD)
    assert np.allclose(prompt[7], 11 + qwen.CODEC_BOS)                  # first text + BOS
    # trailing: the remaining text one row per frame, then the EOS cap
    assert trailing.shape == (3, 4)
    assert np.allclose(trailing[0], 22) and np.allclose(trailing[1], 33)
    assert np.allclose(trailing[2], qwen.TTS_EOS)


def test_qwen_single_token_sentence_still_gets_an_eos_pool():
    import numpy as np
    from oubliette.tts import qwen

    class StubAssets:
        codec = [np.zeros((3072, 4), dtype=np.float32) for _ in range(16)]
        tts_pad = np.zeros(4, dtype=np.float32)

        def text_row(self, tid):
            return np.full(4, float(tid), dtype=np.float32)

        def text_rows(self, tids):
            return np.stack([self.text_row(t) for t in tids])

    prompt, trailing = qwen.build_prompt(StubAssets(), [], [42], speaker_id=3066)
    assert prompt.shape[0] == 7                       # no prefix rows this time
    assert trailing.shape == (1, 4)                   # just the TTS_EOS cap
    assert np.allclose(trailing[0], qwen.TTS_EOS)


def test_qwen_decoder_driver_chunks_and_flushes():
    """The stateful-decoder driver: ≤12 frames per call, state threaded through,
    non-final chunks contribute their valid samples, the final call flushes in
    full — total PCM = frames × 1920 no matter how the chunking falls."""
    import numpy as np
    from oubliette.tts import qwen

    calls = []

    class FakeSession:
        def get_outputs(self):
            names = ["final_wav", "valid_samples", "next_pre_conv_history",
                     "next_latent_buffer", "next_conv_history"]
            names += [f"next_key_{i}" for i in range(8)] + [f"next_value_{i}" for i in range(8)]
            return [type("O", (), {"name": n}) for n in names]

        def run(self, names, feed):
            n = feed["audio_codes"].shape[1]
            calls.append((n, float(feed["is_last"][0]), feed["past_key_0"].shape[2]))
            final = feed["is_last"][0] > 0
            held = 4                                   # the export's lookahead frames
            latent = feed["latent_buffer"].shape[2]
            if final:
                wav = np.zeros((1, (latent + n) * 1920), dtype=np.float16)
                valid = np.array([wav.shape[1]])
            else:
                wav = np.zeros((1, (latent + n) * 1920), dtype=np.float16)
                valid = np.array([max(0, (latent + n - held)) * 1920])
            out = {"final_wav": wav, "valid_samples": valid,
                   "next_pre_conv_history": np.zeros((1, 512, 2), dtype=np.float16),
                   "next_latent_buffer": np.zeros((1, 1024, held), dtype=np.float16),
                   "next_conv_history": np.zeros((1, 1024, 4), dtype=np.float16)}
            kv = min(feed["past_key_0"].shape[2] + n, 72)
            for i in range(8):
                out[f"next_key_{i}"] = np.zeros((1, 16, kv, 64), dtype=np.float16)
                out[f"next_value_{i}"] = np.zeros((1, 16, kv, 64), dtype=np.float16)
            return [out[n] for n in names]

    dec = qwen._Decoder.__new__(qwen._Decoder)      # skip __init__ (no real ONNX)
    dec.sess = FakeSession()
    dec.out_names = [o.name for o in dec.sess.get_outputs()]

    pcm = dec.render(np.zeros((30, 16), dtype=np.int64))
    assert len(pcm) == 30 * 1920                     # every frame accounted for once
    assert [c[0] for c in calls] == [12, 12, 6]      # 30 frames in 12/12/6 chunks
    assert [c[1] for c in calls] == [0.0, 0.0, 1.0]  # is_last only on the flush
    assert calls[1][2] == 12 and calls[2][2] == 24   # KV state threaded through


def test_qwen_probe_lists_whats_missing(tmp_path):
    from oubliette.tts.qwen import QwenBackend
    reason = QwenBackend.probe(tmp_path)
    assert "setup.bat" in reason
    assert "llama-bin" in reason and "tokenizer.json" in reason
