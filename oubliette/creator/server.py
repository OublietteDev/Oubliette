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

import base64
import difflib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..content.loader import PackValidationError, load_pack

STATIC = Path(__file__).parent / "static"
_DEFAULT_PACKS_ROOT = Path(__file__).parent.parent / "content" / "packs"
_TYPES = ["items", "statblocks", "npcs", "places", "lore", "scenarios"]
_TYPE_WORD = {"items": "items", "statblocks": "creatures", "npcs": "characters",
              "places": "places", "lore": "lore entries", "scenarios": "opening setups"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "world"

# The per-type files a pack is made of (the world recipe).
PACK_FILES = ["pack", "items", "statblocks", "npcs", "places", "lore", "scenarios"]

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


def _write_json(path: Path, data) -> None:
    """Write a pack file in a clean, stable, human-diffable shape: 2-space indent,
    real unicode (not \\uXXXX), and a trailing newline."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _backup_pack(pack_dir: Path, pack_id: str) -> str:
    """Copy the current pack to a timestamped backup BEFORE overwriting, so a
    save is never destructive. Backups live OUTSIDE the packs root (in a sibling
    `pack-backups/`) so they're never mistaken for packs. Returns the backup path."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = _packs_root().parent / "pack-backups" / pack_id / stamp
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():                       # same-second second save: keep both
        dest = dest.parent / f"{stamp}-{len(list(dest.parent.iterdir()))}"
    shutil.copytree(pack_dir, dest)
    return str(dest)


def _name_pools(pack_dir: Path) -> dict:
    """{type: {id: display-name}} read best-effort from the pack files, used to turn
    technical ids in validation messages into the names the author actually sees."""
    pools = {}
    for t in _TYPES:
        data = _read_json(pack_dir / f"{t}.json") or []
        pools[t] = {e.get("id"): e.get("name", e.get("id"))
                    for e in data if isinstance(e, dict) and e.get("id")}
    return pools


def _suggest(ref: str, pool: dict) -> str | None:
    """Closest existing name for a mistyped reference ('belt' -> 'sturdy belt')."""
    by_name = {name: name for name in pool.values()}
    hit = difflib.get_close_matches(ref, list(pool.keys()) + list(by_name), n=1, cutoff=0.5)
    if not hit:
        return None
    return pool.get(hit[0], hit[0])     # show the friendly name of the match


def _translate(issue: str, pools: dict) -> dict:
    """Rewrite one loader message into plain language (+ a 'did you mean?' where we
    can). Returns {message, section}. Falls back to the raw text if unrecognised."""
    def nm(t, i):
        return pools.get(t, {}).get(i, i)

    def did_you_mean(ref, t):
        s = _suggest(ref, pools.get(t, {}))
        return f" Did you mean “{s}”?" if s else ""

    # unknown item / place / stat block reference
    m = re.match(r"^(\w+): (.+?)\.(\w+) references unknown (item|place|stat block) '(.+?)'$", issue)
    if m:
        typ, owner, field, kind, ref = m.groups()
        who = nm(typ, owner)
        if field == "exits":
            return {"message": f"“{who}” has an exit leading to a place that doesn’t exist (“{ref}”).{did_you_mean(ref, 'places')}", "section": typ}
        if field == "home_location":
            return {"message": f"“{who}” is set to live somewhere that doesn’t exist (“{ref}”).{did_you_mean(ref, 'places')}", "section": typ}
        if field == "start_location":
            return {"message": f"The opening “{who}” starts in a place that doesn’t exist (“{ref}”).{did_you_mean(ref, 'places')}", "section": typ}
        if kind == "item":
            return {"message": f"“{who}” refers to an item that doesn’t exist (“{ref}”).{did_you_mean(ref, 'items')}", "section": typ}
        if kind == "stat block":
            return {"message": f"“{who}” uses a creature stat line that doesn’t exist (“{ref}”).{did_you_mean(ref, 'statblocks')}", "section": typ}
        return {"message": f"“{who}” points to something that doesn’t exist (“{ref}”).{did_you_mean(ref, 'places')}", "section": typ}

    m = re.match(r"^npcs: (.+?)\.price_list prices '(.+?)' but it is not in inventory$", issue)
    if m:
        owner, ref = m.groups()
        return {"message": f"“{nm('npcs', owner)}” has a price for “{nm('items', ref)}”, but doesn’t carry it. "
                           f"Add it to their belongings, or remove the price.", "section": "npcs"}

    m = re.match(r"^(\w+): duplicate id '(.+?)'$", issue)
    if m:
        typ, dup = m.groups()
        return {"message": f"Two {_TYPE_WORD.get(typ, typ)} share the same internal name (“{dup}”). Rename one of them.", "section": typ}

    m = re.match(r"^pack\.json: entry_scenario references unknown scenario '(.+?)'$", issue)
    if m:
        return {"message": f"This world’s starting setup points to an opening that doesn’t exist (“{m.group(1)}”).", "section": "scenarios"}

    # schema-level field error: "items.json: lantern: base_value: <msg>"
    m = re.match(r"^(\w+)\.json: (.+?): (.+)$", issue)
    if m:
        stem, ident, msg = m.groups()
        section = stem if stem in _TYPES else None
        who = nm(section, ident) if section else ident
        return {"message": f"“{who}” has a problem — {msg}", "section": section}

    # fallback: keep the raw text, guess a section from the leading token
    lead = issue.split(":", 1)[0].replace(".json", "")
    return {"message": issue, "section": lead if lead in _TYPES else None}


def _validate(pack_id: str) -> dict:
    """Run the GAME's loader. `issues` is the raw aggregated list (the guarantee);
    `friendly` rephrases each one in plain language with a section tag for the UI."""
    try:
        load_pack(pack_id, packs_root=_packs_root())
        return {"ok": True, "issues": [], "friendly": []}
    except PackValidationError as e:
        d = _pack_dir(pack_id)
        pools = _name_pools(d) if d else {}
        return {"ok": False, "issues": e.errors,
                "friendly": [_translate(i, pools) for i in e.errors]}


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


class SaveIn(BaseModel):
    contents: dict          # {pack, items, statblocks, npcs, places, scenarios}


@app.post("/api/pack/{pack_id}/save")
async def save_pack(pack_id: str, body: SaveIn) -> JSONResponse:
    """Write the edited world back to disk, after backing up the previous version.
    Saving is allowed even while a world still has issues (you never lose work-in-
    progress) — the response carries the fresh ✓/⚠ report so the page can show
    whether it's playable yet."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)

    backup = _backup_pack(d, pack_id)
    for name in PACK_FILES:
        data = body.contents.get(name)
        if data is not None:                # only rewrite files we were given
            _write_json(d / f"{name}.json", data)

    return JSONResponse({"ok": True, "backed_up": backup, "validation": _validate(pack_id)})


class ImageIn(BaseModel):
    filename: str                  # e.g. "brightvale.jpg" (browser already resized it)
    data: str                      # a data URL or bare base64 of the (resized) image


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@app.post("/api/pack/{pack_id}/image")
async def upload_image(pack_id: str, body: ImageIn) -> JSONResponse:
    """Save an illustration into the pack's images/ folder. The browser resizes the
    picture before sending it, so no image library is needed server-side."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    name = body.filename.strip()
    if not name or not _SAFE_NAME.match(name):
        return JSONResponse({"error": "unsafe filename"}, status_code=400)
    raw = body.data.split(",", 1)[-1]        # tolerate a "data:image/...;base64," prefix
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return JSONResponse({"error": "bad image data"}, status_code=400)
    images = d / "images"
    images.mkdir(exist_ok=True)
    (images / name).write_bytes(blob)
    return JSONResponse({"ok": True, "filename": name})


@app.get("/api/pack/{pack_id}/image/{filename}", response_model=None)
async def get_image(pack_id: str, filename: str) -> FileResponse | JSONResponse:
    """Serve a pack illustration (for The Forge's preview)."""
    d = _pack_dir(pack_id)
    if d is None or not _SAFE_NAME.match(filename):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = d / "images" / filename
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


class NewIn(BaseModel):
    name: str


@app.post("/api/pack/new")
async def new_pack(body: NewIn) -> JSONResponse:
    """Scaffold a brand-new world that already loads (✓): a manifest, one starting
    place, and an opening setup with a blank starter hero. The author builds from
    there. Refuses if a world with the same internal name already exists."""
    name = body.name.strip()
    if not name:
        return JSONResponse({"error": "please name the world"}, status_code=400)
    pack_id = _slug(name)
    root = _packs_root()
    root.mkdir(parents=True, exist_ok=True)
    d = root / pack_id
    if d.exists():
        return JSONResponse({"error": f"a world named “{name}” already exists"}, status_code=409)
    d.mkdir(parents=True)

    _write_json(d / "pack.json", {
        "id": pack_id, "schema_version": 1, "name": name, "version": "0.1.0",
        "author": "", "description": "", "entry_scenario": "opening"})
    for t in ["items", "statblocks", "npcs", "lore"]:
        _write_json(d / f"{t}.json", [])
    _write_json(d / "places.json", [{
        "id": "town_square", "name": "Town Square",
        "description": "A quiet square where your story begins.", "tags": [], "exits": []}])
    _write_json(d / "scenarios.json", [{
        "id": "opening", "name": "A New Beginning", "start_location": "town_square",
        "scene_override": None, "party_source": "default",
        "default_party": [{"id": "hero", "name": "Hero", "kind": "pc"}]}])

    return JSONResponse({"id": pack_id, "validation": _validate(pack_id)})


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
