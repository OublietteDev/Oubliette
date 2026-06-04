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
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..record.events import EventKind
from ..record.store import SqliteEventStore
from ..record.rng import Rng
from ..runtime.loop import TurnLoop
from ..runtime.session import Session
from ..dm.brain import Brain
from ..state.repository import StateError
from ..tools.dispatch import ToolApplyError
from ..trade.service import build_state, buy_transact, sell_transact
from .repl import _load_dotenv, _pick_client

STATIC = Path(__file__).parent / "static"
DB_PATH = os.environ.get("OUBLIETTE_DB", "oubliette-save.sqlite")

app = FastAPI(title="Oubliette Table")


class _Game:
    """Holds the live session/loop. One game per server process (single-player)."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.client_name = "scripted"
        self._open()

    def _open(self) -> None:
        self.store = SqliteEventStore(DB_PATH)
        self.session = Session.open(self.store)
        client, self.client_name = _pick_client(force_scripted=False)
        rng = Rng(seed=1234, record=self.session.emit_log)
        self.loop = TurnLoop(self.session, rng, Brain(client))

    def refresh_client(self) -> None:
        """Re-pick the model client — call AFTER .env is loaded so a key present
        only in .env still selects the live DM (the game is built at import)."""
        client, self.client_name = _pick_client(force_scripted=False)
        self.loop.brain = Brain(client)

    def reset(self) -> None:
        self.store.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        self._open()


GAME = _Game()


# --- serialization ----------------------------------------------------------
def _snapshot() -> dict:
    repo = GAME.session.repo
    pc = repo.pc()
    return {
        "scene": GAME.loop.scene,
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
            for n in repo.npcs()
        ],
        "canon": [
            {"id": r.id, "type": r.entity_type, "name": r.name,
             "text": r.text, "status": r.status}
            for r in GAME.session.canon.all()
        ],
    }


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
        "verb": report.assessment.intent.verb.value,
        "tier": report.assessment.tier.value,
        "state": _snapshot(),
    }


# --- API --------------------------------------------------------------------
class TurnIn(BaseModel):
    text: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
async def get_state() -> JSONResponse:
    return JSONResponse({"state": _snapshot(), "model": GAME.client_name})


@app.post("/api/turn")
async def post_turn(body: TurnIn) -> JSONResponse:
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    async with GAME.lock:  # serialize turns; combat/state mutation isn't reentrant
        report = await GAME.loop.take_turn(text)
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


@app.post("/api/new")
async def post_new() -> JSONResponse:
    async with GAME.lock:
        GAME.reset()
        return JSONResponse({"state": _snapshot(), "model": GAME.client_name})


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
