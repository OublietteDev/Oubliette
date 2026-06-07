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

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..content.loader import DEFAULT_PACK, available_packs
from ..journal.store import Journal, JournalStore
from ..record.events import EventKind, StateOp
from ..record.store import SqliteEventStore
from ..record.rng import Rng
from ..runtime.loop import TurnLoop
from ..runtime.session import Session
from ..dm.brain import Brain
from ..state.repository import StateError
from ..tools.dispatch import ToolApplyError
from ..trade.service import build_state, buy_transact, checkout_transact, sell_transact
from .repl import _load_dotenv, _pick_client

STATIC = Path(__file__).parent / "static"
DB_PATH = os.environ.get("OUBLIETTE_DB", "oubliette-save.sqlite")

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
        rng = Rng(seed=1234, record=self.session.emit_log)
        self.loop = TurnLoop(self.session, rng, Brain(client))

    def refresh_client(self) -> None:
        """Re-pick the model client — call AFTER .env is loaded so a key present
        only in .env still selects the live DM (the game is built at import)."""
        client, self.client_name = _pick_client(force_scripted=False)
        self.loop.brain = Brain(client)

    def new_game(self, pack_id: str | None = None) -> None:
        """Erase the save and start fresh — in `pack_id` if given, else the same
        world as before."""
        self.store.close()
        self.journal.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        if pack_id:
            self.pack_id = pack_id
        self._open()


GAME = _Game()


# --- serialization ----------------------------------------------------------
def _snapshot() -> dict:
    repo = GAME.session.repo
    pc = repo.pc()
    location = GAME.session.location
    # Who's here: NPCs homed at the party's current location (everyone when there's
    # no location, e.g. a custom seed) — mirrors what the DM is told.
    npcs = repo.npcs()
    if location is not None:
        npcs = [n for n in npcs if n.home_location == location]
    return {
        "scene": GAME.session.scene,
        "ended": GAME.session.ended,
        "pc": {
            "name": pc.name, "hp": pc.hp, "max_hp": pc.max_hp,
            "gold": pc.gold, "xp": pc.xp, "armor_class": pc.armor_class,
            "conditions": list(pc.conditions),
            "inventory": [
                {"id": s.item_id, "name": repo.get_item(s.item_id).name, "qty": s.qty}
                for s in pc.inventory
            ],
        },
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
    }


def _build_inventory() -> dict:
    """Per party-member inventory with item details for the inventory panel."""
    repo = GAME.session.repo
    party = []
    for c in repo.party():
        items = []
        for s in c.inventory:
            it = repo.get_item(s.item_id)
            items.append({
                "item_id": s.item_id, "name": it.name, "category": it.category,
                "qty": s.qty, "value": it.base_value, "armor_class": it.armor_class,
                "equippable": it.equippable, "equipped": s.item_id in c.equipped,
                "tags": it.tags,
            })
        party.append({"id": c.id, "name": c.name, "items": items})
    return {"party": party}


def _describe_applied(rt) -> str:
    if rt.canon_create is not None:
        return f"introduced {rt.canon_create.entity_type} “{rt.canon_create.name}” (provisional)"
    if rt.canon_promote is not None:
        return f"confirmed canon {rt.canon_promote}"
    return f"{rt.tool}: {TurnLoop._ops_summary(rt.ops)}"


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
        "applied": [_describe_applied(rt) for rt in report.applied],
        "combat": combat,
        "trade": report.trade_open.model_dump() if report.trade_open is not None else None,
        "meta_notice": report.meta_notice,
        "session_ended": report.session_ended,
        "verb": report.assessment.intent.verb.value,
        "tier": report.assessment.tier.value,
        "state": _snapshot(),
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
    return JSONResponse({"state": _snapshot(), "model": GAME.client_name})


@app.post("/api/turn")
async def post_turn(body: TurnIn) -> JSONResponse:
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if GAME.session.ended:
        return JSONResponse({"error": "the DM has ended this session", "ended": True}, status_code=409)
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


class NewGameIn(BaseModel):
    pack_id: str | None = None     # which world to start; None keeps the current one


@app.post("/api/new")
async def post_new(body: NewGameIn | None = None) -> JSONResponse:
    async with GAME.lock:
        GAME.new_game(body.pack_id if body else None)
        return JSONResponse({"state": _snapshot(), "model": GAME.client_name, "pack_id": GAME.pack_id})


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
