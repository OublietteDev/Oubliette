"""Our own thin ctypes binding to llama.cpp — exactly the slice the Qwen
narrator needs, nothing more.

The ABI (struct layouts, function signatures) is transcribed from llama.h of
llama.cpp build b9333 (MIT) — the exact Vulkan build the setup picker downloads
into models/qwen-1.7b/llama-bin/. The build is PINNED: a different llama.cpp
build may lay these structs out differently, so the picker and this file must
move together.

This is deliberately not llama-cpp-python (heavy, wheels lag, no embeddings-in
batches on our path) and not the spike's wrapper repo (no license — read-only
reference, never imported). Design notes that came from studying that wrapper
live in spike/tts-n0/README.md.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

llama_token = ctypes.c_int32
llama_pos = ctypes.c_int32
llama_seq_id = ctypes.c_int32


class llama_model_params(ctypes.Structure):
    _fields_ = [
        ("devices", ctypes.POINTER(ctypes.c_void_p)),
        ("tensor_buft_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("n_gpu_layers", ctypes.c_int32),
        ("split_mode", ctypes.c_int32),
        ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.POINTER(ctypes.c_float)),
        ("progress_callback", ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_float, ctypes.c_void_p)),
        ("progress_callback_user_data", ctypes.c_void_p),
        ("kv_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("vocab_only", ctypes.c_bool),
        ("use_mmap", ctypes.c_bool),
        ("use_direct_io", ctypes.c_bool),
        ("use_mlock", ctypes.c_bool),
        ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool),
        ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool),
    ]


class llama_context_params(ctypes.Structure):
    _fields_ = [
        ("n_ctx", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint32),
        ("n_ubatch", ctypes.c_uint32),
        ("n_seq_max", ctypes.c_uint32),
        ("n_rs_seq", ctypes.c_uint32),
        ("n_threads", ctypes.c_int32),
        ("n_threads_batch", ctypes.c_int32),
        ("ctx_type", ctypes.c_int32),
        ("rope_scaling_type", ctypes.c_int32),
        ("pooling_type", ctypes.c_int32),
        ("attention_type", ctypes.c_int32),
        ("flash_attn_type", ctypes.c_int32),
        ("rope_freq_base", ctypes.c_float),
        ("rope_freq_scale", ctypes.c_float),
        ("yarn_ext_factor", ctypes.c_float),
        ("yarn_attn_factor", ctypes.c_float),
        ("yarn_beta_fast", ctypes.c_float),
        ("yarn_beta_slow", ctypes.c_float),
        ("yarn_orig_ctx", ctypes.c_uint32),
        ("defrag_thold", ctypes.c_float),
        ("cb_eval", ctypes.c_void_p),
        ("cb_eval_user_data", ctypes.c_void_p),
        ("type_k", ctypes.c_int32),
        ("type_v", ctypes.c_int32),
        ("abort_callback", ctypes.c_void_p),
        ("abort_callback_data", ctypes.c_void_p),
        ("embeddings", ctypes.c_bool),
        ("offload_kqv", ctypes.c_bool),
        ("no_perf", ctypes.c_bool),
        ("op_offload", ctypes.c_bool),
        ("swa_full", ctypes.c_bool),
        ("kv_unified", ctypes.c_bool),
        ("samplers", ctypes.POINTER(ctypes.c_void_p)),
        ("n_samplers", ctypes.c_size_t),
    ]


class llama_sampler_chain_params(ctypes.Structure):
    _fields_ = [("no_perf", ctypes.c_bool)]


class llama_batch(ctypes.Structure):
    _fields_ = [
        ("n_tokens", ctypes.c_int32),
        ("token", ctypes.POINTER(llama_token)),
        ("embd", ctypes.POINTER(ctypes.c_float)),
        ("pos", ctypes.POINTER(llama_pos)),
        ("n_seq_id", ctypes.POINTER(ctypes.c_int32)),
        ("seq_id", ctypes.POINTER(ctypes.POINTER(llama_seq_id))),
        ("logits", ctypes.POINTER(ctypes.c_int8)),
    ]


_LOG_CB_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)

_lib = None           # the bound llama.dll (init() ran)
_lib_dir: Path | None = None
_log_cb = None        # kept alive — ctypes callbacks die if garbage-collected
LAST_ERROR: str | None = None   # llama.cpp's most recent error line, for honest reasons


def _on_log(level: int, message: bytes, _user) -> None:
    # level 2 = error. Everything else is loader chatter we keep out of the
    # game server's console; the last error is kept for failure messages.
    global LAST_ERROR
    if level == 2 and message:
        LAST_ERROR = message.decode("utf-8", errors="replace").strip()


def init(bin_dir: str | os.PathLike) -> None:
    """Load the llama.cpp DLLs from bin_dir and bind the API. Idempotent —
    one llama.cpp per process (the loaded backends are global anyway)."""
    global _lib, _lib_dir, _log_cb
    bin_dir = Path(bin_dir).resolve()
    if _lib is not None:
        if bin_dir != _lib_dir:
            raise RuntimeError(f"llama.cpp already loaded from {_lib_dir}")
        return

    # ggml_backend_load_all() discovers backend DLLs (ggml-vulkan, ggml-cpu-*)
    # relative to the working directory, and Windows resolves their imports via
    # the DLL search path — so: point both at bin_dir for the duration.
    cwd = Path.cwd()
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(bin_dir))
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    os.chdir(bin_dir)
    try:
        ctypes.CDLL(str(bin_dir / "ggml-base.dll"))
        ggml = ctypes.CDLL(str(bin_dir / "ggml.dll"))
        lib = ctypes.CDLL(str(bin_dir / "llama.dll"))

        _log_cb = _LOG_CB_TYPE(_on_log)
        lib.llama_log_set(_log_cb, None)

        ggml.ggml_backend_load_all()
        lib.llama_backend_init()
    finally:
        os.chdir(cwd)

    # --- signatures (only what we call) ---
    lib.llama_model_default_params.restype = llama_model_params
    lib.llama_model_load_from_file.argtypes = [ctypes.c_char_p, llama_model_params]
    lib.llama_model_load_from_file.restype = ctypes.c_void_p
    lib.llama_model_free.argtypes = [ctypes.c_void_p]
    lib.llama_model_get_vocab.argtypes = [ctypes.c_void_p]
    lib.llama_model_get_vocab.restype = ctypes.c_void_p
    lib.llama_model_n_embd.argtypes = [ctypes.c_void_p]
    lib.llama_model_n_embd.restype = ctypes.c_int32
    lib.llama_vocab_n_tokens.argtypes = [ctypes.c_void_p]
    lib.llama_vocab_n_tokens.restype = ctypes.c_int32

    lib.llama_context_default_params.restype = llama_context_params
    lib.llama_init_from_model.argtypes = [ctypes.c_void_p, llama_context_params]
    lib.llama_init_from_model.restype = ctypes.c_void_p
    lib.llama_free.argtypes = [ctypes.c_void_p]

    lib.llama_batch_init.argtypes = [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
    lib.llama_batch_init.restype = llama_batch
    lib.llama_batch_free.argtypes = [llama_batch]
    lib.llama_decode.argtypes = [ctypes.c_void_p, llama_batch]
    lib.llama_decode.restype = ctypes.c_int32
    lib.llama_get_logits_ith.argtypes = [ctypes.c_void_p, ctypes.c_int32]
    lib.llama_get_logits_ith.restype = ctypes.POINTER(ctypes.c_float)
    lib.llama_get_embeddings.argtypes = [ctypes.c_void_p]
    lib.llama_get_embeddings.restype = ctypes.POINTER(ctypes.c_float)

    lib.llama_get_memory.argtypes = [ctypes.c_void_p]
    lib.llama_get_memory.restype = ctypes.c_void_p
    lib.llama_memory_clear.argtypes = [ctypes.c_void_p, ctypes.c_bool]

    lib.llama_sampler_chain_default_params.restype = llama_sampler_chain_params
    lib.llama_sampler_chain_init.argtypes = [llama_sampler_chain_params]
    lib.llama_sampler_chain_init.restype = ctypes.c_void_p
    lib.llama_sampler_chain_add.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.llama_sampler_init_penalties.argtypes = [ctypes.c_int32, ctypes.c_float,
                                                 ctypes.c_float, ctypes.c_float]
    lib.llama_sampler_init_penalties.restype = ctypes.c_void_p
    lib.llama_sampler_init_top_k.argtypes = [ctypes.c_int32]
    lib.llama_sampler_init_top_k.restype = ctypes.c_void_p
    lib.llama_sampler_init_temp.argtypes = [ctypes.c_float]
    lib.llama_sampler_init_temp.restype = ctypes.c_void_p
    lib.llama_sampler_init_dist.argtypes = [ctypes.c_uint32]
    lib.llama_sampler_init_dist.restype = ctypes.c_void_p
    lib.llama_sampler_sample.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32]
    lib.llama_sampler_sample.restype = llama_token
    lib.llama_sampler_free.argtypes = [ctypes.c_void_p]

    _lib = lib
    _lib_dir = bin_dir


def loaded() -> bool:
    return _lib is not None


# --- object wrappers ---------------------------------------------------------

class Model:
    """A loaded GGUF model. n_gpu_layers=-1 offloads everything llama.cpp can
    (Vulkan when a device exists, else it runs on CPU — the self-benchmark
    tells the player the truth either way)."""

    def __init__(self, path: str | os.PathLike):
        params = _lib.llama_model_default_params()
        params.n_gpu_layers = -1
        self.ptr = _lib.llama_model_load_from_file(
            Path(path).resolve().as_posix().encode("utf-8"), params)
        if not self.ptr:
            raise RuntimeError(
                f"llama.cpp could not load {Path(path).name}"
                + (f" ({LAST_ERROR})" if LAST_ERROR else ""))
        self.vocab = _lib.llama_model_get_vocab(self.ptr)
        self.n_embd = _lib.llama_model_n_embd(self.ptr)
        self.n_vocab = _lib.llama_vocab_n_tokens(self.vocab)

    def close(self) -> None:
        if getattr(self, "ptr", None):
            _lib.llama_model_free(self.ptr)
            self.ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class Context:
    def __init__(self, model: Model, n_ctx: int, embeddings: bool = False,
                 n_threads: int | None = None):
        self.model = model               # keep the model alive
        params = _lib.llama_context_default_params()
        params.n_ctx = n_ctx
        params.n_batch = n_ctx
        params.n_ubatch = min(512, n_ctx)
        params.n_seq_max = 1
        params.embeddings = embeddings
        params.flash_attn_type = 1
        params.no_perf = True
        cpu = os.cpu_count() or 4
        params.n_threads = n_threads or max(1, cpu // 2)
        params.n_threads_batch = n_threads or cpu
        self.ptr = _lib.llama_init_from_model(model.ptr, params)
        if not self.ptr:
            raise RuntimeError("llama.cpp context init failed"
                               + (f" ({LAST_ERROR})" if LAST_ERROR else ""))

    def decode(self, batch: "Batch") -> None:
        status = _lib.llama_decode(self.ptr, batch.struct)
        if status != 0:
            raise RuntimeError(f"llama_decode failed (status {status})")

    def logits_last(self):
        """ctypes float pointer to the last flagged token's logits."""
        return _lib.llama_get_logits_ith(self.ptr, -1)

    def embeddings_ptr(self):
        return _lib.llama_get_embeddings(self.ptr)

    def clear_kv(self) -> None:
        _lib.llama_memory_clear(_lib.llama_get_memory(self.ptr), True)

    def close(self) -> None:
        if getattr(self, "ptr", None):
            _lib.llama_free(self.ptr)
            self.ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class Batch:
    """An embeddings batch (the talker takes VECTORS, not token ids — the whole
    reason this binding exists). Positions may be a plain offset or a full
    int32 array — the talker's M-RoPE wants 4 planes: [pos, pos, pos, zeros],
    i.e. 4*n_tokens entries, which is why capacity is checked against them."""

    def __init__(self, n_tokens_max: int, embd_dim: int):
        self.struct = _lib.llama_batch_init(n_tokens_max, embd_dim, 1)
        self.n_tokens_max = n_tokens_max
        self.embd_dim = embd_dim

    def set_embd(self, data, pos) -> None:
        import numpy as np
        n = data.shape[0]
        if n > self.n_tokens_max:
            raise ValueError(f"batch overflow: {n} > {self.n_tokens_max}")
        data = np.ascontiguousarray(data, dtype=np.float32)
        ctypes.memmove(self.struct.embd, data.ctypes.data, data.nbytes)
        if isinstance(pos, int):
            for i in range(n):
                self.struct.pos[i] = pos + i
        else:
            pos = np.ascontiguousarray(pos, dtype=np.int32)
            if len(pos) > self.n_tokens_max:     # pos entries share the token buffer
                raise ValueError(f"position planes overflow the batch: {len(pos)}")
            ctypes.memmove(self.struct.pos, pos.ctypes.data, pos.nbytes)
        self.struct.n_tokens = n
        for i in range(n):
            self.struct.n_seq_id[i] = 1
            self.struct.seq_id[i][0] = 0
            self.struct.logits[i] = 1 if i == n - 1 else 0

    def close(self) -> None:
        if getattr(self, "struct", None) is not None:
            _lib.llama_batch_free(self.struct)
            self.struct = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class Sampler:
    """A native sampler chain: (penalties) -> top-k -> temperature -> dist.
    sample() can first mask logits to a code range plus a whitelist — the
    talker's group-0 codes live in [0, 2048) with EOS/PAD/BOS just above, and
    the predictor's 15 groups each own a 2048-wide slice of one big vocab."""

    def __init__(self, temperature: float, top_k: int, seed: int,
                 repeat_penalty: float = 1.0, penalty_last_n: int = 64):
        self.ptr = _lib.llama_sampler_chain_init(_lib.llama_sampler_chain_default_params())
        if repeat_penalty != 1.0:
            _lib.llama_sampler_chain_add(
                self.ptr, _lib.llama_sampler_init_penalties(
                    penalty_last_n, repeat_penalty, 0.0, 0.0))
        if top_k > 0:
            _lib.llama_sampler_chain_add(self.ptr, _lib.llama_sampler_init_top_k(top_k))
        _lib.llama_sampler_chain_add(self.ptr, _lib.llama_sampler_init_temp(temperature))
        _lib.llama_sampler_chain_add(self.ptr, _lib.llama_sampler_init_dist(seed))

    def sample(self, ctx: Context, n_vocab: int,
               limit: tuple[int, int] | None = None,
               allow: frozenset[int] | set[int] = frozenset()) -> int:
        if limit is not None:
            import numpy as np
            logits = np.ctypeslib.as_array(ctx.logits_last(), shape=(n_vocab,))
            mask = np.ones(n_vocab, dtype=bool)
            mask[limit[0]:limit[1]] = False
            for t in allow:
                mask[t] = False
            logits[mask] = -1e10        # in place, on llama.cpp's own buffer
        return int(_lib.llama_sampler_sample(self.ptr, ctx.ptr, -1))

    def close(self) -> None:
        if getattr(self, "ptr", None):
            _lib.llama_sampler_free(self.ptr)
            self.ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
