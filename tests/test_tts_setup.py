"""The narration front door (N2): hardware classification, the honest
recommendation, and the picker's full conversation — driven with injected
input/print/download so no console, network, or model files are touched.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("OUBLIETTE_DB", os.path.join(tempfile.mkdtemp(), "test.sqlite"))
os.environ.setdefault("OUBLIETTE_CONFIG", os.path.join(tempfile.mkdtemp(), "cfg.json"))

import pytest  # noqa: E402

from oubliette.tts import engine as tts_engine  # noqa: E402
from oubliette.tts import setup as tts_setup  # noqa: E402
from oubliette.tts.setup import (GpuInfo, TIERS, Tier, classify_discrete,  # noqa: E402
                                 recommend, tier_installed)


@pytest.fixture()
def cfg(monkeypatch, tmp_path):
    p = tmp_path / "cfg.json"
    monkeypatch.setenv("OUBLIETTE_CONFIG", str(p))
    tts_engine.invalidate()
    yield p
    tts_engine.invalidate()


class Console:
    """Scripted player: canned answers in, printed lines captured out."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.lines = []

    def input(self, prompt=""):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def print(self, *args):
        self.lines.append(" ".join(str(a) for a in args))

    def text(self):
        return "\n".join(self.lines)


def _fake_download(installed: list):
    def dl(art, dest: Path, print_fn=print):
        dest.mkdir(parents=True, exist_ok=True)
        if art.unpack:      # archives leave a stamp, not the archive itself
            (dest / (art.filename + ".sha256")).write_text(art.sha256.lower())
        else:
            (dest / art.filename).write_bytes(b"\0" * art.size)
        installed.append(art.filename)
    return dl


def _install_tier(model: str, root: Path):
    tier = next(t for t in TIERS if t.model == model)
    (root / model).mkdir(parents=True, exist_ok=True)
    for a in tier.artifacts:
        if a.unpack:
            (root / model / (a.filename + ".sha256")).write_text(a.sha256.lower())
        else:
            (root / model / a.filename).write_bytes(b"\0" * a.size)


# --- classification & recommendation ----------------------------------------

def test_discrete_gpu_names_classify_correctly():
    assert classify_discrete("NVIDIA GeForce RTX 3080")
    assert classify_discrete("AMD Radeon RX 6900 XT")
    assert classify_discrete("Intel Arc A770")
    assert not classify_discrete("Intel(R) UHD Graphics 630")
    assert not classify_discrete("AMD Radeon(TM) Graphics")     # an APU, not a card


def test_recommendation_no_gpu_is_plain_kokoro():
    tier, why = recommend(GpuInfo(name="Intel UHD", discrete=False), TIERS)
    assert tier.model == "kokoro" and "any CPU" in why


def test_recommendation_prefers_qwen_on_a_discrete_gpu():
    # N3: the tier is live — a strong GPU gets the expressive voice.
    tier, why = recommend(GpuInfo(name="RTX 3080", vram_mb=10240, discrete=True), TIERS)
    assert tier.model == "qwen-1.7b" and "discrete GPU" in why
    # ...but not on a GPU with too little memory
    tier, _ = recommend(GpuInfo(name="old card", vram_mb=1024, discrete=True), TIERS)
    assert tier.model == "kokoro"


def test_recommendation_honest_if_qwen_ever_gated_again():
    # The Brett-gate fallback keeps working: an unavailable qwen tier drops
    # the recommendation back to Kokoro with the "when it arrives" note.
    import dataclasses
    tiers = [t if t.model != "qwen-1.7b"
             else dataclasses.replace(t, available=False, unavailable_note="arrives later")
             for t in TIERS]
    tier, why = recommend(GpuInfo(name="RTX 3080", vram_mb=10240, discrete=True), tiers)
    assert tier.model == "kokoro" and "when it arrives" in why


# --- the picker conversation --------------------------------------------------

def test_pick_kokoro_downloads_and_writes_config(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))
    got = []
    console = Console(["1", "n"])
    rc = tts_setup.run(input_fn=console.input, print_fn=console.print,
                       download_fn=_fake_download(got), models_root=tmp_path)
    assert rc == 0
    assert "kokoro-v1.0.onnx" in got and "voices-v1.0.bin" in got
    assert tts_engine.tts_model() == "kokoro"
    assert "fight over the same hardware" in console.text()   # the local-DM warning


def test_enter_accepts_the_recommendation(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))
    rc = tts_setup.run(input_fn=Console([""]).input, print_fn=lambda *a: None,
                       download_fn=_fake_download([]), models_root=tmp_path)
    assert rc == 0 and tts_engine.tts_model() == "kokoro"


def test_installed_model_skips_download(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))
    _install_tier("kokoro", tmp_path)
    got = []
    console = Console(["1"])
    tts_setup.run(input_fn=console.input, print_fn=console.print,
                  download_fn=_fake_download(got), models_root=tmp_path)
    assert got == []                                   # nothing re-downloaded
    assert "already downloaded" in console.text()


def test_pick_none_keeps_game_as_today_and_offers_cleanup(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))
    _install_tier("kokoro", tmp_path)
    console = Console(["0", "y"])                      # narration off; yes, reclaim the disk
    tts_setup.run(input_fn=console.input, print_fn=console.print,
                  download_fn=_fake_download([]), models_root=tmp_path)
    assert tts_engine.tts_model() is None
    assert not (tmp_path / "kokoro").exists()          # deleted only after the explicit yes


def test_replaced_model_survives_a_no(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))
    _install_tier("kokoro", tmp_path)
    console = Console(["0", "n"])
    tts_setup.run(input_fn=console.input, print_fn=console.print,
                  download_fn=_fake_download([]), models_root=tmp_path)
    assert (tmp_path / "kokoro" / "kokoro-v1.0.onnx").exists()   # never silently deleted


def test_pick_qwen_downloads_the_whole_tier(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu",
                        lambda: GpuInfo(discrete=True, name="RTX 3080", vram_mb=10240))
    got = []
    console = Console(["2"])
    rc = tts_setup.run(input_fn=console.input, print_fn=console.print,
                       download_fn=_fake_download(got), models_root=tmp_path)
    assert rc == 0 and tts_engine.tts_model() == "qwen-1.7b"
    assert "qwen3_tts_talker.q5_k.gguf" in got and "embeddings.zip" in got
    assert any("llama-b9333" in f for f in got)        # the pinned llama.cpp build


def test_unavailable_tier_refused_honestly(cfg, tmp_path, monkeypatch):
    # The refusal path stays exercised (the Brett gate re-locks it by flipping
    # `available` — the conversation must still hold).
    import dataclasses
    gated = [t if t.model != "qwen-1.7b"
             else dataclasses.replace(t, available=False, unavailable_note="arrives later")
             for t in TIERS]
    monkeypatch.setattr(tts_setup, "TIERS", gated)
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=True, name="RTX"))
    console = Console(["2", "0"])                      # try qwen, get told, settle for none
    tts_setup.run(input_fn=console.input, print_fn=console.print,
                  download_fn=_fake_download([]), models_root=tmp_path)
    assert "can't be picked yet" in console.text()
    assert tts_engine.tts_model() is None


def test_failed_download_changes_nothing(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))

    def boom(art, dest, print_fn=print):
        raise OSError("connection reset")

    console = Console(["1"])
    rc = tts_setup.run(input_fn=console.input, print_fn=console.print,
                       download_fn=boom, models_root=tmp_path)
    assert rc == 1
    assert tts_engine.tts_model() is None              # config untouched on failure
    assert "Nothing was changed" in console.text()


def test_non_interactive_run_leaves_everything_alone(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu", lambda: GpuInfo(discrete=False))
    json.dump({"tts_model": "kokoro"}, open(os.environ["OUBLIETTE_CONFIG"], "w"))
    tts_engine.invalidate()
    rc = tts_setup.run(input_fn=Console([]).input, print_fn=lambda *a: None,
                       download_fn=_fake_download([]), models_root=tmp_path)
    assert rc == 0 and tts_engine.tts_model() == "kokoro"


def test_tier_installed_checks_exact_sizes(tmp_path):
    tier = next(t for t in TIERS if t.model == "kokoro")
    _install_tier("kokoro", tmp_path)
    assert tier_installed(tier, tmp_path)
    # a truncated file (interrupted copy) must not count as installed
    (tmp_path / "kokoro" / "voices-v1.0.bin").write_bytes(b"\0" * 10)
    assert not tier_installed(tier, tmp_path)


# --- archives: verified zips unpack, stamp, and resume ------------------------

def _zip_artifact(tmp_path, files: dict, unpack="all", into="") -> tuple:
    """A real zip on disk + an Artifact pinned to its true sha256."""
    import hashlib
    import zipfile
    from oubliette.tts.setup import Artifact
    zpath = tmp_path / "asset.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    return zpath, Artifact(url="unused", filename="asset.zip", sha256=digest,
                           size=zpath.stat().st_size, unpack=unpack, into=into)


def test_unpack_all_extracts_and_stamps(tmp_path):
    from oubliette.tts.setup import _unpack_artifact, artifact_installed
    dest = tmp_path / "tier"
    dest.mkdir()
    zpath, art = _zip_artifact(tmp_path, {"embeddings/a.npy": b"AA", "embeddings/b.npy": b"BB"})
    _unpack_artifact(art, zpath, dest)
    assert (dest / "embeddings" / "a.npy").read_bytes() == b"AA"
    assert artifact_installed(art, dest)               # the stamp is the installed-check
    (dest / "asset.zip.sha256").write_text("deadbeef") # a stale stamp doesn't count
    assert not artifact_installed(art, dest)


def test_unpack_dlls_takes_only_dlls_flattened(tmp_path):
    from oubliette.tts.setup import _unpack_artifact
    dest = tmp_path / "tier"
    dest.mkdir()
    zpath, art = _zip_artifact(
        tmp_path, {"llama.dll": b"L", "ggml.dll": b"G", "llama-server.exe": b"X"},
        unpack="dlls", into="llama-bin")
    _unpack_artifact(art, zpath, dest)
    names = sorted(p.name for p in (dest / "llama-bin").iterdir())
    assert names == ["ggml.dll", "llama.dll"]          # the 20 exes stay behind


def test_unpack_refuses_path_traversal(tmp_path):
    import pytest
    from oubliette.tts.setup import _unpack_artifact
    dest = tmp_path / "tier"
    dest.mkdir()
    zpath, art = _zip_artifact(tmp_path, {"../escape.txt": b"nope"})
    with pytest.raises(OSError, match="path-traversal"):
        _unpack_artifact(art, zpath, dest)


def test_interrupted_qwen_install_resumes_not_restarts(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(tts_setup, "detect_gpu",
                        lambda: GpuInfo(discrete=True, name="RTX 3080", vram_mb=10240))
    tier = next(t for t in TIERS if t.model == "qwen-1.7b")
    # the big talker file already landed on a previous (interrupted) run
    talker = tier.artifacts[0]
    (tmp_path / "qwen-1.7b").mkdir(parents=True)
    (tmp_path / "qwen-1.7b" / talker.filename).write_bytes(b"\0" * talker.size)
    got = []
    console = Console(["2"])
    tts_setup.run(input_fn=console.input, print_fn=console.print,
                  download_fn=_fake_download(got), models_root=tmp_path)
    assert talker.filename not in got                  # a gigabyte not re-downloaded
    assert "embeddings.zip" in got
    assert "already here" in console.text()
