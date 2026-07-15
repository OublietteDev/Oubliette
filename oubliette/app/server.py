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
import io
import json
import os
import traceback
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from ..coin import authored_to_cp, format_cp
from ..combat.arena_bridge import character_to_player
from ..content import packaging
from ..content.loader import (DEFAULT_PACK, _PACKS_ROOT, PackValidationError,
                              available_packs, load_pack)
from ..content.ruleset import Ruleset, load_ruleset
from ..journal.store import Journal, JournalStore
from ..quest import offers as quest_offers
from ..record.events import EventKind, StateOp
from ..record.store import SqliteEventStore
from ..record.rng import Rng
from ..rules import derive
from ..rules.chargen_view import chargen_options, preview_payload
from ..rules.chargen import CharacterBuild, ChargenError, build_character
from ..rules.attune import (MAX_ATTUNED, active_attuned, attunable_carried,
                            requires_attunement, validate_attunement)
from ..rules.rest import long_rest_ops, short_rest_ops, reprepare_window_open
from ..rules.rest_gate import RestGateError, long_rest_cost, roll_interruption
from ..rules.levelup import (LevelUpChoice, LevelUpError, level_up, level_up_plan,
                            xp_progress)
from ..runtime.loop import TurnLoop
from ..runtime.session import Session
from ..runtime.transcript import session_notes, transcript_turns
from ..dm.brain import Brain
from ..dm.context import region_root
from ..enums import Ability, Skill
from ..state.models import Character
from ..state.repository import StateError
from ..difficulty import PRESET_BLURBS, PRESET_DIALS, DifficultySettings
from ..table import TONE_PRESETS, TableContract
from ..tools.dispatch import ToolApplyError
from ..trade.service import (build_state, buy_transact, checkout_ops,
                             hand_over_transact, sell_transact)
from ..tts import engine as tts_engine
from ..tts.chunker import SentenceChunker, clean_for_speech
from ..llm import providers
from ..llm.anthropic_client import estimate_cost_usd
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
                 table: TableContract | None = None,
                 difficulty: DifficultySettings | None = None) -> None:
        """Erase the save and start fresh — in `pack_id` if given, else the same
        world as before. `table` sets the campaign's contract (tone + boundaries)
        and `difficulty` its danger dials, both agreed at New Game time; each is
        recorded so it persists and reaches the engine."""
        self.store.close()
        self.journal.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        if pack_id:
            self.pack_id = pack_id
        self._open()
        if table is not None:
            self.session.emit_contract(table, reason="new game")
        if difficulty is not None:
            self.session.emit_difficulty(difficulty, reason="new game")

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
    """The HUD view of one party member (the sidebar + party roster) — a hero or,
    since companions S1, a standing companion (flagged so the UI can badge them)."""
    return {
        "id": pc.id, "name": pc.name, "hp": pc.hp, "max_hp": pc.max_hp,
        "xp": pc.xp, "xp_progress": xp_progress(pc),
        "armor_class": pc.armor_class,
        "companion": bool(getattr(pc, "companion", False)),
        "conditions": list(pc.conditions),
        "inventory": [
            {"id": s.item_id, "name": _stack_label(_ruleset(), s), "qty": s.qty,
             "spell": s.spell, "spell_level": s.spell_level}
            for s in pc.inventory
        ],
    }


def _location_trail() -> list[str]:
    """Place names from the outermost enclosing area down to the party's current spot
    (e.g. ["Brightvale", "Market Square"]) — the "where am I" breadcrumb for the HUD.
    Empty when the party has no authored location (a custom seed)."""
    places = GAME.session.places
    cur, seen, chain = GAME.session.location, set(), []
    while cur in places and cur not in seen:
        seen.add(cur)
        chain.append(places[cur].name)
        cur = places[cur].parent
        if not cur:
            break
    chain.reverse()
    return chain


def _current_day() -> int:
    """The campaign's day number (living-world W3), a pure derivation."""
    from ..world.clock import current_day
    return current_day(GAME.session.store.read_all())


def _house_rule_labels() -> list[str]:
    """The world's active house rules as short player-readable labels — only
    the rules that DIFFER from the book, so an untouched world shows none."""
    hr = getattr(GAME.session, "house_rules", None)
    if hr is None:
        return []
    labels = []
    if hr.initiative == "side":
        labels.append("Side initiative — all heroes act, then all foes")
    elif hr.initiative == "reroll":
        labels.append("Initiative is re-rolled at the top of every round")
    if hr.flanking:
        labels.append("Flanking — melee advantage when allies sandwich a foe")
    if hr.crit_range_19:
        labels.append("Everyone crits on 19–20")
    if hr.brutal_crits:
        labels.append("Brutal crits — critical dice come in maximized")
    if hr.potions_bonus_action:
        labels.append("Drinking a potion is a bonus action")
    return labels


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
        "pack_name": GAME.session.pack_name or "",   # the world you're playing (header)
        "location_trail": _location_trail(),         # parent > sublocation breadcrumb
        "force_ended": GAME.session.force_ended,
        "campaign_ended": GAME.session.campaign_ended,   # hardcore TPK (S4): the tale is told
        "combat_pending": GAME.session.pending_combat is not None,
        "time_of_day": GAME.session.time_of_day,
        "weather": GAME.session.weather,
        # The world clock (living-world W3): 1-based campaign day, derived from
        # the log (nights slept + journey time) — correct even for old saves.
        "day": _current_day(),
        # Rest gating (S3): the UI's Long Rest button routes through the story
        # on a gated table; "free" keeps the direct one-click rest.
        "rest_strictness": GAME.session.difficulty.rest_strictness,
        # Living-world W2: whether this world authors factions at all — drives
        # the menu item; the Factions page itself is served (redacted) separately.
        "has_factions": bool(getattr(GAME.session, "factions", None)),
        # The world's house rules (author-set, read-only for players): human
        # labels for the Settings page; empty list = plays by the book.
        "house_rules": _house_rule_labels(),
        "pc": _pc_view(pc),                          # the lead PC (back-compat)
        "party": [_pc_view(c) for c in repo.party()],  # the whole roster (HUD)
        # The party's shared money (copper + a preformatted display string).
        "purse_cp": repo.party_cp,
        "purse_text": format_cp(repo.party_cp),
        "npcs": [
            {"id": n.id, "name": n.name, "disposition": n.disposition,
             "coin_text": format_cp(n.coin)}
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


def _prune_attunement(char_ids: list[str]) -> None:
    """End any attunement bond to an item its bearer no longer carries (it was
    handed over or sold). Recorded as ATTUNEMENT_CHANGED so the break replays;
    a no-op for members whose bonds all still hold. Call under GAME.lock, after
    the inventory-moving event has been applied."""
    for cid in char_ids:
        try:
            char = GAME.session.repo.get_character(cid)
        except StateError:
            continue
        live = active_attuned(char)
        if live != char.attuned:
            GAME.session.emit_state(
                EventKind.ATTUNEMENT_CHANGED, [StateOp.attune(cid, live)],
                reason=f"{char.name}'s attunement ended — item no longer held")


def _build_inventory() -> dict:
    """Per party-member inventory with item details for the inventory panel. Also
    ships `details`: a compact {item_id: hover-card} map covering ONLY the ids the
    party actually carries (never the whole catalog), so the panel can show what an
    item actually does."""
    repo = GAME.session.repo
    catalog = getattr(GAME.session, "mechanics_catalog", None)
    party = []
    carried: set[str] = set()
    for c in repo.party():
        items = []
        rs = _ruleset()
        for s in c.inventory:
            it = repo.get_item(s.item_id)
            carried.add(s.item_id)
            items.append({
                "item_id": s.item_id, "name": _stack_label(rs, s), "category": it.category,
                "qty": s.qty,
                "value_text": format_cp(it.value_cp) if it.value_cp else None,
                "armor_class": it.armor_class,
                "equippable": it.equippable, "equipped": s.item_id in c.equipped,
                "requires_attunement": requires_attunement(catalog, s.item_id),
                "attuned": s.item_id in c.attuned,
                "tags": it.tags, "spell": s.spell, "spell_name": _spell_name(rs, s.spell),
                "spell_level": s.spell_level,
            })
        party.append({"id": c.id, "name": c.name, "items": items})
    details = {}
    for iid in sorted(carried):
        d = _item_details(iid)
        if d:
            details[iid] = d
    return {"party": party, "details": details}


def _item_details(item_id: str) -> dict | None:
    """The hover-card facts for one carried item — only fields that exist, so the
    front-end renders exactly what's true of the item and nothing else. Prefers the
    session's merged mechanics catalog (SRD + pack, pack wins); falls back to the
    campaign's repo item (which carries only the basic sheet numbers)."""
    catalog = getattr(GAME.session, "mechanics_catalog", None) or {}
    eq = catalog.get(item_id)
    if eq is None:
        return _item_details_fallback(item_id)
    d: dict = {}
    if eq.description:
        d["description"] = eq.description
    if eq.base_value is not None:
        # Mechanics-catalog values still author gp (ints) or coin strings.
        v = authored_to_cp(eq.base_value)
        d["value_text"] = format_cp(v) if v else None
    if eq.weapon is not None:
        w: dict = {"damage": eq.weapon.damage}
        if eq.weapon.properties:
            w["properties"] = list(eq.weapon.properties)
        if eq.weapon.attack_bonus:
            w["attack_bonus"] = eq.weapon.attack_bonus
        d["weapon"] = w
    if eq.armor is not None:
        a: dict = {"base_ac": eq.armor.base_ac, "type": eq.armor.type}
        if eq.armor.dex_cap is not None:
            a["dex_cap"] = eq.armor.dex_cap
        d["armor"] = a
    # magic-item family line: "rare · weapon · requires attunement"
    if eq.item_type != "mundane":
        d["item_type"] = eq.item_type
    if eq.rarity:
        d["rarity"] = eq.rarity
    if eq.magic_bonus:
        d["magic_bonus"] = eq.magic_bonus
    if eq.requires_attunement:
        d["requires_attunement"] = True
    c = eq.consumable
    if c is not None:
        cd = {k: v for k, v in (("healing", c.healing),
                                ("ability_set", c.ability_set),
                                ("grants_resistance", c.grants_resistance),
                                ("casts_spell_level", c.casts_spell_level),
                                ("duration", c.duration)) if v is not None}
        if c.action and c.action != "action":
            cd["action"] = c.action
        if cd:
            d["consumable"] = cd
    p = eq.poison
    if p is not None:
        pd: dict = {"type": p.poison_type, "save_dc": p.save_dc,
                    "save_ability": p.save_ability}
        if p.damage:
            pd["damage"] = p.damage
            pd["damage_type"] = p.damage_type
        if p.conditions:
            pd["conditions"] = list(p.conditions)
        if p.duration:
            pd["duration"] = p.duration
        d["poison"] = pd
    # worn boons — fields landing in a parallel work-stream; read them if present
    # so this works on either side of that merge.
    res = getattr(eq, "grants_resistances", None)
    imm = getattr(eq, "grants_immunities", None)
    if res:
        d["grants_resistances"] = list(res)
    if imm:
        d["grants_immunities"] = list(imm)
    return d or None


def _item_details_fallback(item_id: str) -> dict | None:
    """Details from the campaign's repo catalog for an item outside the mechanics
    catalog (e.g. a DM-invented item registered mid-session)."""
    try:
        it = GAME.session.repo.get_item(item_id)
    except StateError:
        return None
    d: dict = {}
    if it.value_cp is not None:
        d["value_text"] = format_cp(it.value_cp)
    if it.damage:
        d["weapon"] = {"damage": it.damage}
    if it.armor_class is not None:
        a: dict = {"base_ac": it.armor_class}
        if it.armor_type:
            a["type"] = it.armor_type
        if it.dex_cap is not None:
            a["dex_cap"] = it.dex_cap
        d["armor"] = a
    return d or None


def _ops_chip(ops) -> str:
    """TurnLoop._ops_summary with item ids resolved to display names — this string
    lands in a player-facing chip (the DM's own history beats keep the raw ids)."""
    bits = []
    for o in ops:
        if o.op == "coin":
            d = o.delta or 0
            bits.append(f"{o.char} {'+' if d >= 0 else '-'}{format_cp(abs(d))}")
        elif o.op == "gold":     # legacy op (pre-coin saves)
            bits.append(f"{o.char} {o.delta:+d} gp")
        elif o.op == "item":
            bits.append(f"{o.char} {o.delta:+d} {_item_name(_ruleset(), o.item_id)}")
        elif o.op == "hp_set":
            bits.append(f"{o.char} hp={o.value}")
        elif o.op == "xp":
            bits.append(f"{o.char} +{o.delta}xp")
        elif o.op == "conditions":
            bits.append(f"{o.char} conditions={o.conditions}")
    return ", ".join(bits) or "(none)"


def _describe_applied(rt) -> str | None:
    """A short player-facing chip for a state-changing tool, or None for tools that get no
    chip: `dm_note` is PRIVATE (a chip would leak that the DM jotted a secret), and
    set_environment / wrap / force-end surface through the narration, wrap-bar, and force-end
    paths respectively. Travel has no StateOps, so it needs its own label (else '(none)')."""
    if rt.canon_create is not None:
        return f"introduced {rt.canon_create.entity_type} “{rt.canon_create.name}” (provisional)"
    if rt.canon_promote is not None:
        return f"confirmed canon {rt.canon_promote}"
    if rt.travel_to is not None:
        node = GAME.session.places.get(rt.travel_to)
        return f"travelled to {node.name if node is not None else rt.travel_to}"
    if rt.note_text is not None or rt.wrap_proposed or rt.rest_proposed is not None \
            or rt.force_end_session or rt.env_time is not None or rt.env_weather is not None:
        return None
    if rt.ops:
        return f"{rt.tool}: {_ops_chip(rt.ops)}"
    return None


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
            # A pure reward-settled flip (no status change, no note) is DM bookkeeping —
            # the reward handover itself surfaces via its give/transact chip, so don't
            # emit an empty "updated" card for it.
            if rt.quest_update.status is None and not rt.quest_update.note:
                continue
            q = GAME.session.quests.get(rt.quest_update.quest_id)
            title = q.title if q is not None else rt.quest_update.quest_id
            status = rt.quest_update.status
            kind = status if status in ("completed", "failed") else "updated"
            beats.append({"kind": kind, "title": title,
                          "detail": rt.quest_update.note or "", "image": image})
    return beats


def _trinket_url(image: str) -> str:
    return f"/api/pack-image/{quote(image)}"


def _trinket_beats(report) -> list[dict]:
    """Trinkets whose granting moment is THIS turn — a player-facing keepsake card
    for the chat stream. The DM has no tool for this and never knows it happened:
    the moment is derived from the quest tools it already uses (accept_quest /
    update_quest-to-completed), so authored trinkets cost it nothing."""
    beats: list[dict] = []
    for rt in report.applied:
        aq, granted_when, outcome = None, None, ""
        if rt.quest_accept is not None:
            aq = GAME.session.authored_quests.get(rt.quest_accept.quest_id)
            granted_when = "accepted"
        elif rt.quest_update is not None and rt.quest_update.status == "completed":
            q = GAME.session.quests.get(rt.quest_update.quest_id)
            if q is not None and q.authored_id:
                aq = GAME.session.authored_quests.get(q.authored_id)
                granted_when = "completed"
                outcome = rt.quest_update.outcome or ""
        if aq is None:
            continue
        for t in aq.trinkets:
            if t.when != granted_when:
                continue
            if t.when == "completed" and t.outcome and t.outcome != outcome:
                continue
            beats.append({"key": f"{aq.id}:{t.id}", "quest": aq.title,
                          "image": _trinket_url(t.image), "caption": t.caption})
    return beats


def _turn_payload(report) -> dict:
    roll = None
    if report.roll_outcome is not None and report.assessment.roll is not None:
        roll = {
            "spec": report.roll_outcome.spec, "total": report.roll_outcome.total,
            "dc": report.assessment.roll.dc, "result": report.roll_result,
            "purpose": report.roll_outcome.purpose,
        }
        if GAME.session.difficulty.hidden_rolls:
            # Redacted server-side, so the outcome truly isn't in the payload:
            # the player sees the dice land and learns how it went from the story.
            roll["dc"] = None
            roll["result"] = None
    combat = None
    if report.combat_result is not None:
        combat = {"outcome": report.combat_result.outcome,
                  "xp": report.combat_result.xp_award}
    return {
        "narration": report.narration,
        "roll": roll,
        # quest tools surface as their own cards (quest_beats); dm_note/env/wrap/force-end
        # get no chip — _describe_applied returns None for all of those, so drop the Nones.
        "applied": [d for rt in report.applied if (d := _describe_applied(rt)) is not None],
        "quest_beats": _quest_beats(report),
        "trinkets": _trinket_beats(report),
        "growth": list(getattr(report, "growth", []) or []),   # companions that grew this turn
        "companion_deaths": list(getattr(report, "companion_deaths", []) or []),  # the fallen (S3)
        "combat": combat,
        "trade": report.trade_open.model_dump() if report.trade_open is not None else None,
        "meta_notice": report.meta_notice,
        "combat_pending": getattr(report, "combat_pending", False),
        "wrap_pending": getattr(report, "wrap_pending", False),
        "rest_pending": getattr(report, "rest_pending", None),   # "short"|"long"|None (DM proposal)
        "companion_pending": getattr(report, "companion_pending", None),  # recruit/dismiss proposal
        "session_force_ended": report.session_force_ended,
        "verb": report.assessment.intent.verb.value,
        "tier": report.assessment.tier.value,
        "state": _snapshot(),
        "soundscape": _soundscape(),   # the party may have travelled — refresh the mix
    }


# --- API --------------------------------------------------------------------
class TurnIn(BaseModel):
    text: str
    ooc: bool = False          # player's explicit out-of-character signal (composer toggle)
    narrate: bool = False      # this player wants the turn read aloud (narration toggle)


@app.get("/")
async def index() -> FileResponse:
    # no-cache: always revalidate so a refresh never serves a stale page (e.g. an
    # old copy missing the menu).
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache, max-age=0"})


@app.get("/tokens.css")
async def tokens_css() -> FileResponse:
    """The shared house-style token block (oubliette/ui/tokens.css) — the SAME file
    the Forge serves, so the two UIs draw from one palette and cannot drift."""
    return FileResponse(Path(__file__).resolve().parents[1] / "ui" / "tokens.css",
                        media_type="text/css",
                        headers={"Cache-Control": "no-cache, max-age=0"})


@app.get("/api/state")
async def get_state() -> JSONResponse:
    return JSONResponse({"state": _snapshot(), "model": GAME.client_name,
                         "has_progress": _has_progress(), "soundscape": _soundscape()})


@app.get("/api/transcript")
async def get_transcript() -> JSONResponse:
    """The session-in-progress transcript — player messages + DM narration, in order — so a
    reload replays the chat instead of starting blank (W3). Plus the `chronicle`: the
    spoiler-free player-facing recap of each PAST wrapped session (W5), so the player sees
    'Session 1: … Session 2: …' above the live chat. The DM's private notes never come here."""
    events = GAME.session.store.read_all()
    chronicle = [{"index": n["index"], "player_facing": n["player_facing"]}
                 for n in session_notes(events) if n["player_facing"]]
    return JSONResponse({"turns": transcript_turns(events), "chronicle": chronicle})


@app.post("/api/wrap")
async def post_wrap() -> JSONResponse:
    """Wrap up the session in progress (the player's Wrap button, or their confirmation of
    the DM's `end_session` proposal). The DM authors two-faced notes from the full transcript
    — UNLESS Offline Mode (scripted), which writes none — the session seals, and play resumes
    fresh. Returns the player-facing recap to show, and the refreshed state."""
    if GAME.session.force_ended:
        return JSONResponse({"error": "the DM has ended this session", "force_ended": True}, status_code=409)
    if GAME.session.pending_combat is not None:
        return JSONResponse({"error": "finish the fight before wrapping", "combat_pending": True},
                            status_code=409)
    async with GAME.lock:
        write_notes = GAME.client_name != "scripted"   # Offline Mode writes no notes
        report = await GAME.loop.wrap_session(write_notes=write_notes)
    return JSONResponse({
        "wrapped": report.wrapped,
        "player_facing": report.player_facing,
        "wrote_notes": bool(report.player_facing or report.dm_private),
        "notice": report.notice,
        "state": _snapshot(),
    })


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


@app.get("/api/usage")
async def get_usage() -> JSONResponse:
    """Session token/cost meter. Anthropic only: its API reports exact token counts
    in every response's `usage` tail; dollars are OUR estimate from the published
    prices (see llm.anthropic_client). Counts live on the client object, so they
    cover this app run and reset with it (relaunch, provider change, New Game)."""
    client = GAME.loop.brain.client
    usage = getattr(client, "usage", None)
    if GAME.client_name != "anthropic" or not isinstance(usage, dict):
        return JSONResponse({"available": False, "provider": GAME.client_name})
    model = getattr(client, "model", "")
    # The player's own prices (front door's optional fields) beat the built-in
    # table — the honest meter for a model we don't know, or a rate that changed.
    custom = providers.stored_pricing("anthropic")
    return JSONResponse({"available": True, "model": model, "usage": dict(usage),
                         "cost": estimate_cost_usd(model, usage, custom=custom),
                         "custom_pricing": bool(custom)})


@app.get("/api/debug/log")
async def get_debug_log(tail: int = 200) -> JSONResponse:
    """A dev window into the loop's in-memory debug log — assessments, rolls,
    combat staging with its CR-vs-budget arithmetic (`combat_budget` entries),
    bounces, and anomalies. In-memory only: a server restart clears it."""
    import json as _json
    entries = GAME.loop.debug.entries[-max(1, min(tail, 1000)):]
    safe = _json.loads(_json.dumps(
        [{"seq": e.seq, "kind": e.kind, **e.data} for e in entries], default=str))
    return JSONResponse({"entries": safe})


@app.get("/api/debug/context")
async def get_debug_context() -> JSONResponse:
    """A dev window into the EXACT context string the DM is handed this turn —
    the party card, encounter budget, rest rules, and the quests it can see.
    Use it to confirm a level-gated quest is genuinely invisible until the party
    qualifies (it won't appear anywhere in this text). Read-only."""
    return JSONResponse({"context": GAME.loop._build_context("")})


@app.get("/api/difficulty")
async def get_difficulty() -> JSONResponse:
    """This campaign's difficulty settings + the presets (blurbs and the dial
    bundle each stands for) for the New Game and Settings pickers."""
    presets = {name: {"blurb": PRESET_BLURBS.get(name, ""), "dials": dials}
               for name, dials in PRESET_DIALS.items()}
    presets["custom"] = {"blurb": PRESET_BLURBS["custom"], "dials": None}
    return JSONResponse({"difficulty": GAME.session.difficulty.model_dump(),
                         "presets": presets})


@app.put("/api/difficulty")
async def put_difficulty(body: DifficultySettings) -> JSONResponse:
    """Update the campaign's difficulty from Settings — recorded so it persists.
    Changeable mid-campaign by design (including out of hardcore)."""
    async with GAME.lock:
        stored = GAME.session.emit_difficulty(body, reason="settings edit")
        return JSONResponse({"ok": True, "difficulty": stored.model_dump()})


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
@app.get("/api/pack-image/{filename}", response_model=None)
async def map_image(filename: str) -> FileResponse | JSONResponse:
    """Serve any image from the loaded pack's images/ folder by filename — map
    backgrounds and sub-maps under the historical /api/map-image name, trinket art
    (and anything future) under the general /api/pack-image alias."""
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


# --- voiced narration (design: oubliette-voiced-narration) ------------------
# Synthesized sentence clips live in memory only — a turn's audio is spoken once
# and forgotten, never written to disk. The store is a small ring: old clips
# fall off the back long after the browser has fetched them.
_TTS_CLIPS: dict[str, bytes] = {}
_TTS_CLIPS_MAX = 128
_TTS_POOL = None           # lazy single worker: sentences synthesize in order
_TTS_TURN_JOBS: list = []  # the LAST narrated turn's clip futures — cancelled when
                           # a new narrated turn starts, so a slow tier's unfinished
                           # tail never queues ahead of the next turn's clips


def _tts_pool():
    global _TTS_POOL
    if _TTS_POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _TTS_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
    return _TTS_POOL


def _store_clip(wav: bytes) -> str:
    import uuid
    cid = uuid.uuid4().hex
    _TTS_CLIPS[cid] = wav
    while len(_TTS_CLIPS) > _TTS_CLIPS_MAX:
        _TTS_CLIPS.pop(next(iter(_TTS_CLIPS)))
    return cid


@app.get("/api/tts/status")
async def tts_status() -> JSONResponse:
    """Can narration run, with which voices — and if not, an honest why.
    The first ask LOADS the model (seconds on Kokoro, tens on the Qwen tier),
    so it runs on a worker thread — the page boots this endpoint, and the app
    must never sit frozen behind a model load."""
    status = await asyncio.get_running_loop().run_in_executor(None, tts_engine.status)
    return JSONResponse(status)


class TtsIn(BaseModel):
    voice: str


@app.put("/api/tts")
async def put_tts(body: TtsIn) -> JSONResponse:
    """Save the narrator voice (per model — the host's storyteller)."""
    engine, reason = await asyncio.get_running_loop().run_in_executor(
        None, tts_engine.get_engine)
    if engine is None:
        return JSONResponse({"error": reason}, status_code=409)
    if body.voice not in engine.voices():
        return JSONResponse({"error": f"unknown voice '{body.voice}'"}, status_code=400)
    tts_engine.set_tts_voice(engine.id, body.voice)
    return JSONResponse(tts_engine.status())


@app.get("/api/tts/clip/{clip_id}", response_model=None)
async def tts_clip(clip_id: str) -> Response | JSONResponse:
    wav = _TTS_CLIPS.get(clip_id)
    if wav is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(content=wav, media_type="audio/wav")


# The self-benchmark sentence — same one the shipped voice samples read, so what
# the player hears at setup, in Settings, and in the measurement all line up.
_TTS_BENCH_TEXT = ("Beneath the old bay, past the drowned pilings, something has "
                   "been tearing the nets — and whatever it is, it leaves no wake.")


class TtsBenchIn(BaseModel):
    voice: str | None = None    # try a specific voice; default = the saved one


@app.post("/api/tts/benchmark")
async def tts_benchmark(body: TtsBenchIn) -> JSONResponse:
    """Measure narration speed on THIS machine (the measure-don't-promise lock)
    and hand back the synthesized clip so the test doubles as a voice preview.
    Speed is reported as real-time factor: synthesis seconds per second of audio
    — under 1.0 means the voice outruns its own reading."""
    engine, reason = await asyncio.get_running_loop().run_in_executor(
        None, tts_engine.get_engine)
    if engine is None:
        return JSONResponse({"error": reason}, status_code=409)
    voice = body.voice if body.voice in engine.voices() else tts_engine.active_voice()

    def _measure() -> dict:
        import time
        import wave as _wave
        engine.synthesize("Ready.", voice=voice)          # steady-state, not first-call warmup
        t0 = time.perf_counter()
        wav = engine.synthesize(_TTS_BENCH_TEXT, voice=voice)
        synth_s = time.perf_counter() - t0
        with _wave.open(io.BytesIO(wav)) as w:
            audio_s = w.getnframes() / w.getframerate()
        rtf = synth_s / audio_s if audio_s else float("inf")
        verdict = "fast" if rtf < 0.8 else ("borderline" if rtf <= 1.25 else "slow")
        return {"rtf": round(rtf, 2), "synth_seconds": round(synth_s, 2),
                "audio_seconds": round(audio_s, 2), "verdict": verdict,
                "voice": voice, "url": f"/api/tts/clip/{_store_clip(wav)}"}

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            _tts_pool(), _measure)
    except Exception as e:      # a broken benchmark is an answer too — an honest one
        GAME.loop.debug.append("anomaly", stage="tts_benchmark", error=repr(e))
        return JSONResponse({"error": f"the narrator failed to speak: {e}"}, status_code=500)
    return JSONResponse(result)


@app.post("/api/turn")
async def post_turn(body: TurnIn) -> JSONResponse:
    text = body.text.strip()
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if GAME.session.force_ended:
        return JSONResponse({"error": "the DM has ended this session", "force_ended": True}, status_code=409)
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
    if GAME.session.force_ended:
        return JSONResponse({"error": "the DM has ended this session", "force_ended": True}, status_code=409)
    if GAME.session.pending_combat is not None:
        return JSONResponse(
            {"error": "a fight is underway — enter the Arena to resolve it", "combat_pending": True},
            status_code=409)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    # Voiced narration (opt-in per request): finished sentences go to the TTS as
    # the text streams, and each clip is announced on this same stream as
    # {"t":"audio", url, upto} — `upto` being how many narration chars (in the
    # client's UTF-16 units) the clip covers (movie mode reveals text up to it).
    # Unavailable/failed narration NEVER blocks the turn: the text flows exactly
    # as today. The engine's FIRST load is a real model load (tens of seconds on
    # the Qwen tier) — it happens on a worker thread, never on the event loop.
    engine, tts_reason = (
        await asyncio.get_running_loop().run_in_executor(None, tts_engine.get_engine)
        if body.narrate else (None, None))
    chunker = SentenceChunker() if engine is not None else None
    voice = tts_engine.active_voice() if engine is not None else None
    clip_jobs: list = []
    streamed = {"text": ""}   # exactly what the chunker was fed (attempt 0's stream)
    if engine is not None:
        # A slow tier's unfinished tail from the LAST turn must not queue ahead
        # of this one — the player already moved on (the client killed its audio
        # on send). Cancel whatever hasn't started; the running clip finishes.
        global _TTS_TURN_JOBS
        for j in _TTS_TURN_JOBS:
            j.cancel()
        _TTS_TURN_JOBS = clip_jobs

    def _u16(n: int) -> int:
        # The chunker counts Python code points; the client indexes UTF-16 units
        # (an astral emoji is 1 vs 2) — convert so movie mode never lands short
        # or splits a surrogate pair.
        return len(streamed["text"][:n].encode("utf-16-le")) // 2

    def _synth(raw: str, upto16: int) -> None:    # runs on the TTS worker thread
        speakable = clean_for_speech(raw)
        if not speakable:
            return
        try:
            wav = engine.synthesize(speakable, voice=voice)
        except Exception as e:                    # a bad sentence loses its clip, nothing more
            GAME.loop.debug.append("anomaly", stage="tts", error=repr(e))
            return
        _emit({"t": "audio", "url": f"/api/tts/clip/{_store_clip(wav)}", "upto": upto16})

    def _speak(sentences: list) -> None:
        for raw, upto in sentences:
            clip_jobs.append(_tts_pool().submit(_synth, raw, _u16(upto)))

    def on_text(delta: str) -> None:
        # Called from the model's worker thread → hop back onto the loop safely.
        loop.call_soon_threadsafe(queue.put_nowait, {"t": "delta", "v": delta})
        if chunker is not None:
            streamed["text"] += delta
            _speak(chunker.feed(delta))

    def _emit(item: dict) -> None:
        # Enqueue via the loop so a final 'done' lands AFTER all delta callbacks
        # (which on_text scheduled the same way) — preserves stream order.
        loop.call_soon_threadsafe(queue.put_nowait, item)

    async def run_turn() -> None:
        try:
            async with GAME.lock:
                report = await GAME.loop.take_turn(text, on_text=on_text, ooc=body.ooc)
                payload = _turn_payload(report)
            # The game lock is RELEASED here: everything below is audio-only.
            # Holding it through a slow tier's tail synthesis froze every other
            # endpoint for the duration.
            payload["t"] = "done"
            if body.narrate and engine is None:
                payload["tts_off"] = tts_reason   # asked for a voice we can't give — say why
            if chunker is not None:
                final = report.narration or ""
                if chunker.fed and not final.startswith(streamed["text"]):
                    # A retry rewrote the turn (the loop streams only attempt 0).
                    # The remaining draft clips would read a paragraph the player
                    # never sees — drop them; what already played is water under
                    # the bridge. The client snaps to the final text regardless.
                    for j in clip_jobs:
                        j.cancel()
                    GAME.loop.debug.append(
                        "anomaly", stage="tts",
                        error="a retry rewrote the turn — the draft's remaining clips were dropped")
                else:
                    if chunker.fed == 0 and final:
                        # Nothing streamed (a non-streaming path) — voice the final text.
                        streamed["text"] = final
                        _speak(chunker.feed(final))
                    _speak(chunker.flush())
            # 'done' goes out NOW — chips and state land instantly. The client
            # reads until the stream closes, so tail clips ride AFTER it; the
            # stream ends with an 'end' sentinel once the voice catches up.
            _emit(payload)
            if clip_jobs:
                from concurrent.futures import wait as _fwait
                await loop.run_in_executor(None, lambda: _fwait(clip_jobs, timeout=90))
                dropped = sum(1 for j in clip_jobs if j.cancel())
                if dropped:
                    GAME.loop.debug.append(
                        "anomaly", stage="tts",
                        error=f"{dropped} tail clip(s) unfinished after 90s — dropped")
            _emit({"t": "end"})
        except Exception as e:  # surface failures to the client, don't hang
            # …but never silently: keep the full traceback (console + debug log)
            # so a one-off failure is diagnosable after the fact.
            traceback.print_exc()
            GAME.loop.debug.append("anomaly", stage="turn_stream", error=repr(e))
            _emit({"t": "error", "error": str(e)})

    async def events():
        task = asyncio.create_task(run_turn())
        try:
            while True:
                item = await queue.get()
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("t") in ("end", "error"):
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
            if body.action == "sell":                          # a sold bond breaks
                _prune_attunement([c.id for c in repo.party()])
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
    sell: list[dict] = []    # [{owner, item_id, qty}] — sells leave their owner's pack
    recipient: str = "pc"    # which party member receives the purchases


@app.post("/api/trade/checkout")
async def post_checkout(body: CheckoutIn) -> JSONResponse:
    """Settle a whole basket at listed prices as ONE validated, recorded event:
    purchases land on the chosen party member, sells leave each item's owner,
    and the net coin settles against the shared purse."""
    async with GAME.lock:
        repo = GAME.session.repo
        buy = [(e["item_id"], int(e.get("qty", 1))) for e in body.buy]
        sell = [(e.get("owner", "pc"), e["item_id"], int(e.get("qty", 1))) for e in body.sell]
        try:
            ops, reason = checkout_ops(repo, body.merchant_id, buy, sell,
                                       recipient=body.recipient)
            GAME.session.emit_state(EventKind.TOOL_APPLIED, ops, tool="transact", reason=reason)
            _prune_attunement(sorted({owner for owner, _, _ in sell}))  # sold bonds break
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


class HandOverIn(BaseModel):
    from_id: str
    to_id: str
    item_id: str
    qty: int = 1
    spell: str | None = None          # scroll rider: move the EXACT stack
    spell_level: int | None = None


@app.post("/api/handover")
async def post_handover(body: HandOverIn) -> JSONResponse:
    """Bounded player action: pass an item between party members (the bard hands
    the wizard that wand). Runs through the dispatcher like any transact and is
    recorded, so it replays."""
    async with GAME.lock:
        repo = GAME.session.repo
        try:
            tx = hand_over_transact(repo, body.from_id, body.to_id, body.item_id,
                                    body.qty, spell=body.spell,
                                    spell_level=body.spell_level)
            rt = GAME.loop.dispatcher.resolve(tx)
            GAME.session.emit_state(EventKind.TOOL_APPLIED, rt.ops, tool=rt.tool, reason=rt.reason)
            _prune_attunement([body.from_id])   # a bond breaks with the hand-over
            ok, error = True, None
        except (ToolApplyError, StateError) as e:
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


@app.get("/api/trinkets")
async def get_trinkets() -> JSONResponse:
    """Every trinket the party has EARNED (quest-granted keepsakes), replay-derived
    from the event log like the offer set. Whether one is taped into the journal
    lives in the journal document itself — the client compares keys. Player-facing
    only; none of this ever enters the DM's context."""
    earned = quest_offers.earned_trinkets(
        GAME.session.authored_quests, GAME.session.store.read_all(), GAME.session.quests)
    for t in earned:
        t["image"] = _trinket_url(t["image"])
    return JSONResponse({"trinkets": earned})


@app.get("/api/journal/art")
async def journal_art_index() -> JSONResponse:
    """Everything the Bookbinder can offer, read straight from the journal art
    folder: emblem-* (cover emblems), paper-* (page styles), seal-* (wax stamp art,
    keyed by status preset). Dropping a file in static/img/journal IS the whole
    authoring story — for hand-made art and the planned Forge editor alike."""
    folder = STATIC / "img" / "journal"
    exts = {".svg", ".png", ".jpg", ".jpeg", ".webp"}

    def scan(prefix: str) -> list[str]:
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.iterdir()
                      if p.suffix.lower() in exts and p.name.startswith(prefix))

    return JSONResponse({"emblems": scan("emblem-"), "papers": scan("paper-"), "seals": scan("seal-")})


@app.get("/journal-art/{filename}", response_model=None)
async def journal_art(filename: str) -> FileResponse | JSONResponse:
    """Journal art (paper textures, cover emblems) from static/img/journal."""
    path = STATIC / "img" / "journal" / filename
    if any(c in filename for c in ("/", "\\", "..")) or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/journal-fonts/{filename}", response_model=None)
async def journal_font(filename: str) -> FileResponse | JSONResponse:
    """Bundled handwriting fonts (local files so Offline Mode keeps its penmanship)."""
    path = STATIC / "fonts" / filename
    if any(c in filename for c in ("/", "\\", "..")) or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "max-age=604800"})


@app.get("/api/packs")
async def get_packs() -> JSONResponse:
    """The worlds a new game can start in, and which one is playing now."""
    return JSONResponse({"packs": available_packs(), "current": GAME.pack_id})


@app.post("/api/pack/import")
async def post_pack_import(request: Request, overwrite: bool = False) -> JSONResponse:
    """Install a shared world zip (v0.9 portability) so it appears on the
    Choose-a-World shelf. The casual-player door: a world that fails the
    loader's validation is REFUSED whole (nothing half-installed) — fixing a
    flawed pack is the Forge's job, not the player's. `exists=True` means a
    world with this id is already installed; the page asks and retries with
    ?overwrite=true (the old copy is shelved in pack-backups, not lost)."""
    data = await request.body()
    if not data:
        return JSONResponse({"ok": False, "errors": ["the upload is empty"]}, status_code=400)
    try:
        result = packaging.import_pack(data, overwrite=overwrite, require_valid=True)
    except ValueError as e:
        return JSONResponse({"ok": False, "errors": [str(e)]}, status_code=400)
    if result["exists"]:
        return JSONResponse({"ok": False, "exists": True, "id": result["id"],
                             "name": result["name"],
                             "errors": [f"a world called “{result['name']}” is already installed"]})
    if not result["ok"]:
        return JSONResponse({"ok": False, "errors":
                             ["this world has problems and won't load:"] + result["issues"]})
    return JSONResponse({"ok": True, "id": result["id"], "name": result["name"],
                         "version": result.get("version")})


# --- chargen (CS2): serialize the ruleset for the wizard, and validate live ---
def _ruleset() -> Ruleset:
    """The ruleset for chargen — the SESSION's, which since module-kit S2 is
    pack-merged (the world's own backgrounds and items ride alongside the SRD),
    with a bare-SRD load fallback for the custom-seed case."""
    return GAME.session.ruleset or load_ruleset()


def _item_name(rs: Ruleset, item_id: str) -> str:
    """Display name for an item id: the campaign catalog first (pack items and
    DM-registered gear live there — the SRD ruleset alone would leave them as raw
    ids), then the SRD catalog, then a title-cased id. Player-facing lines must
    never read `tickle_bat` where 'Tickle Bat' will do."""
    try:
        return GAME.session.repo.get_item(item_id).name
    except StateError:
        pass
    it = rs.equipment.get(item_id)
    return it.name if it is not None else item_id.replace("_", " ").title()


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


@app.get("/api/factions")
async def get_factions() -> JSONResponse:
    """The party's Factions page (living-world W2). Redaction happens HERE,
    server-side, like the map's undiscovered places: an unknown faction ships
    only `{known: false}` — its name, description, and standing never reach the
    browser until the party learns of it (the ??? row keeps the promise that
    there is more world to meet without saying what). Standing ships as the
    TIER WORD only; the raw score never leaves the engine."""
    from ..world.events import standing_deltas
    from ..world.factions import known_ids, standing_map, tier_for
    s = GAME.session
    factions = getattr(s, "factions", None) or {}
    if not factions:
        return JSONResponse({"factions": []})
    events = s.store.read_all()
    # The SAME derivation the loop feeds the DM (loop._faction_scores) — the
    # world-event overlay included, or a silent event shift would leave this
    # page permanently disagreeing with how the world actually treats the party.
    wev = getattr(s, "world_events", None) or {}
    extra = standing_deltas(wev, factions, events) if wev else None
    scores = standing_map(factions, s.authored_quests, events, s.quests, extra=extra)
    known = known_ids(factions, s.authored_quests, events, s.quests)
    out = []
    for fid, f in factions.items():
        if fid in known:
            out.append({"known": True, "id": fid, "name": f.name,
                        "description": f.description,
                        "tier": tier_for(scores.get(fid, 0))})
        else:
            out.append({"known": False})
    return JSONResponse({"factions": out})


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
                       "equipped": s.item_id in char.equipped,
                       "requires_attunement": requires_attunement(
                           getattr(GAME.session, "mechanics_catalog", None), s.item_id),
                       "attuned": s.item_id in char.attuned} for s in char.inventory],
        # Money is the shared party purse (all PCs draw on it), preformatted.
        "purse_cp": GAME.session.repo.party_cp,
        "purse_text": format_cp(GAME.session.repo.party_cp),
        "xp": char.xp, "xp_progress": xp_progress(char),
        "conditions": list(char.conditions),
        "hit_dice_used": char.hit_dice_used, "slots_used": dict(char.spell_slots_used),
        "resources_used": dict(char.resources_used),
    }
    # The rest-time attunement ritual (multiplayer pre-work): what this hero could
    # bond with and their current bonds — drives the rest popup's picker. Only
    # shipped when there's a choice to make, so the popup stays clean otherwise.
    catalog = getattr(GAME.session, "mechanics_catalog", None)
    attunable = attunable_carried(char, catalog)
    if attunable or char.attuned:
        def _nm(item_id: str) -> str:
            eq = (catalog or {}).get(item_id)
            if eq is not None and getattr(eq, "name", None):
                return eq.name
            try:
                return repo.get_item(item_id).name
            except StateError:
                return item_id
        out["attunement"] = {
            "max": MAX_ATTUNED, "attuned": active_attuned(char),
            "attunable": [{"item_id": i, "name": _nm(i), "attuned": i in char.attuned}
                          for i in attunable],
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


# --- character portability (v0.9): export a hero, import them elsewhere -------

@app.get("/api/character-export/{char_id}")
async def get_character_export(char_id: str) -> JSONResponse:
    """One party member as a self-contained bundle: the full runtime snapshot,
    the item definitions their gear references (a pack sword still cuts in a
    world that never heard of it), and the portrait as base64. Served with a
    download disposition — the Export button on the sheet just navigates here."""
    async with GAME.lock:
        repo = GAME.session.repo
        try:
            char = repo.get_character(char_id)
        except StateError:
            return JSONResponse({"error": "no such character"}, status_code=404)
        if char.kind != "pc":
            return JSONResponse({"error": "only party members can be exported"}, status_code=400)
        ids = dict.fromkeys([*(s.item_id for s in char.inventory), *char.equipped])
        defs = []
        for iid in ids:
            try:
                defs.append(repo.get_item(iid))
            except StateError:
                pass                    # an unregistered id rides along name-only, as in play
        portrait = None
        p = _pc_portrait_path(char_id)
        if p is not None:
            mime = {v: k for k, v in _PORTRAIT_MIME_EXT.items()}.get(p.suffix, "image/png")
            portrait = (mime, p.read_bytes())
        bundle = packaging.character_bundle(char, defs, portrait)
        fname = quote(f"{(char.name or 'hero').strip()}.oubliette-character.json")
        return JSONResponse(bundle, headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


def _read_import_bundle(raw: dict, world) -> tuple[Character, list, tuple | None]:
    """Parse + gate one imported hero against the world they're joining: the
    bundle must read as a character, and the Arena bridge must be able to field
    them (OublietteDev's contract: "Oubliette and the Arena can both read it"). Raises
    ValueError with a player-facing message."""
    char, items, portrait = packaging.parse_character_bundle(raw)
    try:
        character_to_player(char, world.mechanics_catalog, world.ruleset)
    except Exception as e:                      # any bridge failure = not fieldable
        raise ValueError(f"the combat engine can't field {char.name or 'this hero'} ({e})")
    return char, items, portrait


class ImportCheckIn(BaseModel):
    pack_id: str                     # the world the hero would join
    bundle: dict                     # the parsed .oubliette-character.json


@app.post("/api/import-character/check")
async def post_import_character_check(body: ImportCheckIn) -> JSONResponse:
    """Pre-flight for the New Game wizard: is this file a hero both apps can
    read, in the chosen world? Returns a summary card for the imports strip.
    Nothing is persisted — /api/new re-runs the same gate before starting."""
    try:
        world = load_pack(body.pack_id)
    except PackValidationError:
        return JSONResponse({"ok": False, "errors": ["that world won't load"]})
    except Exception:
        return JSONResponse({"ok": False, "errors": [f"unknown world {body.pack_id!r}"]})
    try:
        char, items, portrait = _read_import_bundle(body.bundle, world)
    except ValueError as e:
        return JSONResponse({"ok": False, "errors": [str(e)]})
    sheet = char.sheet
    return JSONResponse({"ok": True, "errors": [], "summary": {
        "name": char.name, "level": char.level,
        "char_class": sheet.char_class if sheet else None,
        "race": sheet.race if sheet else None,
        "items": len(items), "has_portrait": portrait is not None}})


class RestIn(BaseModel):
    char_id: str = "pc"             # legacy: the lone member who spends hit_dice (short rest)
    kind: str                       # "short" | "long"
    hit_dice: int = 0               # legacy single-member hit-dice spend
    hit_dice_by: dict[str, int] | None = None  # short rest: hit dice each member spends, by char id
    attune_by: dict[str, list[str]] | None = None  # the rest-time attunement ritual: each member's
                                    # FULL desired bond list (absolute, max 3); omitted = unchanged


@app.post("/api/rest")
async def post_rest(body: RestIn) -> JSONResponse:
    """Take a short or long rest (CS5) — a PARTY event: every member recovers, recorded
    as one REST_TAKEN event carrying each member's recovery ops. Short-rest hit-die
    healing is individual, so only the member whose sheet was used (`char_id`) spends
    the entered dice; the rest of the party still takes the short rest (features
    recharge) with 0 dice. Hit-die rolls go through the seeded RNG.

    The S3 gate (difficulty): on a gated table a LONG rest needs the DM's standing
    grant (propose_rest) and costs the night — lodging coin in a safe haven, a
    ration per hero in the wild (the cost ops ride the same REST_TAKEN event). On
    a 'dangerous' table an unsafe night may be INTERRUPTED: the party gets only a
    short rest's recovery (the night's cost is still spent). Short rests are
    never gated."""
    async with GAME.lock:
        rs = _ruleset()
        if body.kind not in ("short", "long"):
            return JSONResponse({"ok": False, "error": "rest kind must be 'short' or 'long'"}, status_code=400)
        # The attunement ritual (multiplayer pre-work): validate every member's
        # requested bond list FIRST — a bad choice must abort before the night's
        # cost is charged or the interruption die is rolled.
        attune_ops: list = []
        catalog = getattr(GAME.session, "mechanics_catalog", None)
        try:
            for cid, ids in (body.attune_by or {}).items():
                char = GAME.session.repo.get_character(cid)
                wanted = validate_attunement(char, catalog, ids)
                if wanted != char.attuned:
                    attune_ops.append(StateOp.attune(cid, wanted))
        except StateError as e:
            return JSONResponse({"ok": False, "error": "attune", "message": str(e)},
                                status_code=400)
        cost_ops: list = []
        cost_desc: str | None = None
        interrupted = False
        gated = (body.kind == "long"
                 and GAME.session.difficulty.rest_strictness != "free")
        if gated:
            if GAME.session.pending_rest != "long":
                return JSONResponse({"ok": False, "error": "gated",
                                     "message": "This table gates long rests — ask to make "
                                     "camp in the story, and rest when the DM offers it."},
                                    status_code=409)
            place = (GAME.session.places.get(GAME.session.location)
                     if GAME.session.location else None)
            safe = bool(getattr(place, "safe_haven", False))
            try:
                cost_ops, cost_desc = long_rest_cost(GAME.session.repo, safe)
            except RestGateError as e:
                return JSONResponse({"ok": False, "error": "cost", "message": str(e)},
                                    status_code=409)
            if GAME.session.difficulty.rest_strictness == "dangerous" and not safe:
                interrupted = roll_interruption(GAME.rng)
        # An interrupted long rest grants a short rest's recovery AT BEST — no
        # healing, no slots, no hit dice spent; the night's cost is still paid.
        effective = "short" if (body.kind == "long" and interrupted) else body.kind
        ops: list = []
        for char in GAME.session.repo.party():
            if effective == "long":
                ops += long_rest_ops(char, rs)
            elif body.kind == "long":                   # interrupted night
                ops += short_rest_ops(char, rs, spend_hit_dice=0)
            else:
                if body.hit_dice_by is not None:        # per-member spend (party popup)
                    hd = max(0, body.hit_dice_by.get(char.id, 0))
                else:                                   # legacy: only the named member spends
                    hd = max(0, body.hit_dice) if char.id == body.char_id else 0
                ops += short_rest_ops(char, rs, spend_hit_dice=hd, rng=GAME.rng)
        # Attunement ops ride the same REST_TAKEN event — even an interrupted
        # night: the ritual is the rest's quiet hour, which the party had.
        GAME.session.emit_state(EventKind.REST_TAKEN, ops + attune_ops + cost_ops,
                                rest=effective, interrupted=interrupted, cost=cost_desc)
        # The world clock (living-world W3): a night consumed — long, or long
        # ATTEMPTED and interrupted — rolls the world to next morning. The day
        # number derives from the REST_TAKEN record itself; here we only turn
        # the sky, so the DM and the soundscape wake with the party.
        if (effective == "long" or interrupted) and GAME.session.time_of_day != "day":
            GAME.session.emit_environment("day", None, reason="morning comes")
        if gated:
            GAME.session.pending_rest = None            # the grant is spent
        return JSONResponse({"ok": True, "party": [_sheet_member(c, rs) for c in GAME.session.repo.party()],
                             "state": _snapshot(), "interrupted": interrupted,
                             "cost": cost_desc})


class CompanionIn(BaseModel):
    accept: bool = True


@app.post("/api/companion")
async def post_companion(body: CompanionIn) -> JSONResponse:
    """Confirm (or decline) the DM's standing companion proposal (companions S1) —
    the propose_rest pattern: the DM offered via propose_recruit/propose_dismiss,
    and THIS is the player's word that changes the roster. Accepting a recruit
    emits COMPANION_RECRUITED (the NPC's full snapshot rides the event); accepting
    a parting emits COMPANION_DISMISSED. Declining just clears the proposal — the
    DM sees the roster unchanged and plays on."""
    async with GAME.lock:
        pending = GAME.session.pending_companion
        if not pending:
            return JSONResponse({"ok": False, "error": "no companion proposal is standing — "
                                 "raise it in the story first"}, status_code=409)
        GAME.session.pending_companion = None            # one answer spends the offer
        if not body.accept:
            return JSONResponse({"ok": True, "accepted": False, "state": _snapshot()})
        try:
            char = GAME.session.repo.get_character(pending["char_id"])
        except StateError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        from ..tools.dispatch import PARTY_CAP
        if pending["action"] == "recruit":
            # Re-validate at the door: the world may have moved since the proposal.
            if char.companion or char.kind == "pc":
                return JSONResponse({"ok": False, "error": f"{char.name} is already "
                                     "with the party"}, status_code=409)
            if "dead" in (char.conditions or []):
                return JSONResponse({"ok": False, "error": f"{char.name} is dead — "
                                     "the fallen do not rejoin the party"},
                                    status_code=409)
            if len(GAME.session.repo.party()) >= PARTY_CAP:
                return JSONResponse({"ok": False, "error": f"the party is full "
                                     f"({PARTY_CAP} members)"}, status_code=409)
            GAME.session.emit_companion_recruited(
                char, origin=pending.get("origin") or "recruited",
                reason=pending.get("reason") or "joined the party")
            # A creature recruited into a party already past its threshold grows
            # on the spot — card now, DM note next turn (same contract as level-up).
            grown = GAME.loop._check_companion_growth()
            if grown:
                GAME.session.pending_growth_note += grown
        else:
            if not char.companion:
                return JSONResponse({"ok": False, "error": f"{char.name} isn't a "
                                     "companion"}, status_code=409)
            grown = []
            GAME.session.emit_companion_dismissed(
                char.id, reason=pending.get("reason") or "parted ways")
        return JSONResponse({"ok": True, "accepted": True,
                             "action": pending["action"],
                             "name": char.name, "state": _snapshot(),
                             "growth": grown})


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
        # Companion growth (S2): a level-up can cross a creature's authored
        # threshold — grow them NOW so the player sees the 🐉 card with the
        # level-up, not welded onto their next unrelated message. The DM gets a
        # pending note to acknowledge it in the fiction next turn.
        grown = GAME.loop._check_companion_growth()
        if grown:
            GAME.session.pending_growth_note += grown
        return JSONResponse({"ok": True, "party": [_sheet_member(c, rs) for c in GAME.session.repo.party()],
                             "state": _snapshot(), "growth": grown})


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
    difficulty: DifficultySettings | None = None   # the danger dials agreed at New Game (optional)
    build: CharacterBuild | None = None     # legacy single character (a party of one)
    builds: list[CharacterBuild] | None = None  # the chargen party (preferred); None/[] = quick-start
    imports: list[dict] | None = None       # heroes carried over as character bundles (v0.9)


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
        # Imported heroes gate against the TARGET world (its merged catalog) before
        # the save is erased, for the same reason.
        parsed_imports: list[tuple[Character, list, tuple | None]] = []
        raw_imports = (body.imports if body and body.imports else [])
        if raw_imports:
            target = (body.pack_id if body and body.pack_id else GAME.pack_id)
            try:
                world = load_pack(target)
            except Exception:
                return JSONResponse({"ok": False, "errors": [f"world {target!r} won't load"]},
                                    status_code=400)
            for i, raw in enumerate(raw_imports):
                try:
                    parsed_imports.append(_read_import_bundle(raw, world))
                except ValueError as e:
                    return JSONResponse({"ok": False,
                                         "errors": [f"imported hero #{i + 1}: {e}"]},
                                        status_code=400)
        GAME.new_game(body.pack_id if body else None, body.table if body else None,
                      body.difficulty if body else None)
        if builds or parsed_imports:
            chars = GAME.session.emit_party_created(
                builds, imports=[(c, defs) for c, defs, _ in parsed_imports])
            # Imported portraits: the bytes land beside the NEW save, and a
            # PORTRAIT_SET event records the reference — the exact path the
            # sheet's upload button takes, so replay just works.
            for (char, _defs, portrait), member in zip(parsed_imports, chars[len(builds):]):
                if portrait is None:
                    continue
                ext = _PORTRAIT_MIME_EXT.get(portrait[0])
                if ext is None:
                    continue
                _PC_PORTRAITS.mkdir(parents=True, exist_ok=True)
                for old in _PC_PORTRAITS.glob(f"{member.id}.*"):
                    old.unlink()
                fname = f"{member.id}{ext}"
                (_PC_PORTRAITS / fname).write_bytes(portrait[1])
                GAME.session.emit_state(
                    EventKind.PORTRAIT_SET, [StateOp.portrait(member.id, fname)],
                    reason=f"imported portrait for {member.name}")
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
    model: str | None = None        # free-text model id (v0.9 provider opening)
    base_url: str | None = None     # local-server address (local provider only)
    disconnect: bool = False        # explicit "clear my key, go offline"
    # Optional custom token prices for the cost meter ($ per MILLION tokens).
    # Both set -> the meter prices with these instead of the built-in table;
    # blank -> back to the table. Anthropic-only for now (the only metered provider).
    price_in: float | None = None
    price_out: float | None = None


def _body_pricing(body: ProviderSetBody) -> dict | None:
    """The request's custom-pricing entry, or None when the fields are blank."""
    if body.price_in is None or body.price_out is None:
        return None
    return {"input": body.price_in, "output": body.price_out}


def _pretty_model(mid: str) -> str:
    """`claude-sonnet-5` -> `Claude Sonnet 5` for the connection badge; a
    non-Claude id shows verbatim (the player typed it — echoing it back exactly
    is the honest badge)."""
    if not mid.startswith("claude-"):
        return mid
    words, nums = [], []
    for tok in mid.split("-"):
        (nums if tok.isdigit() else words).append(tok)
    return f"{' '.join(w.capitalize() for w in words)} {'.'.join(nums)}".strip()


def _provider_status() -> dict:
    """Live connection state for the front door: is a real DM wired up, and a
    friendly model label when it is. (`scripted` == offline stub.)"""
    online = GAME.client_name != "scripted"
    model = _pretty_model(providers.stored_model(GAME.client_name)) if online else ""
    return {"online": online, "client": GAME.client_name,
            "selected": providers.selected_provider(), "model": model}


def _throwaway_client(body: ProviderSetBody):
    """A client from the request's settings, falling back to what's stored for
    any field left blank (so 'test' works with a saved key + a new model)."""
    from ..llm import connect
    key = (body.api_key or "").strip() or providers.stored_key(body.provider)
    model = (body.model or "").strip() or providers.stored_model(body.provider)
    base = (body.base_url or "").strip() or providers.stored_base_url(body.provider)
    return connect.build_client(body.provider, key, model, base)


@app.get("/api/providers")
async def get_providers() -> JSONResponse:
    """The provider roster plus the current connection state. Never returns key
    material — only whether one is on file."""
    return JSONResponse({"providers": providers.registry_view(), **_provider_status()})


@app.post("/api/providers/test")
async def post_providers_test(body: ProviderSetBody) -> JSONResponse:
    """Prove a provider/key/model/address combination works WITHOUT saving it:
    one real, tiny forced-tool call through the same client the game would use
    (a fraction of a cent). This is the typo-catcher — `clade-sonnet-5` comes
    back as a plain sentence, not a mid-game crash."""
    from ..llm import connect
    try:
        client = _throwaway_client(body)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    ok, error = await connect.ping(client)
    return JSONResponse({"ok": ok, "error": error})


@app.post("/api/providers")
async def post_providers(body: ProviderSetBody) -> JSONResponse:
    """Save the chosen provider settings and re-pick the live DM immediately (no
    restart) — but only AFTER a live connection test passes, so a typo'd model
    id can never enter the config through the UI. Saving with everything blank
    (no key on a key-required provider) is the deliberate 'back to offline'
    path and skips the test."""
    from ..llm import connect
    prov = providers.get_provider(body.provider)
    if prov is None or not prov.implemented:
        return JSONResponse(
            {"ok": False, "error": f"{body.provider!r} isn't available yet",
             "providers": providers.registry_view(), **_provider_status()},
            status_code=400)
    if body.disconnect:
        async with GAME.lock:
            providers.set_provider_key(body.provider, None,
                                       model=body.model, base_url=body.base_url,
                                       pricing=_body_pricing(body))
            GAME.refresh_client()
        return JSONResponse({"ok": True, "providers": providers.registry_view(),
                             **_provider_status()})
    # A blank key keeps the saved one (so changing just the model doesn't demand
    # re-pasting a key); the explicit `disconnect` flag is how you go offline.
    key = (body.api_key or "").strip() or providers.stored_key(body.provider)
    going_live = bool(key) or (prov.key_optional and bool(
        (body.model or "").strip() or providers.stored_model(body.provider)))
    if not going_live:
        return JSONResponse(
            {"ok": False, "error": f"no {prov.key_label} set",
             "providers": providers.registry_view(), **_provider_status()},
            status_code=400)
    try:
        client = _throwaway_client(body)
        ok, error = await connect.ping(client)
    except Exception as e:
        ok, error = False, str(e)
    if not ok:
        return JSONResponse(
            {"ok": False, "error": error or "could not connect",
             "providers": providers.registry_view(), **_provider_status()},
            status_code=400)
    async with GAME.lock:
        providers.set_provider_key(body.provider, key,
                                   model=body.model, base_url=body.base_url,
                                   pricing=_body_pricing(body))
        GAME.refresh_client()
    return JSONResponse({"ok": True, "providers": providers.registry_view(),
                         **_provider_status()})


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
