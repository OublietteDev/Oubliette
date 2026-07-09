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
        (dest / art.filename).write_bytes(b"\0" * art.size)
        installed.append(art.filename)
    return dl


def _install_tier(model: str, root: Path):
    tier = next(t for t in TIERS if t.model == model)
    for a in tier.artifacts:
        (root / model).mkdir(parents=True, exist_ok=True)
        (root / model / a.filename).write_bytes(b"\0" * a.size)


# --- classification & recommendation ----------------------------------------

def test_discrete_gpu_names_classify_correctly():
    assert classify_discrete("NVIDIA GeForce RTX 3080")
    assert classify_discrete("AMD Radeon RX 6900 XT")
    assert classify_discrete("Intel Arc A770")
    assert not classify_discrete("Intel(R) UHD Graphics 630")
    assert not classify_discrete("AMD Radeon(TM) Graphics")     # an APU, not a card


def test_recommendation_is_kokoro_while_qwen_is_gated():
    # Even a strong GPU gets Kokoro today (the qwen tier flips on in N3) —
    # with an honest "ready when it arrives" note.
    tier, why = recommend(GpuInfo(name="RTX 3080", vram_mb=10240, discrete=True), TIERS)
    assert tier.model == "kokoro" and "when it arrives" in why


def test_recommendation_no_gpu_is_plain_kokoro():
    tier, why = recommend(GpuInfo(name="Intel UHD", discrete=False), TIERS)
    assert tier.model == "kokoro" and "any CPU" in why


def test_recommendation_prefers_qwen_when_available_and_gpu_fits():
    import dataclasses
    tiers = [t if t.model != "qwen-1.7b"
             else dataclasses.replace(t, available=True, unavailable_note="")
             for t in TIERS]
    tier, _ = recommend(GpuInfo(name="RTX 3080", vram_mb=10240, discrete=True), tiers)
    assert tier.model == "qwen-1.7b"
    # ...but not on a GPU with too little memory
    tier, _ = recommend(GpuInfo(name="old card", vram_mb=1024, discrete=True), tiers)
    assert tier.model == "kokoro"


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


def test_unavailable_tier_refused_honestly(cfg, tmp_path, monkeypatch):
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
