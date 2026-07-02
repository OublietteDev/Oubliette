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
import random
import re
import shutil
from datetime import datetime
from pathlib import Path

from dataclasses import replace

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError

from ..content.loader import PackValidationError, load_pack
from ..content.ruleset import load_ruleset
from ..content.srd_schemas import Background
from ..rules.chargen import (CharacterBuild, ChargenError, _project_srd_item,
                             build_character)
from ..rules.chargen_view import chargen_options, preview_payload
from ..rules.levelup import (MAX_LEVEL, LevelUpChoice, LevelUpError, level_up,
                             level_up_plan, xp_for_level)
from ..state.models import Character

STATIC = Path(__file__).parent / "static"
_DEFAULT_PACKS_ROOT = Path(__file__).parent.parent / "content" / "packs"
_TYPES = ["items", "statblocks", "npcs", "places", "lore", "quests", "scenarios",
          "ai_profiles", "backgrounds"]
_TYPE_WORD = {"items": "items", "statblocks": "creatures", "npcs": "characters",
              "places": "places", "lore": "lore entries", "quests": "quests",
              "scenarios": "opening setups", "ai_profiles": "AI personalities",
              "backgrounds": "backgrounds"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "world"

# The per-type files a pack is made of (the world recipe).
PACK_FILES = ["pack", "items", "statblocks", "npcs", "places", "lore", "quests",
              "scenarios", "ai_profiles", "backgrounds"]

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
        pools[t] = {e.get("id"): e.get("name") or e.get("title") or e.get("id")
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

    # quest cross-references (the techier ones; place/item refs fall to the generic matcher)
    m = re.match(r"^quests: (.+?)\.giver_npc references unknown npc '(.+?)'$", issue)
    if m:
        owner, ref = m.groups()
        return {"message": f"The quest “{nm('quests', owner)}” is given by a character that doesn’t "
                           f"exist (“{ref}”).{did_you_mean(ref, 'npcs')}", "section": "quests"}

    m = re.match(r"^quests: (.+?) is given by '(.+?)', who has no home_location.*$", issue)
    if m:
        owner, ref = m.groups()
        return {"message": f"The quest “{nm('quests', owner)}” is given by “{nm('npcs', ref)}”, but that "
                           f"character lives nowhere — give them a home so the party can find them.",
                "section": "quests"}

    m = re.match(r"^quests: (.+?)\.branches references unknown quest '(.+?)'$", issue)
    if m:
        owner, ref = m.groups()
        return {"message": f"The quest “{nm('quests', owner)}” leads on to a quest that doesn’t exist "
                           f"(“{ref}”).", "section": "quests"}

    m = re.match(r"^quests: (.+?) is unreachable.*$", issue)
    if m:
        return {"message": f"The quest “{nm('quests', m.group(1))}” can never start — make it a starting "
                           f"quest, or have another quest lead to it.", "section": "quests"}

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


def _audio_warnings(pack_id: str) -> list:
    """Non-blocking checks: place sound cues that point at a file no longer in the pack's
    audio/ folder. Audio is cosmetic — a missing sound just plays nothing — so these are
    WARNINGS, never load errors (the world still loads and plays)."""
    d = _pack_dir(pack_id)
    if d is None:
        return []
    audio = d / "audio"
    have = {p.name for p in audio.iterdir() if p.is_file()} if audio.is_dir() else set()
    places = _read_json(d / "places.json")
    out = []
    if isinstance(places, list):
        for p in places:
            if not isinstance(p, dict):
                continue
            who = p.get("name") or p.get("id") or "a place"
            for c in (p.get("sounds") or []):
                f = c.get("file") if isinstance(c, dict) else None
                if f and f not in have:
                    out.append({"message": f"“{who}” uses a sound “{f}” that isn’t in the "
                                           f"pack — it will be silent.", "section": "places"})
    return out


def _validate(pack_id: str) -> dict:
    """Run the GAME's loader. `issues` is the raw aggregated list (the guarantee);
    `friendly` rephrases each one in plain language with a section tag for the UI.
    `warnings` are non-blocking notes (missing sound files) — `ok` ignores them."""
    warnings = _audio_warnings(pack_id)
    try:
        load_pack(pack_id, packs_root=_packs_root())
        return {"ok": True, "issues": [], "friendly": [], "warnings": warnings}
    except PackValidationError as e:
        d = _pack_dir(pack_id)
        pools = _name_pools(d) if d else {}
        return {"ok": False, "issues": e.errors,
                "friendly": [_translate(i, pools) for i in e.errors], "warnings": warnings}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache, max-age=0"})


@app.get("/tokens.css")
async def tokens_css() -> FileResponse:
    """The shared house-style token block (oubliette/ui/tokens.css) — the SAME file
    the play app serves, so the two UIs draw from one palette and cannot drift."""
    return FileResponse(Path(__file__).resolve().parents[1] / "ui" / "tokens.css",
                        media_type="text/css",
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
                "warning_count": len(report.get("warnings", [])),
            })
    return JSONResponse({"packs": out})


@app.get("/api/pack/{pack_id}")
async def read_pack(pack_id: str) -> JSONResponse:
    """One world's raw contents (for read-only display) + its validity report."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    contents = {name: _read_json(d / f"{name}.json") for name in PACK_FILES}
    audio_dir = d / "audio"
    audio_files = sorted(p.name for p in audio_dir.iterdir() if p.is_file()) if audio_dir.is_dir() else []
    # which creatures carry a full combat file (Phase 3b) — so the editor can badge them
    monsters_dir = d / "monsters"
    monster_files = sorted(p.stem for p in monsters_dir.glob("*.json")) if monsters_dir.is_dir() else []
    # which person-NPCs have a built character snapshot (Phase 4b) — same idea
    chars_dir = d / "characters"
    character_files = sorted(p.stem for p in chars_dir.glob("*.json")) if chars_dir.is_dir() else []
    return JSONResponse({"id": pack_id, "contents": contents, "validation": _validate(pack_id),
                         "audio_files": audio_files, "monster_files": monster_files,
                         "character_files": character_files})


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


# --- creature portraits (Phase 3a) ---------------------------------------------
# A pack creature's token art lives in <pack>/portraits/<id>.<ext>, the same dir
# the game + Arena read (arena_bridge PortraitDirs.pack). Mirrors the app's
# character-portrait upload (raw bytes, format preserved so PNG transparency
# survives) for a consistent picker UX, keyed by the creature's id.
_PORTRAIT_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg",
                      "image/webp": ".webp", "image/gif": ".gif"}
_PORTRAIT_MAX_BYTES = 8 * 1024 * 1024          # 8 MB, matching the app


@app.post("/api/pack/{pack_id}/portrait/{sb_id}")
async def upload_portrait(pack_id: str, sb_id: str, request: Request) -> JSONResponse:
    """Save a creature's portrait into the pack's portraits/ folder, keyed by the
    creature id. POSTed as raw bytes; the browser sets Content-Type from the file
    (we keep the original format, so transparent PNG token art stays transparent).
    Re-uploading replaces any prior-extension image. Returns the stored filename."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    if not _SAFE_NAME.match(sb_id):
        return JSONResponse({"error": "unsafe creature id"}, status_code=400)
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = _PORTRAIT_MIME_EXT.get(mime)
    if ext is None:
        return JSONResponse({"error": "unsupported image type; use PNG, JPG, WEBP, or GIF"}, status_code=400)
    data = await request.body()
    if not data:
        return JSONResponse({"error": "the uploaded file is empty"}, status_code=400)
    if len(data) > _PORTRAIT_MAX_BYTES:
        return JSONResponse({"error": f"image too large ({len(data) // (1024 * 1024)} MB); max is 8 MB"}, status_code=400)
    portraits = d / "portraits"
    portraits.mkdir(exist_ok=True)
    for old in portraits.glob(f"{sb_id}.*"):   # drop any prior-extension image
        old.unlink()
    fname = f"{sb_id}{ext}"
    (portraits / fname).write_bytes(data)
    return JSONResponse({"ok": True, "filename": fname})


@app.get("/api/pack/{pack_id}/portrait/{filename}", response_model=None)
async def get_portrait(pack_id: str, filename: str) -> FileResponse | JSONResponse:
    """Serve a creature portrait (for The Forge's preview)."""
    d = _pack_dir(pack_id)
    if d is None or not _SAFE_NAME.match(filename):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = d / "portraits" / filename
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


# --- creature combat files (Phase 3b) ------------------------------------------
# Optional, per-creature: <pack>/monsters/<sb_id>.json holds a full Arena `Monster`
# (the same shape the SRD set ships). When present, the bridge prefers it over the
# flat one-swing mapping, so a Forge-authored creature fights its full kit
# (multiattack, breath weapons, distinct attacks). The slim StatBlock stays the
# bestiary/identity record; this is layered combat truth on top.
class MonsterIn(BaseModel):
    monster: dict          # a full Arena Monster JSON (validated against the engine model)


def _validate_arena_monster(data: dict) -> str | None:
    """None if `data` is a valid Arena Monster, else a short error string. Imported
    lazily so the Forge needn't load the Arena engine unless someone authors combat."""
    try:
        from arena.models.monster import Monster as _ArenaMonster
        _ArenaMonster.model_validate(data)
        return None
    except Exception as e:                  # pydantic ValidationError or import issue
        return str(e).splitlines()[0] if str(e) else "invalid combat data"


@app.get("/api/pack/{pack_id}/monster/{sb_id}", response_model=None)
async def get_monster(pack_id: str, sb_id: str) -> JSONResponse:
    """A creature's combat file, or 404 if it has none (then it uses the flat mapping)."""
    d = _pack_dir(pack_id)
    if d is None or not _SAFE_NAME.match(sb_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    data = _read_json(d / "monsters" / f"{sb_id}.json")
    if data is None:
        return JSONResponse({"error": "no combat file"}, status_code=404)
    return JSONResponse({"ok": True, "monster": data})


@app.put("/api/pack/{pack_id}/monster/{sb_id}")
async def save_monster(pack_id: str, sb_id: str, body: MonsterIn) -> JSONResponse:
    """Write a creature's combat file. Validated against the Arena `Monster` model so a
    broken file can't be saved (the bridge would silently skip it at fight time)."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    if not _SAFE_NAME.match(sb_id):
        return JSONResponse({"error": "unsafe creature id"}, status_code=400)
    err = _validate_arena_monster(body.monster)
    if err is not None:
        return JSONResponse({"error": f"invalid combat data: {err}"}, status_code=400)
    monsters = d / "monsters"
    monsters.mkdir(exist_ok=True)
    _write_json(monsters / f"{sb_id}.json", body.monster)
    return JSONResponse({"ok": True, "filename": f"{sb_id}.json"})


@app.post("/api/pack/{pack_id}/monster-baseline")
async def monster_baseline(pack_id: str, body: dict) -> JSONResponse:
    """Project a slim StatBlock → a full baseline Arena Monster (via the same bridge
    the game uses), so the attacks editor can seed a creature that has no combat file
    yet with its real abilities/AC/HP/defenses and a single starter attack. Pure
    projection — writes nothing."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    try:
        from oubliette.combat.arena_bridge import statblock_to_monster
        from oubliette.content.schemas import StatBlock
        sb = StatBlock.model_validate(body.get("statblock") or {})
        monster = statblock_to_monster(sb).model_dump(mode="json")
    except Exception as e:
        return JSONResponse({"error": f"bad creature: {str(e).splitlines()[0]}"}, status_code=400)
    return JSONResponse({"ok": True, "monster": monster})


@app.delete("/api/pack/{pack_id}/monster/{sb_id}")
async def delete_monster(pack_id: str, sb_id: str) -> JSONResponse:
    """Remove a creature's combat file — it reverts to the flat mapping (or its SRD
    file, if the id matches one). Idempotent: deleting a non-existent file is OK."""
    d = _pack_dir(pack_id)
    if d is None or not _SAFE_NAME.match(sb_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = d / "monsters" / f"{sb_id}.json"
    existed = path.is_file()
    if existed:
        path.unlink()
    return JSONResponse({"ok": True, "deleted": existed})


# --- person-NPC character snapshots (Phase 4b) -------------------------------
# A combat_kind="person" NPC fights as a real PC-style character; its chargen
# snapshot lives at packs/<id>/characters/<npc_id>.json (keyed by NPC id, like a
# creature's combat file is keyed by stat-block id). The loader reads it as the
# NPC's runtime Character — so a broken snapshot would hard-fail the pack, which
# is why the save endpoint validates against the engine model first.
class CharacterIn(BaseModel):
    character: dict        # a full state Character JSON (validated against the model)


@app.get("/api/pack/{pack_id}/character/{npc_id}", response_model=None)
async def get_person_character(pack_id: str, npc_id: str) -> JSONResponse:
    """A person-NPC's chargen snapshot, or 404 if it hasn't been built yet."""
    d = _pack_dir(pack_id)
    if d is None or not _SAFE_NAME.match(npc_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    data = _read_json(d / "characters" / f"{npc_id}.json")
    if data is None:
        return JSONResponse({"error": "no character file"}, status_code=404)
    return JSONResponse({"ok": True, "character": data})


@app.put("/api/pack/{pack_id}/character/{npc_id}")
async def save_person_character(pack_id: str, npc_id: str, body: CharacterIn) -> JSONResponse:
    """Persist a person-NPC's chargen snapshot. Validated against the engine
    `Character` model so a broken snapshot can't be saved (the loader would
    otherwise hard-fail the whole pack at load time)."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    if not _SAFE_NAME.match(npc_id):
        return JSONResponse({"error": "unsafe character id"}, status_code=400)
    try:
        Character.model_validate(body.character)
    except Exception as e:
        return JSONResponse({"error": f"invalid character: {str(e).splitlines()[0]}"}, status_code=400)
    chars = d / "characters"
    chars.mkdir(exist_ok=True)
    _write_json(chars / f"{npc_id}.json", body.character)
    return JSONResponse({"ok": True, "filename": f"{npc_id}.json"})


@app.delete("/api/pack/{pack_id}/character/{npc_id}")
async def delete_person_character(pack_id: str, npc_id: str) -> JSONResponse:
    """Remove a person-NPC's chargen snapshot. Idempotent."""
    d = _pack_dir(pack_id)
    if d is None or not _SAFE_NAME.match(npc_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = d / "characters" / f"{npc_id}.json"
    existed = path.is_file()
    if existed:
        path.unlink()
    return JSONResponse({"ok": True, "deleted": existed})


# --- SRD source catalog (Phase 3b-2: "start from an existing creature") --------
# The global bestiary (identity + rich description) and the matching Arena combat
# files are the clone sources the Forge offers alongside the current pack's own
# creatures. Read-only; loaded once (static content).
_SRD_BESTIARY_PATH = Path(__file__).parent.parent / "content" / "srd" / "bestiary.json"
_srd_bestiary_cache: dict | None = None


def _srd_bestiary() -> dict:
    """{id: StatBlock-dict} for the SRD bestiary, loaded once."""
    global _srd_bestiary_cache
    if _srd_bestiary_cache is None:
        data = _read_json(_SRD_BESTIARY_PATH) or []
        _srd_bestiary_cache = {e["id"]: e for e in data if isinstance(e, dict) and e.get("id")}
    return _srd_bestiary_cache


@app.get("/api/srd/monsters")
async def list_srd_monsters() -> JSONResponse:
    """The SRD creatures you can clone from — a light list for the picker."""
    out = [{"id": e["id"], "name": e.get("name") or e["id"],
            "cr": e.get("cr"), "type": e.get("type")}
           for e in _srd_bestiary().values()]
    out.sort(key=lambda m: ((m["cr"] if m["cr"] is not None else 0), m["name"]))
    return JSONResponse({"monsters": out})


@app.get("/api/srd/monster/{srd_id}")
async def get_srd_monster(srd_id: str) -> JSONResponse:
    """One SRD creature's identity (its bestiary StatBlock) + its full Arena combat
    file (or null). The Forge clones from these into the current pack."""
    sb = _srd_bestiary().get(srd_id)
    if sb is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    combat = None
    if _SAFE_NAME.match(srd_id):
        from arena.paths import DATA_DIR
        combat = _read_json(DATA_DIR / "monsters" / "srd" / f"{srd_id}.json")
    return JSONResponse({"ok": True, "statblock": sb, "combat": combat})


_ruleset_cache = None


def _ruleset():
    """The global SRD ruleset (chargen pickers + derivation) — pack-independent, so
    loaded once and cached. Phase 4b: building a person-NPC as a real character."""
    global _ruleset_cache
    if _ruleset_cache is None:
        _ruleset_cache = load_ruleset()
    return _ruleset_cache


def _chargen_ruleset(pack: str | None):
    """The ruleset a chargen request runs against: the SRD, plus the named pack's
    own backgrounds and items (module-kit S2) — so a person-NPC authored inside
    Atria can BE a Silverfin dockhand carrying dockhand boots. The pack is read
    from disk leniently: it may be mid-edit, so entries that don't validate are
    simply skipped here (the pack validator panel is where they're reported)."""
    rs = _ruleset()
    d = _pack_dir(pack) if pack else None
    if d is None:
        return rs
    from ..content.loader import _project_mechanics
    from ..content.schemas import Item as PackItem

    def entries(filename: str) -> list:
        data = _read_json(d / filename)
        return data if isinstance(data, list) else []

    backgrounds = dict(rs.backgrounds)
    for raw in entries("backgrounds.json"):
        try:
            b = Background(**raw)
        except (ValidationError, TypeError):
            continue
        backgrounds[b.id] = b
    equipment = dict(rs.equipment)
    for raw in entries("items.json"):
        try:
            it = PackItem(**raw)
        except (ValidationError, TypeError):
            continue
        equipment[it.id] = _project_mechanics(it)
    return replace(rs, backgrounds=backgrounds, equipment=equipment)


@app.get("/api/chargen/options")
async def get_chargen_options(pack: str | None = None) -> JSONResponse:
    """Everything the person-NPC character builder renders — classes, races,
    backgrounds, spell lists, ability methods — the same projection the play
    app's chargen wizard uses (rules.chargen_view). With `?pack=`, the pack's
    own backgrounds/items join the pickers (module-kit S2)."""
    return JSONResponse(chargen_options(_chargen_ruleset(pack)))


def _equipped_items(char: Character, rs):
    """The character's worn/wielded gear as state Items, resolved from the SRD
    catalog — what the derivation needs to recompute AC/attack (no repo here, so we
    project straight from the ruleset, like chargen does)."""
    return [_project_srd_item(rs.equipment[i]) for i in char.equipped if i in rs.equipment]


def _grant_level_xp(char: Character) -> Character:
    """Authoring convenience: an authored NPC is assumed to have earned their
    level, so grant the XP the *next* level needs. XP is a gate during PLAY (you
    grind for it), but in the Forge the author just dials a level — this lets the
    same `level_up` engine advance them without a grind. Mutates and returns char."""
    nxt = char.level + 1
    if nxt <= MAX_LEVEL:
        char.xp = max(char.xp, xp_for_level(nxt))
    return char


@app.post("/api/chargen/preview")
async def post_chargen_preview(body: CharacterBuild, pack: str | None = None) -> JSONResponse:
    """Run the chargen firewall on an in-progress build and return either the
    aggregated errors or the fully-derived preview sheet — live wizard feedback,
    nothing persisted."""
    rs = _chargen_ruleset(pack)
    try:
        char, items = build_character(body, rs)
    except ChargenError as e:
        return JSONResponse({"ok": False, "errors": e.errors})
    return JSONResponse({"ok": True, "errors": [], "preview": preview_payload(char, items, rs)})


@app.post("/api/chargen/build")
async def post_chargen_build(body: CharacterBuild, pack: str | None = None) -> JSONResponse:
    """Build the level-1 character for real and return the full `Character` snapshot
    (what a person-NPC stores, 4b-3) alongside the preview. Same firewall as
    /preview."""
    rs = _chargen_ruleset(pack)
    try:
        char, items = build_character(body, rs)
    except ChargenError as e:
        return JSONResponse({"ok": False, "errors": e.errors})
    return JSONResponse({"ok": True, "errors": [],
                         "character": char.model_dump(mode="json"),
                         "preview": preview_payload(char, items, rs)})


@app.post("/api/chargen/levelup/plan")
async def post_chargen_levelup_plan(character: Character, pack: str | None = None) -> JSONResponse:
    """What the character's NEXT level requires (HP, ASI/feat, subclass, new
    spells) — drives the wizard's per-level choices. Operates on the transient
    character in the body; no repo. XP is granted so authoring isn't gated by it."""
    return JSONResponse(level_up_plan(_grant_level_xp(character), _chargen_ruleset(pack)))


class _ForgeLevelUpIn(BaseModel):
    character: Character
    choice: LevelUpChoice = LevelUpChoice()


@app.post("/api/chargen/levelup")
async def post_chargen_levelup(body: _ForgeLevelUpIn, pack: str | None = None) -> JSONResponse:
    """Advance the transient character one level and return the new snapshot. Unlike
    the play app this isn't event-sourced (authoring, not a live game), so a "roll"
    HP method without an explicit value just rolls here."""
    rs = _chargen_ruleset(pack)
    char, choice = _grant_level_xp(body.character), body.choice
    cc = rs.classes.get(char.sheet.char_class) if char.sheet else None
    if choice.hp_method == "roll" and choice.hp_roll is None and cc is not None:
        choice.hp_roll = random.randint(1, cc.hit_die)
    try:
        leveled = level_up(char, rs, choice, equipped_items=_equipped_items(char, rs),
                           char_id=char.id)
    except LevelUpError as e:
        return JSONResponse({"ok": False, "errors": e.errors}, status_code=400)
    return JSONResponse({"ok": True, "errors": [],
                         "character": leveled.model_dump(mode="json"),
                         "preview": preview_payload(leveled, _equipped_items(leveled, rs), rs)})


@app.post("/api/chargen/sheet")
async def post_chargen_sheet(character: Character, pack: str | None = None) -> JSONResponse:
    """Render an already-built Character into the same derived sheet the build
    preview shows — so a person-NPC can be reviewed without rebuilding it."""
    rs = _chargen_ruleset(pack)
    return JSONResponse({"ok": True, "preview": preview_payload(character, _equipped_items(character, rs), rs)})


def _safe_leaf(name: str) -> bool:
    """A filename that can't escape its folder — looser than _SAFE_NAME so audio files
    can keep author-friendly names (spaces, &, parentheses), just no path separators."""
    return bool(name) and "/" not in name and "\\" not in name and ".." not in name


class AudioIn(BaseModel):
    filename: str                  # the author's own file name (kept as-is)
    data: str                      # a data URL or bare base64 of the audio bytes


@app.post("/api/pack/{pack_id}/audio")
async def upload_audio(pack_id: str, body: AudioIn) -> JSONResponse:
    """Save a sound into the pack's audio/ folder (copied in, so the pack stays
    self-contained and shareable — like illustrations)."""
    d = _pack_dir(pack_id)
    if d is None:
        return JSONResponse({"error": f"no such pack: {pack_id!r}"}, status_code=404)
    name = body.filename.strip()
    if not _safe_leaf(name):
        return JSONResponse({"error": "unsafe filename"}, status_code=400)
    raw = body.data.split(",", 1)[-1]        # tolerate a "data:audio/...;base64," prefix
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return JSONResponse({"error": "bad audio data"}, status_code=400)
    audio = d / "audio"
    audio.mkdir(exist_ok=True)
    (audio / name).write_bytes(blob)
    return JSONResponse({"ok": True, "filename": name})


@app.get("/api/pack/{pack_id}/audio/{filename}", response_model=None)
async def get_audio(pack_id: str, filename: str) -> FileResponse | JSONResponse:
    """Serve a pack sound (for The Forge's preview play button)."""
    d = _pack_dir(pack_id)
    if d is None or not _safe_leaf(filename):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = d / "audio" / filename
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
    for t in ["items", "statblocks", "npcs", "lore", "quests", "ai_profiles"]:
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
