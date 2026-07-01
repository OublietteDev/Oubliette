"""Web front-end: a FastAPI app serving a single-page chat UI for Oubliette Table.

One process: it holds a Session + TurnLoop and exposes a tiny JSON API the page
calls. The page renders the DM's narration AND the live authoritative state
(sheet, inventory, canon) — surfacing the numbers, which is the whole point.

Run: `oubliette-play` (or `python -m oubliette.app.server`). It opens a browser
to the chat window. Uses the real model when ANTHROPIC_API_KEY is set (env or
.env), else the scripted offline DM.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..content.loader import DEFAULT_PACK, _PACKS_ROOT, available_packs
from ..content.ruleset import Ruleset, load_ruleset
from ..journal.store import Journal, JournalStore
from ..record.events import EventKind, StateOp
from ..record.store import SqliteEventStore
from ..record.rng import Rng
from ..rules import derive
from ..rules.chargen_view import chargen_options, preview_payload
from ..rules.chargen import CharacterBuild, ChargenError, build_character
from ..rules.rest import long_rest_ops, short_rest_ops, reprepare_window_open
from ..rules.levelup import (LevelUpChoice, LevelUpError, level_up, level_up_plan,
                            xp_progress)
from ..runtime.loop import TurnLoop
from ..runtime.session import Session
from ..dm.brain import Brain
from ..dm.context import region_root
from ..enums import Ability, Skill
from ..state.models import Character
from ..state.repository import StateError
from ..table import TONE_PRESETS, TableContract
from ..tools.dispatch import ToolApplyError
from ..trade.service import build_state, buy_transact, checkout_transact, sell_transact
from ..llm import providers
from .repl import _load_dotenv, _pick_client

STATIC = Path(__file__).parent / "static"
_SRD_PORTRAITS = Path(__file__).parents[1] / "content" / "srd" / "portraits"
DB_PATH = os.environ.get("OUBLIETTE_DB", "oubliette-save.sqlite")
# Player-uploaded PC portraits — campaign runtime data, so they live beside the save
# DB (not in shipped content). The event log records the filename; the bytes live here.
_PC_PORTRAITS = Path(DB_PATH).resolve().parent / "character-portraits"
# image MIME (sent as the upload's Content-Type) -> stored file extension
_PORTRAIT_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg",
                      "image/webp": ".webp", "image/gif": ".gif"}
_PORTRAIT_MAX_BYTES = 8 * 1024 * 1024          # 8 MB — generous for a portrait, bounded

app = FastAPI(title="Oubliette Table")


class _Game:
    """Holds the live session/loop. One game per server process (single-player)."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.client_name = "scripted"
        self.pack_id = DEFAULT_PACK            # world for a new game (saves pin their own)
        self._open()

    def _open(self) -> None:
        self.store = SqliteEventStore(DB_PATH)
        self.session = Session.open(self.store, pack_id=self.pack_id)
        self.pack_id = self.session.pack_id or self.pack_id   # reflect the loaded/pinned world
        self.journal = JournalStore(DB_PATH)   # player notes — never enters DM context
        client, self.client_name = _pick_client(force_scripted=False)
        self.rng = Rng(seed=1234, record=self.session.emit_log)
        self.loop = TurnLoop(self.session, self.rng, Brain(client))

    def refresh_client(self) -> None:
        """Re-pick the model client — call AFTER .env is loaded so a key present
        only in .env still selects the live DM (the game is built at import)."""
        client, self.client_name = _pick_client(force_scripted=False)
        self.loop.brain = Brain(client)

    def new_game(self, pack_id: str | None = None,
                 table: TableContract | None = None) -> None:
        """Erase the save and start fresh — in `pack_id` if given, else the same
        world as before. `table` sets the campaign's contract (tone + boundaries)
        agreed at New Game time; it's recorded so it persists and reaches the DM."""
        self.store.close()
        self.journal.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        if pack_id:
            self.pack_id = pack_id
        self._open()
        if table is not None:
            self.session.emit_contract(table, reason="new game")

    def reload_world(self) -> None:
        """Re-read the pack from disk and rebuild the session by replaying the save —
        so edits made in The Forge (new sounds, art, places) show up in a running game
        WITHOUT starting over. The event log is untouched; play state replays identically
        on top of the refreshed pack baseline."""
        self.store.close()
        self.journal.close()
        self._open()


GAME = _Game()


# --- serialization ----------------------------------------------------------
def _pc_view(pc) -> dict:
    """The HUD view of one player character (the sidebar + party roster)."""
    return {
        "id": pc.id, "name": pc.name, "hp": pc.hp, "max_hp": pc.max_hp,
        "gold": pc.gold, "xp": pc.xp, "xp_progress": xp_progress(pc),
        "armor_class": pc.armor_class,
        "conditions": list(pc.conditions),
        "inventory": [
            {"id": s.item_id, "name": _stack_label(_ruleset(), s), "qty": s.qty,
             "spell": s.spell, "spell_level": s.spell_level}
            for s in pc.inventory
        ],
    }


def _snapshot() -> dict:
    repo = GAME.session.repo
    pc = repo.pc()
    location = GAME.session.location
    # Who's here: NPCs homed at the party's current location (everyone when there's
    # no location, e.g. a custom seed) — mirrors what the DM is told.
    npcs = repo.npcs()
    if location is not None:
        npcs = [n for n in npcs if n.home_location == location]
    # The party may pursue one quest at a time (the dispatcher enforces it). Surface
    # that single active quest for the sidebar; completed/failed ones drop out and
    # live on only in the player's journal if they choose to keep them.
    active_quests = GAME.session.quests.active()
    quest = None
    if active_quests:
        q = active_quests[0]
        quest = {"id": q.id, "title": q.title, "text": q.text, "notes": list(q.notes)}
    return {
        "scene": GAME.session.scene,
        "ended": GAME.session.ended,
        "combat_pending": GAME.session.pending_combat is not None,
        "time_of_day": GAME.session.time_of_day,
        "weather": GAME.session.weather,
        "pc": _pc_view(pc),                          # the lead PC (back-compat)
        "party": [_pc_view(c) for c in repo.party()],  # the whole roster (HUD)
        "npcs": [
            {"id": n.id, "name": n.name, "disposition": n.disposition, "gold": n.gold}
            for n in npcs
        ],
        # The panel shows SESSION canon (the DM's live inventions). Authored pack
        # canon stays backstage — it powers the DM's retrieval, but dumping every
        # authored place/NPC here would spoil unvisited content.
        "canon": [
            {"id": r.id, "type": r.entity_type, "name": r.name,
             "text": r.text, "status": r.status}
            for r in GAME.session.canon.all() if r.origin != "authored"
        ],
        "quest": quest,                              # the lone active quest, or None
    }


def _has_progress() -> bool:
    """True if the current save has been played at all (the player has taken at least
    one turn) — drives the start menu's 'Continue'. A brand-new save has only the
    session-start marker and, optionally, a contract, so it has nothing to resume."""
    return any(ev.kind == EventKind.PLAYER_MESSAGE.value
               for ev in GAME.session.store.read_all())


def _build_inventory() -> dict:
    """Per party-member inventory with item details for the inventory panel."""
    repo = GAME.session.repo
    party = []
    for c in repo.party():
        items = []
        rs = _ruleset()
        for s in c.inventory:
            it = repo.get_item(s.item_id)
            items.append({
                "item_id": s.item_id, "name": _stack_label(rs, s), "category": it.category,
                "qty": s.qty, "value": it.base_value, "armor_class": it.armor_class,
                "equippable": it.equippable, "equipped": s.item_id in c.equipped,
                "tags": it.tags, "spell": s.spell, "spell_name": _spell_name(rs, s.spell),
                "spell_level": s.spell_level,
            })
        party.append({"id": c.id, "name": c.name, "items": items})
    return {"party": party}


def _describe_applied(rt) -> str:
    if rt.canon_create is not None:
        return f"introduced {rt.canon_create.entity_type} “{rt.canon_create.name}” (provisional)"
    if rt.canon_promote is not None:
        return f"confirmed canon {rt.canon_promote}"
    return f"{rt.tool}: {TurnLoop._ops_summary(rt.ops)}"


def _top_location_id() -> str | None:
    """The party's enclosing top-level area (walk up the parent chain) — quest-card
    illustrations key off this, not the specific sub-room. Same "what area am I in"
    notion the DM context uses to scope ambient quest awareness."""
    return region_root(GAME.session.location, GAME.session.places)


def _quest_beats(report) -> list[dict]:
    """Visible quest moments (start/update/complete) for the chat stream, with the
    current area's illustration. Computed from the turn's tool calls — the DM never
    sees or manages these cards."""
    top = _top_location_id() or "_"
    image = f"/api/world-image/{top}"
    beats: list[dict] = []
    for rt in report.applied:
        if rt.quest_start is not None:
            beats.append({"kind": "started", "title": rt.quest_start.title, "detail": "", "image": image})
        elif rt.quest_accept is not None:
            aq = GAME.session.authored_quests.get(rt.quest_accept.quest_id)
            title = aq.title if aq is not None else rt.quest_accept.quest_id
            beats.append({"kind": "started", "title": title, "detail": "", "image": image})
        elif rt.quest_update is not None:
            q = GAME.session.quests.get(rt.quest_update.quest_id)
            title = q.title if q is not None else rt.quest_update.quest_id
            status = rt.quest_update.status
            kind = status if status in ("completed", "failed") else "updated"
            beats.append({"kind": kind, "title": title,
                          "detail": rt.quest_update.note or "", "image": image})
    return beats


def _turn_payload(report) -> dict:
    roll = None
    if report.roll_outcome is not None and report.assessment.roll is not None:
        roll = {
            "spec": report.roll_outcome.spec, "total": report.roll_outcome.total,
            "dc": report.assessment.roll.dc, "result": report.roll_result,
            "purpose": report.roll_outcome.purpose,
        }
    combat = None
    if report.combat_result is not None:
        combat = {"outcome": report.combat_result.outcome,
                  "xp": report.combat_result.xp_award}
    return {
        "narration": report.narration,
        "roll": roll,
        # quest tools surface as their own cards (quest_beats), not raw chips
        "applied": [_describe_applied(rt) for rt in report.applied
                    if rt.quest_start is None and rt.quest_update is None],
        "quest_beats": _quest_beats(report),
        "combat": combat,
        "trade": report.trade_open.model_dump() if report.trade_open is not None else None,
        "meta_notice": report.meta_notice,
        "combat_pending": getattr(report, "combat_pending", False),
        "session_ended": report.session_ended,
        "verb": report.assessment.intent.verb.value,
        "tier": report.assessment.tier.value,
        "state": _snapshot(),
        "soundscape": _soundscape(),   # the party may have travelled — refresh the mix
    }


# --- API --------------------------------------------------------------------
class TurnIn(BaseModel):
    text: str
    ooc: bool = False          # player's explicit out-of-character signal (composer toggle)


@app.get("/")
async def index() -> FileResponse:
    # no-cache: always revalidate so a refresh never serves a stale page (e.g. an
    # old copy missing the menu). The single-file UI has no other assets to bust.
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache, max-age=0"})


@app.get("/api/state")
async def get_state() -> JSONResponse:
    return JSONResponse({"state": _snapshot(), "model": GAME.client_name,
                         "has_progress": _has_progress(), "soundscape": _soundscape()})


@app.get("/api/table")
async def get_table() -> JSONResponse:
    """This campaign's table contract + the available tone presets (for Settings)."""
    return JSONResponse({"table": GAME.session.table.model_dump(), "presets": TONE_PRESETS})


@app.put("/api/table")
async def put_table(body: TableContract) -> JSONResponse:
    """Update the campaign's table contract from Settings — recorded so it persists
    and reaches the DM next turn."""
    async with GAME.lock:
        stored = GAME.session.emit_contract(body, reason="settings edit")
        return JSONResponse({"ok": True, "table": stored.model_dump()})


@app.get("/api/world-image/{place_id}")
async def world_image(place_id: str) -> FileResponse:
    """A place's illustration (for quest cards). Serves the pack's image if the
    place has one, else a tasteful fallback so cards always look complete."""
    # no-cache (revalidate) rather than a long max-age, so newly-added or changed
    # art shows immediately instead of a stale image lingering for a day.
    node = GAME.session.places.get(place_id)
    if node is not None and node.image and "/" not in node.image and "\\" not in node.image:
        path = _PACKS_ROOT / (GAME.pack_id or "") / "images" / node.image
        if path.is_file():
            return FileResponse(path, headers={"Cache-Control": "no-cache"})
    return FileResponse(STATIC / "img" / "quest-fallback.svg",
                        headers={"Cache-Control": "no-cache"})


def _visited_place_ids() -> set:
    """Places the party has actually reached: the start location plus every travel
    destination in the log. Movement is DM-driven (the `travel` tool), so this is the
    full record of where they've been — the basis for map discovery."""
    s = GAME.session
    visited: set = set()
    if s.start_location:
        visited.add(s.start_location)
    if s.location:
        visited.add(s.location)
    for ev in s.store.read_all():
        if ev.kind == EventKind.LOCATION_CHANGED.value:
            to = ev.payload.get("to")
            if to:
                visited.add(to)
    return visited


def _children_by_parent() -> dict:
    """Group places by their parent id (None = top-level area)."""
    kids: dict = {}
    for node in GAME.session.places.values():
        kids.setdefault(node.parent, []).append(node)
    return kids


def _subtree_visited(area_id: str, kids: dict, visited: set) -> bool:
    """True if the area itself OR any place nested under it has been visited —
    i.e. the party has set foot somewhere inside this area, so it's 'discovered'."""
    stack, seen = [area_id], set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in visited:
            return True
        for child in kids.get(cur, []):
            stack.append(child.id)
    return False


def _map_image_url(filename: str | None) -> str | None:
    """A served URL for a pack map background (world map or a place's sub-map), or None."""
    return f"/api/map-image/{filename}" if filename else None


@app.get("/api/map")
async def get_map() -> JSONResponse:
    """The player's world map: top-level areas, each a PIN at its authored position on
    the world-map background. Hover reveals name + description; a discovered area can be
    opened (double-click) to its own sub-map (`sub_map` background + child pins).

    Discovery redaction is done HERE, server-side, so unvisited content never reaches
    the browser. An area the party hasn't reached (itself or anything nested in it) comes
    back with no name, no description, no children and no sub-map — only a placeholder
    handle and its position (a bare 'Unknown' pin). It stays a mystery until visited; the
    map shows the world's SHAPE from the start, but identities are earned by travelling.

    DM-invented locations never appear: `travel` only resolves to pack places, so the
    party can't stand on one, and the map iterates pack places only — a graceful no-op."""
    s = GAME.session
    kids = _children_by_parent()
    visited = _visited_place_ids()
    current_top = _top_location_id()
    tops = kids.get(None, [])

    areas = []
    for i, node in enumerate(tops):
        known = _subtree_visited(node.id, kids, visited)
        child_nodes = kids.get(node.id, [])
        children = [{
            "handle": c.id,
            "name": c.name,
            "description": c.description,
            "position": c.position,                  # pin on this area's sub-map
            "visited": c.id in visited,
            "current": c.id == s.location,
        } for c in child_nodes] if known else []     # undiscovered areas reveal no rooms
        areas.append({
            "handle": node.id if known else f"hidden-{i}",
            "known": known,
            "name": node.name if known else None,
            "description": node.description if known else None,
            "position": node.position,               # {x,y} percent, or null (client falls back)
            "current": node.id == current_top,
            "has_children": known and bool(child_nodes),   # drillable only once discovered
            "sub_map": _map_image_url(node.map_image) if known else None,
            "children": children,
        })

    current_name = None
    if current_top is not None:
        node = s.places.get(current_top)
        current_name = node.name if node is not None else None
    return JSONResponse({
        "world_map": _map_image_url(s.world_map),
        "current_area_name": current_name,
        "areas": areas,
    })


@app.get("/api/map-image/{filename}", response_model=None)
async def map_image(filename: str) -> FileResponse | JSONResponse:
    """Serve a pack map background (the world map, or a place's sub-map) by filename,
    from the loaded pack's images/ folder."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = _PACKS_ROOT / (GAME.pack_id or "") / "images" / filename
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def _soundscape() -> list:
    """The active audio layers at the party's current location — the flat list the
    browser mixer renders (design oubliette-audio-mixer §2/§3). Inheritance (S2): the
    current place's beds, PLUS any ancestor bed marked scope='passed_down' — so a
    top-level theme rides down into every child while local sounds stay put. Conditions
    (time/weather) and one-shots arrive in later seams. Resolution lives here in code so
    the client stays a dumb renderer."""
    places = GAME.session.places
    layers, seen, walked = [], set(), set()
    cur = places.get(GAME.session.location)
    at_current = True
    while cur is not None and cur.id not in walked:       # current → ancestors
        walked.add(cur.id)
        for cue in getattr(cur, "sounds", ()):
            kind = cue.get("kind", "bed")
            if kind not in ("bed", "oneshot"):
                continue
            if not at_current and cue.get("scope", "local") != "passed_down":
                continue                                  # ancestors give only passed-down cues
            if cue.get("time", "any") not in ("any", GAME.session.time_of_day):
                continue                                  # time/weather conditions (S5)
            if cue.get("weather", "any") not in ("any", GAME.session.weather):
                continue
            name = cue.get("file")
            if not name or name in seen:
                continue
            seen.add(name)
            layer = {
                "file": name,
                "url": f"/api/audio/{quote(name)}",   # encode &, spaces, etc. in the filename
                "kind": kind,
                "category": cue.get("category", "sfx"),
                "gain": cue.get("gain", 1.0),
            }
            if kind == "oneshot":                         # sparse, randomized firing (S3)
                layer["min_gap"] = cue.get("min_gap")
                layer["max_gap"] = cue.get("max_gap")
            layers.append(layer)
        cur = places.get(cur.parent)
        at_current = False
    return layers


@app.get("/api/soundscape")
async def get_soundscape() -> JSONResponse:
    return JSONResponse({"soundscape": _soundscape()})


@app.get("/api/audio/{filename}", response_model=None)
async def audio_file(filename: str) -> FileResponse | JSONResponse:
    """Serve a pack sound (a bed loop or one-shot) by filename, from the loaded pack's
    audio/ folder."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = _PACKS_ROOT / (GAME.pack_id or "") / "audio" / filename
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.post("/api/turn")
async def post_turn(body: TurnIn) -> JSONResponse:
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if GAME.session.ended:
        return JSONResponse({"error": "the DM has ended this session", "ended": True}, status_code=409)
    if GAME.session.pending_combat is not None:
        return JSONResponse(
            {"error": "a fight is underway — enter the Arena to resolve it", "combat_pending": True},
            status_code=409)
    async with GAME.lock:  # serialize turns; combat/state mutation isn't reentrant
        report = await GAME.loop.take_turn(text, ooc=body.ooc)
        return JSONResponse(_turn_payload(report))


@app.post("/api/turn/stream", response_model=None)
async def post_turn_stream(body: TurnIn) -> StreamingResponse | JSONResponse:
    """Server-Sent Events: stream narration deltas, then a final payload.
    Events: {"t":"delta","v":"..."} during generation, then {"t":"done", ...}."""
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if GAME.session.ended:
        return JSONResponse({"error": "the DM has ended this session", "ended": True}, status_code=409)
    if GAME.session.pending_combat is not None:
        return JSONResponse(
            {"error": "a fight is underway — enter the Arena to resolve it", "combat_pending": True},
            status_code=409)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_text(delta: str) -> None:
        # Called from the model's worker thread → hop back onto the loop safely.
        loop.call_soon_threadsafe(queue.put_nowait, {"t": "delta", "v": delta})

    def _emit(item: dict) -> None:
        # Enqueue via the loop so a final 'done' lands AFTER all delta callbacks
        # (which on_text scheduled the same way) — preserves stream order.
        loop.call_soon_threadsafe(queue.put_nowait, item)

    async def run_turn() -> None:
        async with GAME.lock:
            try:
                report = await GAME.loop.take_turn(text, on_text=on_text, ooc=body.ooc)
                payload = _turn_payload(report)
                payload["t"] = "done"
                _emit(payload)
            except Exception as e:  # surface failures to the client, don't hang
                _emit({"t": "error", "error": str(e)})

    async def events():
        task = asyncio.create_task(run_turn())
        try:
            while True:
                item = await queue.get()
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("t") in ("done", "error"):
                    break
        finally:
            await task

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/combat/enter")
async def post_combat_enter() -> JSONResponse:
    """Play the staged tactical fight: launches The Arena (a desktop window),
    blocks until the player exits, then folds the outcome back into the story as
    one COMBAT_RESULT event and clears the combat lock."""
    if GAME.session.pending_combat is None:
        return JSONResponse(
            {"error": "no combat is staged", "combat_pending": False}, status_code=409)
    async with GAME.lock:
        report = await GAME.loop.enter_combat()
        return JSONResponse(_turn_payload(report))


class TradeActionIn(BaseModel):
    merchant_id: str
    action: str          # "buy" | "sell"
    item_id: str
    qty: int = 1


@app.post("/api/trade")
async def post_trade(body: TradeActionIn) -> JSONResponse:
    async with GAME.lock:
        repo = GAME.session.repo
        try:
            if body.action == "buy":
                tx = buy_transact(repo, body.merchant_id, body.item_id, body.qty)
            elif body.action == "sell":
                tx = sell_transact(repo, body.merchant_id, body.item_id, body.qty)
            else:
                return JSONResponse({"ok": False, "error": "unknown action"}, status_code=400)
            rt = GAME.loop.dispatcher.resolve(tx)              # validate
            GAME.session.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
            ok, error = True, None
        except (ToolApplyError, StateError) as e:
            ok, error = False, str(e)
        # always return a fresh trade view + game state so the UI re-renders
        try:
            trade = build_state(repo, body.merchant_id).model_dump()
        except StateError:
            trade = None
        return JSONResponse({"ok": ok, "error": error, "trade": trade, "state": _snapshot()})


class CheckoutIn(BaseModel):
    merchant_id: str
    buy: list[dict] = []     # [{item_id, qty}]
    sell: list[dict] = []


@app.post("/api/trade/checkout")
async def post_checkout(body: CheckoutIn) -> JSONResponse:
    """Settle a whole basket at listed prices as one validated transact."""
    async with GAME.lock:
        repo = GAME.session.repo
        buy = [(e["item_id"], int(e.get("qty", 1))) for e in body.buy]
        sell = [(e["item_id"], int(e.get("qty", 1))) for e in body.sell]
        try:
            tx = checkout_transact(repo, body.merchant_id, buy, sell)
            rt = GAME.loop.dispatcher.resolve(tx)
            GAME.session.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
            ok, error = True, None
        except (ToolApplyError, StateError) as e:
            ok, error = False, str(e)
        try:
            trade = build_state(repo, body.merchant_id).model_dump()
        except StateError:
            trade = None
        return JSONResponse({"ok": ok, "error": error, "trade": trade, "state": _snapshot()})


@app.get("/api/inventory")
async def get_inventory() -> JSONResponse:
    return JSONResponse(_build_inventory())


class EquipIn(BaseModel):
    char_id: str
    item_id: str
    equip: bool


@app.post("/api/equip")
async def post_equip(body: EquipIn) -> JSONResponse:
    """Player loadout change — bounded (you can only equip an equippable item you
    hold), validated by code, and recorded so it replays."""
    async with GAME.lock:
        repo = GAME.session.repo
        try:
            char = repo.get_character(body.char_id)
            if char.item_qty(body.item_id) <= 0:
                raise StateError("you are not carrying that item")
            if body.equip and not repo.get_item(body.item_id).equippable:
                raise StateError("that item cannot be equipped")
            loadout = [i for i in char.equipped if i != body.item_id]
            if body.equip:
                loadout.append(body.item_id)
            GAME.session.emit_state(
                EventKind.EQUIP_CHANGED, [StateOp.equip(body.char_id, loadout)],
                reason=f"player {'equipped' if body.equip else 'unequipped'} {body.item_id}")
            ok, error = True, None
        except StateError as e:
            ok, error = False, str(e)
        return JSONResponse({"ok": ok, "error": error, "inventory": _build_inventory(), "state": _snapshot()})


@app.get("/api/journal")
async def get_journal() -> JSONResponse:
    """Player notes. Deliberately separate from the turn path — never enters the
    DM's context (so it can't induce hallucination or bloat the prompt)."""
    return JSONResponse(GAME.journal.get().model_dump())


@app.put("/api/journal")
async def put_journal(body: Journal) -> JSONResponse:
    async with GAME.lock:
        GAME.journal.put(body)
        return JSONResponse({"ok": True})


@app.get("/api/packs")
async def get_packs() -> JSONResponse:
    """The worlds a new game can start in, and which one is playing now."""
    return JSONResponse({"packs": available_packs(), "current": GAME.pack_id})


# --- chargen (CS2): serialize the ruleset for the wizard, and validate live ---
def _ruleset() -> Ruleset:
    """The SRD ruleset for chargen — the session's (global, pack-independent), with a
    load fallback for the custom-seed case."""
    return GAME.session.ruleset or load_ruleset()


def _item_name(rs: Ruleset, item_id: str) -> str:
    it = rs.equipment.get(item_id)
    return it.name if it is not None else item_id


def _spell_name(rs: Ruleset, spell_id: str | None) -> str | None:
    """Display name for a scroll's inscribed spell (A5). Falls back to a title-cased id
    so an authored spell not in the SRD ruleset still reads cleanly."""
    if not spell_id:
        return None
    s = rs.spells.get(spell_id)
    return s.name if s is not None else spell_id.replace("_", " ").title()


_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th",
             6: "6th", 7: "7th", 8: "8th", 9: "9th"}


def _stack_label(rs: Ruleset, stack) -> str:
    """An inventory line's display name, annotated with a scroll's inscribed spell — and
    its cast level when it's a commissioned/upcast scroll (e.g. 'Spell Scroll: Fireball
    (5th-level)')."""
    base = _item_name(rs, stack.item_id)
    sp = _spell_name(rs, stack.spell)
    if not sp:
        return base
    lvl = getattr(stack, "spell_level", None)
    if lvl:                                    # 0 (cantrip) and None both read plainly
        return f"{base}: {sp} ({_ORDINALS.get(lvl, str(lvl))}-level)"
    return f"{base}: {sp}"


def _chargen_options() -> dict:
    # The ruleset → wizard-options projection moved to rules.chargen_view so the
    # Forge renders chargen from the same source of truth (no drift).
    return chargen_options(_ruleset())


def _preview_payload(char: Character, items, rs: Ruleset) -> dict:
    return preview_payload(char, items, rs)


@app.get("/api/chargen/options")
async def get_chargen_options() -> JSONResponse:
    return JSONResponse(_chargen_options())


# --- the bestiary (global SRD monster reference) -----------------------------
_CR_FRACTIONS = {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}


def _cr_label(cr: float | None) -> str:
    """Human CR string: fractions for the sub-1 tiers, plain ints otherwise."""
    if cr is None:
        return "—"
    if cr in _CR_FRACTIONS:
        return _CR_FRACTIONS[cr]
    return str(int(cr)) if cr == int(cr) else str(cr)


def _action_view(a) -> dict:
    return {"name": a.name, "desc": a.desc, "attack_bonus": a.attack_bonus,
            "reach": a.reach, "target": a.target,
            "damage": a.damage, "damage_type": a.damage_type}


def _statblock_view(sb, source: str, scope: str) -> dict:
    """One stat block, flattened for the panel. Empty/None fields are passed through
    so the client can decide what to show (graceful degradation for minimal blocks).
    `source` is the display label (pack name or "SRD"); `scope` ("srd"/"pack") routes
    the portrait endpoint to the right images directory."""
    return {
        "id": sb.id, "name": sb.name, "kind": sb.kind,
        "key": f"{scope}:{sb.id}",       # unique across the merged list (pack ids can shadow SRD)
        "source": source, "scope": scope,
        "portrait_url": f"/api/monster-portrait/{scope}/{sb.id}",
        "size": sb.size, "type": sb.type, "alignment": sb.alignment,
        "cr": sb.cr, "cr_label": _cr_label(sb.cr), "xp": sb.xp,
        "abilities": dict(sb.abilities),
        "hp": sb.hp, "hit_dice": sb.hit_dice,
        "armor_class": sb.armor_class, "ac_desc": sb.ac_desc,
        "speed": dict(sb.speed),
        "saves": dict(sb.saves), "skills": list(sb.skills),
        "skill_bonuses": dict(sb.skill_bonuses),
        "damage_vulnerabilities": list(sb.damage_vulnerabilities),
        "damage_resistances": list(sb.damage_resistances),
        "damage_immunities": list(sb.damage_immunities),
        "condition_immunities": list(sb.condition_immunities),
        "senses": dict(sb.senses), "languages": sb.languages,
        "traits": list(sb.traits),
        "actions": [_action_view(a) for a in sb.actions],
        "legendary_actions": [_action_view(a) for a in sb.legendary_actions],
        "reactions": [_action_view(a) for a in sb.reactions],
        "description": sb.description,
    }


def _encountered_creature_keys() -> set:
    """Bestiary keys (`scope:id`) the party has faced in a resolved encounter, recorded
    on COMBAT_RESULT events. The basis for the bestiary knowledge gate — mirrors
    `_visited_place_ids()` for the map."""
    keys: set = set()
    for ev in GAME.session.store.read_all():
        if ev.kind == EventKind.COMBAT_RESULT.value:
            for k in ev.payload.get("encountered", []) or []:
                keys.add(k)
    return keys


def _bestiary_gate():
    """The active per-world bestiary knowledge cutoff, or None when this world doesn't
    gate (no manifest setting, or `enabled: false`)."""
    g = getattr(GAME.session, "bestiary_gate", None)
    return g if (g is not None and getattr(g, "enabled", False)) else None


def _cr_value(cr) -> float:
    """CR for threshold comparison; an unrated creature (None) sorts as -1, so it stays
    on the always-known side of any non-negative threshold."""
    return cr if cr is not None else -1.0


def _creature_known(scope: str, mid: str, cr, gate, encountered) -> bool:
    """Whether a bestiary entry is revealed. With no gate, everything is known.
    Otherwise creatures at/below the CR threshold are always known; above it, only
    once the party has encountered them in play."""
    if gate is None:
        return True
    if _cr_value(cr) <= gate.max_known_cr:
        return True
    return f"{scope}:{mid}" in encountered


@app.get("/api/bestiary")
async def get_bestiary() -> JSONResponse:
    """The bestiary the panel renders: the loaded world's own monsters PLUS the global
    SRD library, merged into one list ordered by challenge rating then name. Each entry
    is tagged with its source so the panel can badge pack vs SRD.

    If the world sets a knowledge gate, above-threshold creatures the party hasn't
    encountered are withheld entirely and reported only as a `hidden_count` — the panel
    shows them as a locked "Undiscovered" tally. They come online once faced in combat."""
    rs = _ruleset()
    session = GAME.session
    pack_label = session.pack_name or "This World"
    views = [_statblock_view(sb, pack_label, "pack") for sb in session.statblocks]
    views += [_statblock_view(sb, "SRD", "srd") for sb in rs.bestiary.values()]
    # stable: challenge rating, then name (the panel groups by CR tier).
    views.sort(key=lambda v: (v["cr"] if v["cr"] is not None else -1.0, v["name"]))
    gate = _bestiary_gate()
    if gate is None:
        return JSONResponse({"monsters": views, "gated": False, "hidden_count": 0})
    encountered = _encountered_creature_keys()
    known = [v for v in views if _creature_known(v["scope"], v["id"], v["cr"], gate, encountered)]
    return JSONResponse({"monsters": known, "gated": True,
                         "hidden_count": len(views) - len(known)})


def _monster_portrait_path(scope: str, mid: str) -> Path | None:
    """Resolve a monster's portrait file: the stat block's `portrait` field if set,
    else `<id>.png`, under the scope's portraits/ dir. None if nothing on disk."""
    if scope == "srd":
        sb = _ruleset().bestiary.get(mid)
        base = _SRD_PORTRAITS
    elif scope == "pack":
        sb = next((s for s in GAME.session.statblocks if s.id == mid), None)
        base = _PACKS_ROOT / (GAME.pack_id or "") / "portraits"
    else:
        return None
    if sb is None:
        return None
    fname = sb.portrait or f"{mid}.png"
    if "/" in fname or "\\" in fname:        # no path traversal out of the dir
        return None
    path = base / fname
    return path if path.is_file() else None


@app.get("/api/monster-portrait/{scope}/{mid}")
async def monster_portrait(scope: str, mid: str) -> FileResponse:
    """A monster's portrait (combat-board token art + the bestiary detail). Serves the
    authored image if present, else a neutral silhouette so every monster has one.

    Under a knowledge gate, a creature the party hasn't encountered serves the
    silhouette regardless — so its art can't be peeked by guessing the URL."""
    gate = _bestiary_gate()
    if gate is not None:
        sb = (_ruleset().bestiary.get(mid) if scope == "srd"
              else next((s for s in GAME.session.statblocks if s.id == mid), None))
        if sb is not None and not _creature_known(scope, mid, sb.cr, gate, _encountered_creature_keys()):
            return FileResponse(STATIC / "img" / "monster-fallback.svg",
                                headers={"Cache-Control": "no-cache"})
    path = _monster_portrait_path(scope, mid)
    if path is not None:
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    return FileResponse(STATIC / "img" / "monster-fallback.svg",
                        headers={"Cache-Control": "no-cache"})


# --- the read-only character sheet (CS3) -------------------------------------
def _ruleset_name(table: dict, ident: str | None) -> str | None:
    """Display name for a ruleset id (class/race/…), or None for a missing id."""
    if ident is None:
        return None
    ent = table.get(ident)
    return ent.name if ent is not None else ident


def _spell_view(rs: Ruleset, spell_id: str) -> dict:
    s = rs.spells.get(spell_id)
    if s is None:
        return {"id": spell_id, "name": spell_id, "level": None}
    return {"id": s.id, "name": s.name, "level": s.level, "school": s.school,
            "casting_time": s.casting_time, "range": s.range, "components": s.components,
            "duration": s.duration, "concentration": s.concentration, "ritual": s.ritual,
            "description": s.description}


def _sheet_member(char: Character, rs: Ruleset) -> dict:
    """One character's full sheet — every number code-derived (design §7). Works for a
    chargen PC (full D&D build) and degrades gracefully for a sheet-less quick-start
    hero (basic stats only)."""
    repo = GAME.session.repo
    equipped_items = []
    for i in char.equipped:
        try:
            equipped_items.append(repo.get_item(i))
        except StateError:
            pass
    d = derive.sheet_stats(char, rs, equipped_items)
    sheet = char.sheet
    saves = {a.value: {"mod": d["saves"][a.value],
                       "proficient": bool(sheet and a in sheet.saving_throw_proficiencies)}
             for a in Ability}
    from ..enums import SKILL_ABILITY, Skill
    skills = {s.value: {"mod": d["skills"][s.value], "ability": SKILL_ABILITY[s].value,
                        "proficient": s in char.skill_proficiencies,
                        "expertise": bool(sheet and s in sheet.expertise)}
              for s in Skill}
    out = {
        "id": char.id, "name": char.name, "has_sheet": sheet is not None,
        "portrait_url": f"/api/character-portrait/{char.id}",
        "has_portrait": char.portrait is not None,
        "level": char.level, "hp": char.hp, "max_hp": char.max_hp,
        "abilities": {a.value: {"score": char.abilities.get(a, 10), "mod": char.ability_mod(a)}
                      for a in Ability},
        "saves": saves, "skills": skills, "derived": d,
        "inventory": [{"name": _stack_label(rs, s), "qty": s.qty,
                       "equipped": s.item_id in char.equipped} for s in char.inventory],
        "gold": char.gold, "xp": char.xp, "xp_progress": xp_progress(char),
        "conditions": list(char.conditions),
        "hit_dice_used": char.hit_dice_used, "slots_used": dict(char.spell_slots_used),
        "resources_used": dict(char.resources_used),
    }
    if sheet is None:
        return out
    cc = rs.classes.get(sheet.char_class)
    out["identity"] = {
        "race": _ruleset_name(rs.races, sheet.race),
        "subrace": _ruleset_name(rs.subraces, sheet.subrace),
        "char_class": _ruleset_name(rs.classes, sheet.char_class),
        "subclass": _ruleset_name(rs.subclasses, sheet.subclass),
        "background": _ruleset_name(rs.backgrounds, sheet.background),
        "alignment": sheet.alignment, "size": sheet.size, "speed": sheet.speed,
    }
    out["hit_dice"] = {"die": (cc.hit_die if cc else None), "total": char.level,
                       "used": char.hit_dice_used}
    out["proficiencies"] = {
        "armor": list(sheet.armor_proficiencies), "weapons": list(sheet.weapon_proficiencies),
        "tools": list(sheet.tool_proficiencies), "languages": list(sheet.languages),
    }
    # features grouped by source, in a stable source order
    order = ["race", "subrace", "class", "subclass", "background", "feat"]
    groups: dict = {}
    for f in sheet.features:
        groups.setdefault(f.source or "other", []).append({"name": f.name, "text": f.text})
    out["features"] = [{"source": src, "items": groups[src]}
                       for src in order + [s for s in groups if s not in order] if src in groups]
    if sheet.spellcasting_ability is not None:
        preparation = cc.spellcasting.preparation if (cc and cc.spellcasting) else "known"
        pool = derive.prepare_pool(char, rs)     # None for non-prepared casters
        window_open = reprepare_window_open(GAME.session.store.read_all())
        out["spellcasting"] = {
            "ability": sheet.spellcasting_ability.value,
            "save_dc": d["spell_save_dc"], "attack_bonus": d["spell_attack_bonus"],
            "slots": d["spell_slots"], "slots_recharge": d["spell_slots_recharge"],
            "cantrips_known": d["cantrips_known"], "prepared_count": d["prepared_count"],
            "cantrips": [_spell_view(rs, s) for s in sheet.cantrips_known],
            "spells": [_spell_view(rs, s) for s in (sheet.spells_prepared or sheet.spells_known)],
            # Re-prepare on long rest (C5): the chooser only lights up for a
            # prepared caster while the post-long-rest window is open.
            "preparation": preparation,
            "can_reprepare": bool(pool) and window_open,
            "reprepare_window_open": window_open,
            "prepared_ids": list(sheet.spells_prepared),
            "prepare_pool": [_spell_view(rs, s) for s in (pool or [])],
        }
    out["resources"] = d["class_resources"]
    out["flavor"] = {"personality_traits": list(sheet.personality_traits),
                     "ideals": list(sheet.ideals), "bonds": list(sheet.bonds),
                     "flaws": list(sheet.flaws)}
    return out


@app.get("/api/sheet")
async def get_sheet() -> JSONResponse:
    """The party's read-only character sheets (PC-only today, built to hold a party)."""
    rs = _ruleset()
    return JSONResponse({"party": [_sheet_member(c, rs) for c in GAME.session.repo.party()]})


# --- PC portraits (A3): the player's token art, board-ready for the Arena ------
def _pc_portrait_path(char_id: str) -> Path | None:
    """Resolve a PC's portrait file from its recorded filename, under the campaign's
    character-portraits/ dir. None if unset or missing. Path-traversal guarded."""
    try:
        char = GAME.session.repo.get_character(char_id)
    except StateError:
        return None
    fname = char.portrait
    if not fname or "/" in fname or "\\" in fname:
        return None
    path = _PC_PORTRAITS / fname
    return path if path.is_file() else None


@app.get("/api/character-portrait/{char_id}")
async def character_portrait(char_id: str) -> FileResponse:
    """A PC's portrait (character sheet + Arena board token). Serves the uploaded image
    if present, else a neutral silhouette so every character has a token."""
    path = _pc_portrait_path(char_id)
    if path is not None:
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    return FileResponse(STATIC / "img" / "character-fallback.svg",
                        headers={"Cache-Control": "no-cache"})


@app.post("/api/character-portrait/{char_id}")
async def upload_character_portrait(char_id: str, request: Request) -> JSONResponse:
    """Attach a portrait to a PC (fork F2 = player upload). The image is POSTed as the
    raw request body (the browser sets Content-Type from the file); we validate it,
    store it beside the save keyed by character id, and record a PORTRAIT_SET event so
    the reference survives save/replay. Re-uploading replaces the previous image."""
    async with GAME.lock:
        repo = GAME.session.repo
        try:
            char = repo.get_character(char_id)
            if char.kind != "pc":
                raise StateError("portraits are for player characters")
            mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
            ext = _PORTRAIT_MIME_EXT.get(mime)
            if ext is None:
                raise StateError("unsupported image type; use PNG, JPG, WEBP, or GIF")
            data = await request.body()
            if not data:
                raise StateError("the uploaded file is empty")
            if len(data) > _PORTRAIT_MAX_BYTES:
                raise StateError(f"image too large ({len(data) // (1024 * 1024)} MB); max is 8 MB")
            _PC_PORTRAITS.mkdir(parents=True, exist_ok=True)
            for old in _PC_PORTRAITS.glob(f"{char_id}.*"):   # drop any prior-extension image
                old.unlink()
            fname = f"{char_id}{ext}"
            (_PC_PORTRAITS / fname).write_bytes(data)
            GAME.session.emit_state(
                EventKind.PORTRAIT_SET, [StateOp.portrait(char_id, fname)],
                reason=f"player set a portrait for {char.name}")
            ok, error = True, None
        except StateError as e:
            ok, error = False, str(e)
        return JSONResponse({"ok": ok, "error": error, "state": _snapshot()})


class RestIn(BaseModel):
    char_id: str = "pc"             # legacy: the lone member who spends hit_dice (short rest)
    kind: str                       # "short" | "long"
    hit_dice: int = 0               # legacy single-member hit-dice spend
    hit_dice_by: dict[str, int] | None = None  # short rest: hit dice each member spends, by char id


@app.post("/api/rest")
async def post_rest(body: RestIn) -> JSONResponse:
    """Take a short or long rest (CS5) — a PARTY event: every member recovers, recorded
    as one REST_TAKEN event carrying each member's recovery ops. Short-rest hit-die
    healing is individual, so only the member whose sheet was used (`char_id`) spends
    the entered dice; the rest of the party still takes the short rest (features
    recharge) with 0 dice. Hit-die rolls go through the seeded RNG."""
    async with GAME.lock:
        rs = _ruleset()
        if body.kind not in ("short", "long"):
            return JSONResponse({"ok": False, "error": "rest kind must be 'short' or 'long'"}, status_code=400)
        ops: list = []
        for char in GAME.session.repo.party():
            if body.kind == "long":
                ops += long_rest_ops(char, rs)
            else:
                if body.hit_dice_by is not None:        # per-member spend (party popup)
                    hd = max(0, body.hit_dice_by.get(char.id, 0))
                else:                                   # legacy: only the named member spends
                    hd = max(0, body.hit_dice) if char.id == body.char_id else 0
                ops += short_rest_ops(char, rs, spend_hit_dice=hd, rng=GAME.rng)
        GAME.session.emit_state(EventKind.REST_TAKEN, ops, rest=body.kind)
        return JSONResponse({"ok": True, "party": [_sheet_member(c, rs) for c in GAME.session.repo.party()],
                             "state": _snapshot()})


class PrepareSpellsIn(BaseModel):
    char_id: str
    spells: list[str]


@app.post("/api/prepare_spells")
async def post_prepare_spells(body: PrepareSpellsIn) -> JSONResponse:
    """Re-prepare a prepared caster's spell list (C5). Allowed only inside the
    post-long-rest window (before the party acts). The firewall validates the
    pick (exact count + drawn from the class pool / spellbook) before recording
    one SPELLS_PREPARED event; replay reproduces the list byte-identically."""
    async with GAME.lock:
        rs = _ruleset()
        if not reprepare_window_open(GAME.session.store.read_all()):
            return JSONResponse(
                {"ok": False, "error": "Spells can only be re-prepared after a long "
                 "rest, before the party acts."}, status_code=400)
        try:
            char = GAME.session.repo.get_character(body.char_id)
        except StateError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        err = derive.validate_prepared_choice(char, rs, body.spells)
        if err:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
        GAME.session.emit_state(
            EventKind.SPELLS_PREPARED,
            [StateOp.spells_prepared(body.char_id, body.spells)],
            char_id=body.char_id,
        )
        return JSONResponse({"ok": True, "party": [_sheet_member(c, rs) for c in GAME.session.repo.party()],
                             "state": _snapshot()})


@app.get("/api/levelup/plan")
async def get_levelup_plan(char_id: str = "pc") -> JSONResponse:
    """What advancing to the next level requires (drives the level-up UI)."""
    try:
        char = GAME.session.repo.get_character(char_id)
    except StateError as e:
        return JSONResponse({"can_level": False, "reason": str(e)})
    return JSONResponse(level_up_plan(char, _ruleset()))


class LevelUpIn(LevelUpChoice):
    char_id: str = "pc"


@app.post("/api/levelup")
async def post_levelup(body: LevelUpIn) -> JSONResponse:
    """Advance a character one level (CS5). Rolls HP via the seeded RNG when the player
    chose to roll, then records-then-applies a CHARACTER_LEVELED event."""
    async with GAME.lock:
        rs = _ruleset()
        try:
            char = GAME.session.repo.get_character(body.char_id)
        except StateError as e:
            return JSONResponse({"ok": False, "errors": [str(e)]}, status_code=400)
        choice = LevelUpChoice(**body.model_dump(exclude={"char_id"}))
        cc = rs.classes.get(char.sheet.char_class) if char.sheet else None
        if choice.hp_method == "roll" and choice.hp_roll is None and cc is not None:
            choice.hp_roll = GAME.rng.roll(f"1d{cc.hit_die}", "level_up_hp").total
        equipped = []
        for i in char.equipped:
            try:
                equipped.append(GAME.session.repo.get_item(i))
            except StateError:
                pass
        try:
            leveled = level_up(char, rs, choice, equipped_items=equipped, char_id=body.char_id)
        except LevelUpError as e:
            return JSONResponse({"ok": False, "errors": e.errors}, status_code=400)
        GAME.session.emit_character_leveled(leveled)
        return JSONResponse({"ok": True, "party": [_sheet_member(c, rs) for c in GAME.session.repo.party()],
                             "state": _snapshot()})


@app.post("/api/chargen/preview")
async def post_chargen_preview(body: CharacterBuild) -> JSONResponse:
    """Run the firewall live: validate the in-progress build and return either the
    aggregated errors or the fully-derived preview sheet. Never mutates state."""
    rs = _ruleset()
    try:
        char, items = build_character(body, rs)
    except ChargenError as e:
        return JSONResponse({"ok": False, "errors": e.errors})
    return JSONResponse({"ok": True, "errors": [], "preview": _preview_payload(char, items, rs)})


class NewGameIn(BaseModel):
    pack_id: str | None = None              # which world to start; None keeps the current one
    table: TableContract | None = None      # the table contract agreed at New Game (optional)
    build: CharacterBuild | None = None     # legacy single character (a party of one)
    builds: list[CharacterBuild] | None = None  # the chargen party (preferred); None/[] = quick-start


@app.post("/api/new")
async def post_new(body: NewGameIn | None = None) -> JSONResponse:
    async with GAME.lock:
        # The party: prefer the builds list; fall back to the single legacy build.
        builds = ((body.builds if body and body.builds else
                   ([body.build] if body and body.build else [])) or [])
        # Validate EVERY character BEFORE erasing the save — an invalid build must not
        # cost the player their game. The ruleset is global, so the current session's
        # serves regardless of which world we're about to start.
        rs = _ruleset()
        for b in builds:
            try:
                build_character(b, rs)
            except ChargenError as e:
                return JSONResponse({"ok": False, "errors": e.errors}, status_code=400)
        GAME.new_game(body.pack_id if body else None, body.table if body else None)
        if builds:
            GAME.session.emit_party_created(builds)   # replaces the default-party stopgap
        return JSONResponse({"ok": True, "state": _snapshot(), "model": GAME.client_name,
                             "pack_id": GAME.pack_id, "has_progress": _has_progress(),
                             "soundscape": _soundscape()})


@app.post("/api/reload")
async def post_reload() -> JSONResponse:
    """Re-read the pack from disk into the running game (keeps the save), so edits made
    in The Forge appear without a New Game — the author→test convenience."""
    async with GAME.lock:
        GAME.reload_world()
        return JSONResponse({"state": _snapshot(), "model": GAME.client_name,
                             "pack_id": GAME.pack_id, "soundscape": _soundscape()})


# --- provider / API-key front door ------------------------------------------

class ProviderSetBody(BaseModel):
    provider: str
    api_key: str | None = None


def _pretty_model(mid: str) -> str:
    """`claude-sonnet-5` -> `Claude Sonnet 5` for the connection badge."""
    words, nums = [], []
    for tok in mid.split("-"):
        (nums if tok.isdigit() else words).append(tok)
    return f"{' '.join(w.capitalize() for w in words)} {'.'.join(nums)}".strip()


def _provider_status() -> dict:
    """Live connection state for the front door: is a real DM wired up, and a
    friendly model label when it is. (`scripted` == offline stub.)"""
    online = GAME.client_name != "scripted"
    from ..llm.anthropic_client import DEFAULT_MODEL
    model = _pretty_model(DEFAULT_MODEL) if GAME.client_name == "anthropic" else ""
    return {"online": online, "client": GAME.client_name,
            "selected": providers.selected_provider(), "model": model}


@app.get("/api/providers")
async def get_providers() -> JSONResponse:
    """The provider roster (which services exist + which are wired) plus the current
    connection state. Never returns key material — only whether one is on file."""
    return JSONResponse({"providers": providers.registry_view(), **_provider_status()})


@app.post("/api/providers")
async def post_providers(body: ProviderSetBody) -> JSONResponse:
    """Save the chosen provider + key and re-pick the live DM immediately (no
    restart). An unimplemented provider is refused; a key that fails to construct a
    client leaves the game offline and says so."""
    prov = providers.get_provider(body.provider)
    if prov is None or not prov.implemented:
        return JSONResponse(
            {"ok": False, "error": f"{body.provider!r} isn't available yet",
             "providers": providers.registry_view(), **_provider_status()},
            status_code=400)
    async with GAME.lock:
        providers.set_provider_key(body.provider, body.api_key)
        GAME.refresh_client()
    status = _provider_status()
    if body.api_key and not status["online"]:
        return JSONResponse(
            {"ok": False, "error": "that key didn't connect — still in offline mode",
             "providers": providers.registry_view(), **status}, status_code=400)
    return JSONResponse({"ok": True, "providers": providers.registry_view(), **status})


def main() -> None:
    _load_dotenv()
    GAME.refresh_client()  # now that .env is loaded, prefer the live DM if keyed
    import threading
    import webbrowser

    import uvicorn

    host, port = "127.0.0.1", 8000
    url = f"http://{host}:{port}"
    print(f"\n  Oubliette Table — open your browser to {url}\n  (Ctrl+C to stop)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
