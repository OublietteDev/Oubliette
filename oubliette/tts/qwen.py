"""Tier 2 — Qwen3-TTS 1.7B CustomVoice, driven by our own thin engine.

The pipeline (design: voiced-narration N3): a talker LLM (GGUF, llama.cpp —
Vulkan when there's a GPU) emits one codec frame per step as a group-0 code; a
small code-predictor LLM (GGUF) fills in groups 1–15 for that frame; a
stateful ONNX decoder renders the 16-group frames to 24 kHz PCM on the plain
CPU onnxruntime the Kokoro tier already ships (RTF 0.60 measured on the
6900 XT — the decoder never needs the GPU).

The talker consumes EMBEDDING VECTORS, not token ids — prompts are sums of
text-embedding and codec-embedding table rows (exported .npy files, memory-
mapped). Protocol constants (codec ids, speaker ids, language ids) come from
the official Apache-2.0 Qwen3-TTS export config; the loop itself is our spike
port (spike/tts-n0/bench_qwen.py) grown up. The one narrator instruct below is
the tier's locked voice direction — pace and accent ride every synthesis.
"""

from __future__ import annotations

import io
import threading
import wave
from pathlib import Path

SAMPLE_RATE = 24000
FRAME_SAMPLES = 1920          # one codec frame = 80 ms
NUM_GROUPS = 16

# Codec-side protocol ids (rows of codec embedding table 0) and text-side
# special ids (rows of the projected text table) — from the official export's
# config.json (Apache 2.0; a copy sits beside the spike benches).
CODEC_PAD, CODEC_BOS, CODEC_EOS = 2148, 2149, 2150
THINK, NOTHINK, THINK_BOS, THINK_EOS = 2154, 2155, 2156, 2157
TTS_PAD, TTS_BOS, TTS_EOS = 151671, 151672, 151673
LANG_ENGLISH = 2050
GROUP_VOCAB = 2048            # each of the 16 groups' codes live in [0, 2048)

# The nine CustomVoice speakers (official ids). Vivian first: she is the tier's
# locked default narrator (Chris, 2026-07-09, after two audition rounds).
SPEAKERS = {
    "vivian": 3065, "serena": 3066, "ryan": 3061, "aiden": 2861,
    "dylan": 2878, "eric": 2875, "ono_anna": 2873, "sohee": 2864,
    "uncle_fu": 3010,
}

# The tier's voice direction — locked with the shipped sample (commit e7b0fde).
# The narrator voice is a (speaker, instruct) pair; players pick the speaker,
# the direction ships with the tier.
INSTRUCT = ("Speak with a refined British accent, like the narrator of a "
            "fantasy audiobook — measured, warm, a little wry. Keep a brisk, "
            "confident pace — no lingering.")

# Sampling — the exact settings the locked audition samples were made with.
# Fixed seeds: the same sentence narrates the same way every time.
TALKER_TEMP, TALKER_TOP_K, TALKER_SEED = 0.6, 50, 42
TALKER_REPEAT_PENALTY, TALKER_PENALTY_LAST_N = 1.05, 128
PREDICTOR_TEMP, PREDICTOR_TOP_K, PREDICTOR_SEED = 0.6, 50, 45
MAX_FRAMES = 400              # 32 s — far past any one sentence

DECODER_CHUNK = 12            # frames per decoder call (the export's design size)
DECODER_LAYERS = 8

FILES = {
    "talker": "qwen3_tts_talker.q5_k.gguf",
    "predictor": "qwen3_tts_predictor.q8_0.gguf",
    "decoder": "qwen3_tts_decoder.fp16.onnx",
    "tokenizer": "tokenizer.json",
}
EMBEDDINGS_DIR = "embeddings"
LLAMA_BIN_DIR = "llama-bin"


class _Assets:
    """The exported embedding tables, memory-mapped — ~900 MB on disk, paged in
    as rows get touched. The text table is fp16 (151936×2048); the 16 codec
    tables are fp32; proj maps the talker's 2048-dim hidden to the predictor's
    1024-dim input, applied lazily per row (cheaper than materializing 16
    projected tables)."""

    def __init__(self, emb_dir: Path):
        import numpy as np
        self.text = np.load(emb_dir / "text_embedding_projected.npy", mmap_mode="r")
        self.codec = [np.load(emb_dir / f"codec_embedding_{g}.npy", mmap_mode="r")
                      for g in range(NUM_GROUPS)]
        self.proj_w = np.load(emb_dir / "proj_weight.npy")     # (1024, 2048) — small, load hot
        self.proj_b = np.load(emb_dir / "proj_bias.npy")
        self.tts_pad = self.text_row(TTS_PAD)

    def text_row(self, token_id: int):
        return self.text[token_id].astype("float32")

    def text_rows(self, token_ids):
        return self.text[list(token_ids)].astype("float32")

    def to_1024(self, vec):
        return vec @ self.proj_w.T + self.proj_b


def build_prompt(assets: _Assets, prefix_rows: list, text_ids: list[int],
                 speaker_id: int):
    """The talker's initial prompt (embeddings) and the trailing text pool.

    Layout (CustomVoice, streaming text fusion — the mode every verified sample
    used): the caller's prefix rows (instruct block + role header, plain text
    embeddings); think/language/speaker rows as tts_pad + codec rows; a TTS_BOS
    row; then only the FIRST text token (fused with codec BOS). The rest of
    the text feeds in one token per generated frame, summed with that frame's
    audio embedding — that's the trailing pool.
    """
    import numpy as np
    rows = list(prefix_rows)
    pad = assets.tts_pad
    table0 = assets.codec[0]
    for cid in (THINK, THINK_BOS, LANG_ENGLISH, THINK_EOS):
        rows.append(pad + table0[cid])
    rows.append(pad + table0[speaker_id])
    rows.append(assets.text_row(TTS_BOS) + table0[CODEC_PAD])
    rows.append(assets.text_row(text_ids[0]) + table0[CODEC_BOS])
    prompt = np.vstack(rows).astype(np.float32)

    eos_row = assets.text_row(TTS_EOS)[None]
    if len(text_ids) > 1:
        trailing = np.vstack([assets.text_rows(text_ids[1:]), eos_row])
    else:
        trailing = eos_row
    return prompt, trailing.astype(np.float32)


class _Decoder:
    """Driver for the stateful ONNX decoder export: feed ≤12 frames at a time,
    thread the conv/KV state through, and on the final chunk take the full
    flush. All state tensors are fp16 (the export's own precision)."""

    def __init__(self, onnx_path: Path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        # Don't spin-wait: this shares a process with the game server.
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(onnx_path), opts,
                                         providers=["CPUExecutionProvider"])
        self.out_names = [o.name for o in self.sess.get_outputs()]
        # First-call kernel warmup so turn one doesn't pay it mid-narration.
        import numpy as np
        self.render(np.zeros((2, NUM_GROUPS), dtype=np.int64))

    def _zero_state(self) -> dict:
        import numpy as np
        f16 = np.float16
        state = {
            "pre_conv_history": np.zeros((1, 512, 0), dtype=f16),
            "latent_buffer": np.zeros((1, 1024, 0), dtype=f16),
            "conv_history": np.zeros((1, 1024, 0), dtype=f16),
        }
        for i in range(DECODER_LAYERS):
            state[f"past_key_{i}"] = np.zeros((1, 16, 0, 64), dtype=f16)
            state[f"past_value_{i}"] = np.zeros((1, 16, 0, 64), dtype=f16)
        return state

    def render(self, codes) -> "np.ndarray":
        """(n_frames, 16) int codes → float32 PCM for the whole utterance."""
        import numpy as np
        state = self._zero_state()
        pieces = []
        n = codes.shape[0]
        for start in range(0, n, DECODER_CHUNK):
            chunk = codes[start:start + DECODER_CHUNK]
            final = start + DECODER_CHUNK >= n
            feed = {"audio_codes": chunk[None].astype(np.int64),
                    "is_last": np.array([1.0 if final else 0.0], dtype=np.float16)}
            feed.update(state)
            out = dict(zip(self.out_names, self.sess.run(self.out_names, feed)))
            wav = out["final_wav"][0].astype(np.float32)
            if final:
                pieces.append(wav)          # the flush includes the held-back tail
            else:
                pieces.append(wav[:int(out["valid_samples"][0])])
                state = {
                    "pre_conv_history": out["next_pre_conv_history"],
                    "latent_buffer": out["next_latent_buffer"],
                    "conv_history": out["next_conv_history"],
                }
                for i in range(DECODER_LAYERS):
                    state[f"past_key_{i}"] = out[f"next_key_{i}"]
                    state[f"past_value_{i}"] = out[f"next_value_{i}"]
        return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)


class QwenBackend:
    """Tier 2 for the engine front door — same contract as KokoroBackend:
    probe / voices / default_voice / synthesize(text, voice) -> WAV bytes."""

    id = "qwen-1.7b"

    def __init__(self, root: Path):
        from tokenizers import Tokenizer   # deferred: [tts] extra may be absent
        from . import llamacpp

        llamacpp.init(root / LLAMA_BIN_DIR)
        self._assets = _Assets(root / EMBEDDINGS_DIR)
        self._tok = Tokenizer.from_file(str(root / FILES["tokenizer"]))
        self._instruct_ids = self._tok.encode(
            f"<|im_start|>user\n{INSTRUCT}<|im_end|>\n").ids + self._tok.encode(
            "<|im_start|>assistant\n").ids

        self._talker = llamacpp.Model(root / FILES["talker"])
        self._predictor = llamacpp.Model(root / FILES["predictor"])
        self._talker_ctx = llamacpp.Context(self._talker, n_ctx=2048, embeddings=True)
        self._pred_ctx = llamacpp.Context(self._predictor, n_ctx=64)
        self._talker_batch = llamacpp.Batch(2048, self._talker.n_embd)
        self._pred_batch = llamacpp.Batch(2, self._predictor.n_embd)
        self._decoder = _Decoder(root / FILES["decoder"])
        self._llamacpp = llamacpp
        # One synthesis at a time: the llama.cpp contexts hold mutable KV state.
        self._lock = threading.Lock()

    @property
    def default_voice(self) -> str:
        return "vivian"

    def voices(self) -> list[str]:
        return list(SPEAKERS)

    # --- synthesis ------------------------------------------------------------

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> bytes:
        """One sentence → one mono 16-bit WAV. Raises on failure — the caller
        owns the never-block-a-turn promise. `speed` is accepted for interface
        parity; pace direction lives in the instruct."""
        import numpy as np
        speaker_id = SPEAKERS.get(voice, SPEAKERS["vivian"])
        text_ids = self._tok.encode(text).ids
        if not text_ids:
            raise ValueError("nothing to say")
        with self._lock:
            frames = self._generate_frames(text_ids, speaker_id)
        if not frames:
            raise RuntimeError("the narrator produced no audio for this sentence")
        pcm = self._decoder.render(np.array(frames, dtype=np.int64))
        pcm16 = (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def _generate_frames(self, text_ids: list[int], speaker_id: int) -> list[list[int]]:
        import numpy as np
        lc = self._llamacpp
        assets = self._assets
        prompt, trailing = build_prompt(
            assets, list(assets.text_rows(self._instruct_ids)), text_ids, speaker_id)

        # M-RoPE prefill: positions come in 4 planes — [pos, pos, pos, zeros].
        n_p = prompt.shape[0]
        self._talker_ctx.clear_kv()
        base = np.arange(n_p, dtype=np.int32)
        self._talker_batch.set_embd(
            prompt, np.concatenate([base, base, base, np.zeros(n_p, dtype=np.int32)]))
        self._talker_ctx.decode(self._talker_batch)
        hidden = np.ctypeslib.as_array(
            self._talker_ctx.embeddings_ptr(), shape=(n_p, self._talker.n_embd))[-1].copy()

        talker_sampler = lc.Sampler(TALKER_TEMP, TALKER_TOP_K, TALKER_SEED,
                                    TALKER_REPEAT_PENALTY, TALKER_PENALTY_LAST_N)
        pred_sampler = lc.Sampler(PREDICTOR_TEMP, PREDICTOR_TOP_K, PREDICTOR_SEED)
        frames: list[list[int]] = []
        step_pos = np.zeros(4, dtype=np.int32)
        try:
            for step in range(MAX_FRAMES):
                # A clip must never be empty: EOS stays off the menu for the
                # first two frames (the official pipeline does the same).
                allow = {CODEC_PAD, CODEC_BOS} if step < 2 else {CODEC_PAD, CODEC_BOS, CODEC_EOS}
                code0 = talker_sampler.sample(self._talker_ctx, self._talker.n_vocab,
                                              limit=(0, GROUP_VOCAB), allow=allow)
                if code0 == CODEC_EOS:
                    break
                codes, summed = self._predict_frame(hidden, code0, pred_sampler)
                frames.append(codes)

                # Feed the frame back: audio embedding sum + the next trailing
                # text row (or tts_pad once the text is spent).
                text_vec = trailing[step] if step < len(trailing) else assets.tts_pad
                nxt = (summed + text_vec).astype(np.float32)[None]
                step_pos[0:3] = n_p + step
                self._talker_batch.set_embd(nxt, step_pos)
                self._talker_ctx.decode(self._talker_batch)
                hidden = np.ctypeslib.as_array(
                    self._talker_ctx.embeddings_ptr(),
                    shape=(1, self._talker.n_embd))[0].copy()
        finally:
            talker_sampler.close()
            pred_sampler.close()
        return frames

    def _predict_frame(self, hidden, code0: int, sampler) -> tuple[list[int], "np.ndarray"]:
        """Groups 1–15 for one frame. The predictor's single output vocab holds
        all 15 groups back-to-back, 2048 codes each — sampling is range-limited
        to the current group's slice. Returns the codes and the 2048-dim sum of
        all 16 groups' embeddings (the talker's next audio input)."""
        import numpy as np
        assets = self._assets
        codes = [code0]
        summed = assets.codec[0][code0].astype(np.float32).copy()

        self._pred_ctx.clear_kv()
        first = np.stack([assets.to_1024(hidden),
                          assets.to_1024(assets.codec[0][code0].astype(np.float32))])
        self._pred_batch.set_embd(first, 0)
        self._pred_ctx.decode(self._pred_batch)

        for g in range(1, NUM_GROUPS):
            lo = (g - 1) * GROUP_VOCAB
            token = sampler.sample(self._pred_ctx, self._predictor.n_vocab,
                                   limit=(lo, lo + GROUP_VOCAB))
            code = token - lo
            codes.append(code)
            row = assets.codec[g][code].astype(np.float32)
            summed += row
            if g < NUM_GROUPS - 1:
                self._pred_batch.set_embd(assets.to_1024(row)[None], g + 1)
                self._pred_ctx.decode(self._pred_batch)
        return codes, summed

    # --- availability -----------------------------------------------------------

    @classmethod
    def probe(cls, root: Path) -> str | None:
        """Why this backend can't load right now, or None if it should."""
        missing = [name for name in FILES.values() if not (root / name).is_file()]
        if not (root / EMBEDDINGS_DIR / "text_embedding_projected.npy").is_file():
            missing.append(f"{EMBEDDINGS_DIR}/")
        if not (root / LLAMA_BIN_DIR / "llama.dll").is_file():
            missing.append(f"{LLAMA_BIN_DIR}/")
        if missing:
            return (f"the Qwen narrator isn't fully downloaded "
                    f"(missing {', '.join(missing)} in {root}) - re-run setup.bat")
        try:
            import onnxruntime  # noqa: F401
            import tokenizers   # noqa: F401
        except ImportError:
            return "the narration packages aren't installed (pip extra: [tts])"
        return None
