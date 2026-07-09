"""The narration front door — setup.bat's final step (design: voiced-narration N2).

Looks at the machine, gives an honest recommendation, points at the sample
clips so the choice is *heard*, downloads exactly the chosen voice model,
verifies it against pinned checksums, and writes the one `tts_model` key.
Safe to re-run anytime: an installed model is detected and kept, so switching
models later is just "run setup.bat again" — it lands straight back here.

Stdlib only, on purpose: this runs right after pip and must never depend on
the [tts] packages whose use it is choosing.

Run: python -m oubliette.tts.setup
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import engine as tts_engine

SAMPLES_DIR = Path("voice-samples")


@dataclass(frozen=True)
class Artifact:
    url: str
    filename: str
    sha256: str
    size: int              # bytes — for progress display and a fast installed-check
    # Archives: verified zips are extracted, replaced by a "<filename>.sha256"
    # stamp (the installed-check), and deleted. "all" keeps member paths;
    # "dlls" flattens just *.dll into `into` (llama.cpp ships 20 exes we skip).
    unpack: str | None = None      # None | "all" | "dlls"
    into: str = ""                 # subdir under the tier dir to extract into


@dataclass(frozen=True)
class Tier:
    number: int
    model: str | None      # the tts_model config value; None = narration off
    name: str
    blurb: str             # the honest label — what the voice IS, not a sales pitch
    needs: str = ""
    disk: str = ""
    artifacts: tuple = ()
    available: bool = True
    unavailable_note: str = ""
    sample: str | None = None


_QWEN_RELEASE = "https://github.com/OublietteDev/Oubliette/releases/download/tts-models-v1/"

# The tier table IS the picker. The Brett-gate fallback ("remove the Qwen
# option forever") = delete its entry here — nothing else refers to it.
TIERS: list[Tier] = [
    Tier(
        number=0, model=None, name="No narration",
        blurb="the game exactly as it is today",
    ),
    Tier(
        number=1, model="kokoro", name="Kokoro",
        blurb="instant and light; clear but flat - a capable reader, not an actor",
        needs="any CPU", disk="~340 MB",
        sample="kokoro.mp3",
        artifacts=(
            Artifact(
                url="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
                filename="kokoro-v1.0.onnx",
                sha256="7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
                size=325_532_387,
            ),
            Artifact(
                url="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
                filename="voices-v1.0.bin",
                sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
                size=28_214_398,
            ),
        ),
    ),
    Tier(
        number=2, model="qwen-1.7b", name="Qwen (the good voice)",
        blurb="expressive, nine speakers, a narrator with direction",
        needs="a GPU with ~2 GB of memory to spare", disk="~2.0 GB",
        sample="qwen-1.7b.mp3",
        artifacts=(
            # Model artifacts live on the Oubliette repo's own release, tagged
            # tts-models-v1 — a models-only tag, so these URLs outlive game
            # releases. llama.cpp comes straight from its official release
            # (MIT), pinned to the exact build our ctypes binding matches.
            Artifact(
                url=_QWEN_RELEASE + "qwen3_tts_talker.q5_k.gguf",
                filename="qwen3_tts_talker.q5_k.gguf",
                sha256="04532771e2ee7217cf267dd4d7ab6f08bc36e1e15772c18a40c58aa9330e8728",
                size=1_006_245_120,
            ),
            Artifact(
                url=_QWEN_RELEASE + "qwen3_tts_predictor.q8_0.gguf",
                filename="qwen3_tts_predictor.q8_0.gguf",
                sha256="42c89bdea05c42afa5ea8f5d97ece0d7e62114416ab4262c8524531688c890c0",
                size=151_124_320,
            ),
            Artifact(
                url=_QWEN_RELEASE + "qwen3_tts_decoder.fp16.onnx",
                filename="qwen3_tts_decoder.fp16.onnx",
                sha256="e65c9eeb59c72c9cacaafa966adbca52b236c76b13084c3a2c8357c5dc675c61",
                size=230_054_436,
            ),
            Artifact(
                url=_QWEN_RELEASE + "tokenizer.json",
                filename="tokenizer.json",
                sha256="09267689b8362020b9763b65dd5be7e086b31e28d72e02837a9e781de9a91bc7",
                size=11_423_986,
            ),
            Artifact(
                url=_QWEN_RELEASE + "embeddings.zip",
                filename="embeddings.zip",
                sha256="9ff6819599865d3f6354fa44e1877e9df7b4c26c4da0badf6fe04752c59f3991",
                size=616_401_257,
                unpack="all",
            ),
            Artifact(
                url="https://github.com/ggml-org/llama.cpp/releases/download/b9333/llama-b9333-bin-win-vulkan-x64.zip",
                filename="llama-b9333-bin-win-vulkan-x64.zip",
                sha256="0971a54893feafcc043b18d839dba9a42cb1038a5005030c18990e35fdc209d4",
                size=32_836_469,
                unpack="dlls", into="llama-bin",
            ),
        ),
    ),
]


# --- what's on this machine -------------------------------------------------

@dataclass
class GpuInfo:
    name: str | None = None
    vram_mb: int | None = None     # exact only when nvidia-smi answers
    discrete: bool = False


def _nvidia_smi() -> tuple[str, int] | None:
    """(name, vram_mb) from nvidia-smi, or None. The one reliable VRAM source."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        line = (out.stdout or "").strip().splitlines()
        if out.returncode == 0 and line:
            name, mem = line[0].rsplit(",", 1)
            return name.strip(), int(mem.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def _video_controllers() -> list[str]:
    """Adapter names from Windows (CIM). VRAM from this source is famously wrong
    (32-bit caps, shared-memory noise), so we take only the names."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def classify_discrete(name: str) -> bool:
    """Is this adapter a discrete GPU (vs. integrated graphics)? Name heuristics —
    the recommendation is a suggestion, and the in-game self-benchmark tells the
    truth on the player's actual hardware either way."""
    n = name.lower()
    if any(k in n for k in ("geforce", "rtx", "gtx", "quadro", "nvidia")):
        return True
    if "radeon rx" in n:                       # "AMD Radeon(TM) Graphics" = an APU — not this
        return True
    if " arc " in f" {n} " or n.startswith("intel arc"):
        return True
    return False


def detect_gpu() -> GpuInfo:
    smi = _nvidia_smi()
    if smi is not None:
        return GpuInfo(name=smi[0], vram_mb=smi[1], discrete=True)
    names = _video_controllers()
    for name in names:
        if classify_discrete(name):
            return GpuInfo(name=name, discrete=True)
    return GpuInfo(name=names[0] if names else None, discrete=False)


def recommend(gpu: GpuInfo, tiers: list[Tier]) -> tuple[Tier, str]:
    """(the tier to pre-select, one honest sentence why)."""
    qwen = next((t for t in tiers if t.model == "qwen-1.7b"), None)
    kokoro = next(t for t in tiers if t.model == "kokoro")
    enough_vram = gpu.vram_mb is None or gpu.vram_mb >= 2048
    if gpu.discrete and enough_vram and qwen is not None and qwen.available:
        return qwen, "this machine has a discrete GPU - the expressive voice should run well"
    if gpu.discrete and qwen is not None and not qwen.available:
        return kokoro, ("this machine looks ready for the expressive tier when it "
                        "arrives - today the pick is Kokoro")
    return kokoro, "Kokoro runs great on any CPU - no GPU needed"


# --- download & verify -------------------------------------------------------

def _fmt_mb(n: int) -> str:
    return f"{n / 1_048_576:.0f} MB"


def download_artifact(art: Artifact, dest_dir: Path, print_fn=print) -> None:
    """Fetch one model file to dest_dir with progress, verify its checksum, and
    only then give it its real name. Raises on any failure — the caller decides
    what that means for the config."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / (art.filename + ".part")
    final = dest_dir / art.filename
    req = urllib.request.Request(art.url, headers={"User-Agent": "oubliette-setup"})
    digest = hashlib.sha256()
    done = 0
    last_pct = -1
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
        while True:
            chunk = resp.read(1_048_576)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            pct = int(done * 100 / art.size) if art.size else 0
            if pct >= last_pct + 5:                    # a quiet, steady progress line
                print_fn(f"    {pct:3d}%   {_fmt_mb(done)} / {_fmt_mb(art.size)}")
                last_pct = pct
    if digest.hexdigest().lower() != art.sha256.lower():
        part.unlink(missing_ok=True)
        raise OSError(f"{art.filename}: the downloaded file failed its integrity check")
    if art.unpack:
        _unpack_artifact(art, part, dest_dir, print_fn)
        part.unlink(missing_ok=True)
    else:
        os.replace(part, final)


def _unpack_artifact(art: Artifact, archive: Path, dest_dir: Path, print_fn=print) -> None:
    """Extract a checksum-verified zip, then leave a stamp file in the
    archive's place — the stamp holding the pinned sha256 is the installed
    check (the archive itself is deleted to give the disk space back)."""
    import zipfile
    target = dest_dir / art.into if art.into else dest_dir
    target.mkdir(parents=True, exist_ok=True)
    print_fn(f"    unpacking into {target} ...")
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            name = member.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise OSError(f"{art.filename}: refusing a path-traversal entry ({member})")
            if art.unpack == "dlls":
                if not name.lower().endswith(".dll"):
                    continue
                with z.open(member) as src, open(target / Path(name).name, "wb") as out:
                    shutil.copyfileobj(src, out)
            else:
                z.extract(member, target)
    (dest_dir / (art.filename + ".sha256")).write_text(art.sha256.lower(), encoding="ascii")


def artifact_installed(art: Artifact, tier_dir: Path) -> bool:
    """This one file (or unpacked archive) already present and current."""
    if art.unpack:
        stamp = tier_dir / (art.filename + ".sha256")
        try:
            return stamp.read_text(encoding="ascii").strip() == art.sha256.lower()
        except OSError:
            return False
    f = tier_dir / art.filename
    return f.is_file() and f.stat().st_size == art.size


def tier_installed(tier: Tier, models_root: Path) -> bool:
    """All of a tier's artifacts present and current (sizes for plain files,
    stamps for unpacked archives; full checksums ran at download time)."""
    if not tier.artifacts:
        return False
    root = models_root / (tier.model or "")
    return all(artifact_installed(a, root) for a in tier.artifacts)


# --- the interactive picker ---------------------------------------------------

def _menu_lines(tiers: list[Tier], rec: Tier, models_root: Path) -> list[str]:
    lines = []
    for t in tiers:
        tags = []
        if t.number == rec.number:
            tags.append("recommended")
        if t.model and tier_installed(t, models_root):
            tags.append("installed")
        tag = ("   <- " + ", ".join(tags)) if tags else ""
        lines.append(f"   [{t.number}] {t.name:<22} - {t.blurb}{tag}")
        if not t.available:
            lines.append(f"       ({t.unavailable_note})")
        elif t.needs:
            lines.append(f"       needs: {t.needs}, download: {t.disk}")
    return lines


def _open_samples(print_fn=print, open_fn=None) -> None:
    if not SAMPLES_DIR.is_dir():
        print_fn("   (the voice-samples folder is missing from this copy of the game)")
        return
    print_fn(f"   Opening {SAMPLES_DIR}\\ - double-click a clip to hear that voice.")
    try:
        (open_fn or os.startfile)(str(SAMPLES_DIR.resolve()))   # noqa: S606 — the point
    except OSError:
        print_fn(f"   (couldn't open the folder - find the clips in {SAMPLES_DIR.resolve()})")


def run(input_fn=input, print_fn=print,
        download_fn=download_artifact, open_fn=None,
        models_root: Path | None = None) -> int:
    """The picker. Everything impure is injectable so tests can drive it."""
    root = models_root if models_root is not None else tts_engine.models_root()
    p = print_fn

    p("")
    p("--------------------------------------------------")
    p("   The narrator - voiced narration (optional)")
    p("--------------------------------------------------")
    gpu = detect_gpu()
    if gpu.name:
        vram = f", {gpu.vram_mb} MB memory" if gpu.vram_mb else ""
        kind = "discrete GPU" if gpu.discrete else "integrated graphics"
        p(f"   Your machine: {gpu.name} ({kind}{vram})")
    else:
        p("   Your machine: no graphics adapter details found")
    rec, why = recommend(gpu, TIERS)
    p(f"   Recommendation: {why}.")
    p("")
    for line in _menu_lines(TIERS, rec, root):
        p(line)
    p("")
    p("   [s] hear the voices first (opens the samples folder)")
    # Default: an earlier deliberate choice (incl. explicit "off") wins; a
    # machine that's never been asked defaults to the recommendation.
    from oubliette.llm.providers import load_config
    cfg = load_config()
    if "tts_model" in cfg:
        default = next((t for t in TIERS if t.model == cfg.get("tts_model")), rec)
    else:
        default = rec

    chosen: Tier | None = None
    while chosen is None:
        try:
            # A piped/redirected stdin can smuggle a UTF-8 BOM in front of the
            # first answer (PowerShell does) - either as U+FEFF or as its three
            # raw bytes, depending on the console codepage. Scrub both, or "1"
            # reads as gibberish and every piped answer is rejected.
            raw = input_fn(f"   Your pick [{default.number}]: ")
            raw = raw.lstrip("ï»¿").strip().lower()
        except EOFError:                       # non-interactive run: keep things as they are
            p("   (no input available - leaving narration as it is)")
            return 0
        if raw == "":
            chosen = default
        elif raw == "s":
            _open_samples(p, open_fn)
        elif raw.isdigit() and any(t.number == int(raw) for t in TIERS):
            t = next(t for t in TIERS if t.number == int(raw))
            if not t.available:
                p(f"   {t.name} {t.unavailable_note} - it can't be picked yet.")
            else:
                chosen = t
        else:
            p("   That's not one of the options.")

    if chosen.model is None:
        tts_engine.set_tts_model(None)
        p("   Narration is off - the game plays exactly as it does today.")
    else:
        if tier_installed(chosen, root):
            p(f"   {chosen.name} is already downloaded - keeping it.")
        else:
            p(f"   Downloading {chosen.name} ({chosen.disk}) ...")
            try:
                for art in chosen.artifacts:
                    if artifact_installed(art, root / (chosen.model or "")):
                        p(f"   - {art.filename} (already here - kept)")
                        continue          # an interrupted install resumes, not restarts
                    p(f"   - {art.filename}")
                    download_fn(art, root / chosen.model, p)
            except OSError as e:
                p(f"   [X] Download failed: {e}")
                p("       Nothing was changed. Run setup.bat again to retry -")
                p("       the game itself works fine without narration.")
                return 1
        tts_engine.set_tts_model(chosen.model)
        p(f"   Done. The narrator is {chosen.name}.")
        p("   In the game: Settings turns narration on and picks the voice;")
        p("   the volume lives under the speaker button, next to music.")
        p("   NOTE: running the DM itself on a local model on this machine?")
        p("   Stick with Kokoro or no narration - two local models will")
        p("   fight over the same hardware.")

    # Reclaim space from any OTHER tier still on disk — always ask, never silent.
    for t in TIERS:
        if t.model and t.model != chosen.model and tier_installed(t, root):
            try:
                raw = input_fn(f"   {t.name} is still on disk ({t.disk}). Delete it to free the space? [y/N]: ")
            except EOFError:
                break
            if raw.strip().lower() == "y":
                shutil.rmtree(root / t.model, ignore_errors=True)
                p(f"   {t.name} removed.")
            else:
                p(f"   Kept. (Dev tip: models/{t.model} stays usable by flipping tts_model.)")
    p("   Change your mind anytime: re-run setup.bat - it lands right back here.")
    return 0


def main() -> int:
    try:
        return run()
    except Exception as e:      # the front door must never wedge the whole setup
        print(f"   [X] The narration step hit a snag: {e!r}")
        print("       Skipping it - the game works fine without narration.")
        print("       Re-run setup.bat later to try again.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
