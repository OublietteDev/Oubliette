"""Pack + character portability (the v0.9 release feature).

Two shapes travel between installs:

  **World zips** (`<id>.oubliette-world.zip`) — a content pack folder, whole:
  the JSON files plus every asset subdir (audio/images/characters/monsters/
  portraits). Export walks the folder; import extracts it under the packs
  root (zip-slip guarded, size-capped) and then judges it with `load_pack` —
  the SAME validator the game boots worlds with, so an import that reports
  ok will genuinely play. The Forge accepts flawed imports (the editor is
  where you fix them); the play app refuses them (`require_valid=True`) so a
  casual player never installs a world that won't load.

  **Character bundles** (`<name>.oubliette-character.json`) — one runtime
  `Character` snapshot plus the item DEFINITIONS its gear references (so a
  pack sword still cuts in a world that never heard of it) plus the portrait
  as base64. Import rides the existing CHARACTER_CREATED event (characters +
  items), so replay/reload works unchanged.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ..state.models import Character, Item as StateItem
from .loader import _PACKS_ROOT, PackValidationError, load_pack

# Caps on what an import will unpack — far above any real pack (Atria with a
# full soundscape is ~15 MB), low enough that a hostile zip can't disk-bomb.
_MAX_MEMBERS = 5000
_MAX_TOTAL_BYTES = 750 * 1024 * 1024
_ID_RE = re.compile(r"^[a-z0-9_]+$")

CHARACTER_FORMAT = "oubliette-character"


# --- world zips ---------------------------------------------------------------

def export_pack(pack_id: str, packs_root: Path | None = None) -> bytes:
    """Zip a pack folder, whole, for sharing. Members are stored relative to
    the pack root (pack.json at the top), so the zip is self-describing — the
    id comes from the manifest inside, never the filename."""
    base = (packs_root or _PACKS_ROOT) / pack_id
    if not (base / "pack.json").is_file():
        raise ValueError(f"no such world: {pack_id!r}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(base.rglob("*")):
            if path.is_dir() or path.name.startswith("."):
                continue
            z.write(path, path.relative_to(base).as_posix())
    return buf.getvalue()


def _zip_manifest_prefix(names: list[str]) -> str:
    """Where pack.json lives inside the zip: "" for a flat export, or the
    single top-level folder a hand-zipped pack usually carries."""
    if "pack.json" in names:
        return ""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    if len(tops) == 1:
        top = next(iter(tops))
        if f"{top}/pack.json" in names:
            return f"{top}/"
    raise ValueError("this zip is not an Oubliette world — no pack.json inside")


def _safe_member(rel: str) -> bool:
    """A zip member path that can't escape the destination folder."""
    if not rel or rel.startswith("/") or "\\" in rel or ":" in rel:
        return False
    parts = rel.split("/")
    return all(p not in ("", ".", "..") for p in parts)


def import_pack(data: bytes, packs_root: Path | None = None,
                overwrite: bool = False, require_valid: bool = False) -> dict:
    """Install a world zip under the packs root and validate it whole.

    Returns {ok, id, name, version, issues, exists}:
      - `exists=True` (ok=False): a world with this id is already installed
        and `overwrite` was not set — the caller asks the player and retries.
      - `issues` non-empty: the loader's aggregated lint. With
        `require_valid=True` the extraction is rolled back (any overwritten
        world restored) and ok=False; otherwise the world is installed anyway
        for the Forge to fix (ok=True, issues attached).
    Raises ValueError for a hostile or non-world zip (nothing is written)."""
    root = packs_root or _PACKS_ROOT
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("that file is not a zip archive")
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > _MAX_MEMBERS:
            raise ValueError("this zip holds too many files to be a world")
        if sum(i.file_size for i in infos) > _MAX_TOTAL_BYTES:
            raise ValueError("this zip unpacks too large to be a world")
        prefix = _zip_manifest_prefix([i.filename for i in infos])
        try:
            manifest = json.loads(z.read(f"{prefix}pack.json").decode("utf-8"))
        except Exception:
            raise ValueError("the world's pack.json is unreadable")
        pack_id = manifest.get("id") if isinstance(manifest, dict) else None
        if not isinstance(pack_id, str) or not _ID_RE.match(pack_id):
            raise ValueError("the world's pack.json carries no usable id")
        name = manifest.get("name") or pack_id
        version = manifest.get("version")

        dest = root / pack_id
        backup: Path | None = None
        if dest.exists():
            if not overwrite:
                return {"ok": False, "exists": True, "id": pack_id,
                        "name": name, "version": version, "issues": []}
            # Same shelf the Forge's save backups use — an overwritten world
            # is recoverable, never gone.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = root.parent / "pack-backups" / pack_id / f"import-{stamp}"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(backup))

        members = []
        for info in infos:
            rel = info.filename[len(prefix):]
            if not _safe_member(rel):
                raise ValueError(f"refusing a suspicious path in the zip: {info.filename!r}")
            members.append((info, rel))
        try:
            for info, rel in members:
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            if backup is not None:
                shutil.move(str(backup), str(dest))
            raise

    issues: list[str] = []
    try:
        load_pack(pack_id, packs_root=root)
    except PackValidationError as e:
        issues = list(e.errors)
    if issues and require_valid:
        shutil.rmtree(dest, ignore_errors=True)
        if backup is not None:
            shutil.move(str(backup), str(dest))
        return {"ok": False, "exists": False, "id": pack_id, "name": name,
                "version": version, "issues": issues}
    return {"ok": True, "exists": False, "id": pack_id, "name": name,
            "version": version, "issues": issues}


# --- character bundles ----------------------------------------------------------

def character_bundle(char: Character, items: list[StateItem],
                     portrait: tuple[str, bytes] | None = None) -> dict:
    """The self-contained export of one hero: the runtime snapshot, the item
    definitions their gear references, and the portrait image (mime, bytes)."""
    return {
        "format": CHARACTER_FORMAT,
        "version": 1,
        "character": char.model_dump(mode="json"),
        "items": [it.model_dump(mode="json") for it in items],
        "portrait": ({"mime": portrait[0],
                      "data": base64.b64encode(portrait[1]).decode("ascii")}
                     if portrait else None),
    }


def parse_character_bundle(raw) -> tuple[Character, list[StateItem],
                                         tuple[str, bytes] | None]:
    """Read a character bundle (or, liberally, a bare Character JSON — the
    Forge's person-NPC sidecars import too). Returns (character, items,
    portrait). The character comes back as a PC with portrait/id left for the
    importer to assign. Raises ValueError with a friendly message when the
    file isn't a character either app could read."""
    if not isinstance(raw, dict):
        raise ValueError("that file is not a character export")
    body = raw.get("character") if "character" in raw else raw
    if "character" in raw and raw.get("format") not in (None, CHARACTER_FORMAT):
        raise ValueError("that file is a different kind of export, not a character")
    try:
        char = Character.model_validate(body)
    except (ValidationError, TypeError) as e:
        raise ValueError(f"the character inside doesn't read as one ({type(e).__name__})")
    char = char.model_copy(update={"kind": "pc", "portrait": None})
    items: list[StateItem] = []
    for i, raw_item in enumerate(raw.get("items") or []):
        try:
            items.append(StateItem.model_validate(raw_item))
        except (ValidationError, TypeError):
            raise ValueError(f"item #{i + 1} in the bundle doesn't read as an item")
    portrait = None
    p = raw.get("portrait")
    if isinstance(p, dict) and p.get("data"):
        try:
            portrait = (str(p.get("mime") or "image/png"),
                        base64.b64decode(p["data"], validate=True))
        except Exception:
            portrait = None                     # a broken portrait never blocks the hero
    return char, items, portrait
