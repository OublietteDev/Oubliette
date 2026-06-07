"""The Forge web app (FastAPI), C1: open & check.

One process, one self-contained page. Endpoints:
  GET /                  -> the authoring page
  GET /api/packs         -> the worlds you can open (id, name, version, ✓/⚠)
  GET /api/pack/{id}     -> one world's contents (read-only) + the validity report

Validity is NOT computed here — it's delegated to `oubliette.content.loader`,
the same code the game loads packs with. If The Forge says a world is ready, the
game will accept it.

Run: `oubliette-forge` (or `python -m oubliette.creator.server`) — opens a browser.
Reads packs from `oubliette/content/packs` by default; override with the
OUBLIETTE_PACKS_ROOT env var (used by tests).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from ..content.loader import PackValidationError, load_pack

STATIC = Path(__file__).parent / "static"
_DEFAULT_PACKS_ROOT = Path(__file__).parent.parent / "content" / "packs"

# The per-type files a pack is made of (the world recipe).
PACK_FILES = ["pack", "items", "statblocks", "npcs", "places", "scenarios"]

app = FastAPI(title="Oubliette: The Forge")


def _packs_root() -> Path:
    """Where worlds live. Read per request so tests can point elsewhere."""
    override = os.environ.get("OUBLIETTE_PACKS_ROOT")
    return Path(override) if override else _DEFAULT_PACKS_ROOT


def _pack_dir(pack_id: str) -> Path | None:
    """Resolve a pack folder, refusing anything that isn't a direct child of the
    packs root (no path-traversal via ids like '../foo')."""
    if not pack_id or "/" in pack_id or "\\" in pack_id or pack_id in (".", ".."):
        return None
    d = _packs_root() / pack_id
    return d if (d.is_dir() and (d / "pack.json").is_file()) else None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _validate(pack_id: str) -> dict:
    """Run the GAME's loader. Returns the friendly ✓/⚠ shape for the UI."""
    try:
        load_pack(pack_id, packs_root=_packs_root())
        return {"ok": True, "issues": []}
    except PackValidationError as e:
        return {"ok": False, "issues": e.errors}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache, max-age=0"})


@app.get("/api/packs")
async def list_packs() -> JSONResponse:
    """Every openable world, with a quick ✓ ready / ⚠ N-to-fix summary."""
    root = _packs_root()
    out = []
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            manifest = _read_json(d / "pack.json")
            if manifest is None:
                continue                    # not a pack folder; skip
            report = _validate(d.name)
            out.append({
                "id": d.name,
                "name": (manifest.get("name") if isinstance(manifest, dict) else None) or d.name,
                "version": manifest.get("version") if isinstance(manifest, dict) else None,
                "ok": report["ok"],
                "issue_count": len(report["issues"]),
            })
    return JSONResponse({"packs": out})


@app.get("/api/pack/{pack_id}")
async def read_pack(pack_id: str) -> JSONResponse:
    """One world's raw contents (for read-only display) + its validity report."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    contents = {name: _read_json(d / f"{name}.json") for name in PACK_FILES}
    return JSONResponse({"id": pack_id, "contents": contents, "validation": _validate(pack_id)})


def main() -> None:
    import threading
    import webbrowser

    import uvicorn

    host, port = "127.0.0.1", 8001     # 8000 is the game; The Forge runs alongside
    url = f"http://{host}:{port}"
    print(f"\n  Oubliette: The Forge — open your browser to {url}\n  (Ctrl+C to stop)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
