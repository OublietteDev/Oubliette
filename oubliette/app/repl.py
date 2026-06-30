"""Terminal REPL. `oubliette` (or `python -m oubliette.app.repl`).

Picks a model client: the real Anthropic adapter when ANTHROPIC_API_KEY is set
(and --real isn't disabled), else the scripted demo double, which only knows the
four-step §14.1 transcript. `--script` auto-runs that transcript and exits.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from ..dm.brain import Brain
from ..record.rng import Rng
from ..record.store import InMemoryEventStore, SqliteEventStore
from ..runtime.loop import TurnLoop, TurnReport
from ..runtime.session import Session
from ..state.repository import Repository

DEMO_TRANSCRIPT = [
    "I look around the market.",
    "I tell the merchant these worn boots are priceless dwarven heirlooms.",
    "Sold.",
    "I now have 10,000 gold.",
]

# Phase 1: combat boundary — a fight (first-class victory) and a non-combat exit.
COMBAT_TRANSCRIPT = [
    "I draw my knife and attack the bandit.",
    "I try to talk the bandits down.",
]

# Phase 3: canonization — introduce a new NPC as provisional world canon.
CANON_TRANSCRIPT = [
    "I approach the old woman at the well and ask her name.",
]


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependency): set vars not already in the environment.
    Lets `python -m oubliette.app.repl` pick up ANTHROPIC_API_KEY from a gitignored
    .env file. Never overrides an explicitly-set environment variable."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _pick_client(force_scripted: bool):
    """Pick the DM client from the player's saved provider/key (front-door config),
    falling back to the scripted OFFLINE stub when no live provider is configured.
    The config's key takes precedence, then the provider's env var (so a .env /
    ANTHROPIC_API_KEY still works untouched). Only wired providers can go live; an
    unimplemented selection or a missing key lands on the offline stub."""
    if not force_scripted:
        from ..llm import providers
        prov = providers.selected_provider()
        key = providers.stored_key(prov)
        if prov == "anthropic" and key:
            try:
                from ..llm.anthropic_client import AnthropicLLMClient
                return AnthropicLLMClient(api_key=key), "anthropic"
            except Exception as e:  # pragma: no cover
                print(f"[warn] falling back to scripted client: {e}")
    from ..llm.scripted import ScriptedLLMClient
    return ScriptedLLMClient(), "scripted"


def _render_state(session: Session) -> str:
    repo = session.repo
    pc = repo.pc()
    inv = ", ".join(f"{s.qty}x {repo.get_item(s.item_id).name}" for s in pc.inventory) or "(empty)"
    line = f"  [ {pc.name}: {pc.hp}/{pc.max_hp} HP | {pc.gold}g | {pc.xp} XP | inventory: {inv} ]"
    canon = [r for r in session.canon.all() if r.origin != "authored"]  # session canon only
    if canon:
        line += "\n  [ canon: " + ", ".join(f"{r.name} ({r.status})" for r in canon) + " ]"
    return line


def _print_report(report: TurnReport, session: Session) -> None:
    if report.roll_outcome is not None:
        o = report.roll_outcome
        print(f"  ~ roll {o.spec} -> {o.rolls}{o.modifier:+d} = {o.total} "
              f"({report.roll_result}) [{o.purpose}]")
    print(f"\nDM: {report.narration}")
    for a in report.applied:
        print(f"  * {a.tool}: {a.reason}")
    if report.combat_result is not None:
        cr = report.combat_result
        extra = f", +{cr.xp_award} XP" if cr.xp_award else ""
        print(f"  [combat] outcome: {cr.outcome}{extra}")
    if report.meta_notice:
        print(f"  (meta) {report.meta_notice}")
    print(_render_state(session))


async def _run(transcript: list[str] | None, force_scripted: bool, db: str | None) -> None:
    store = SqliteEventStore(db) if db else InMemoryEventStore()
    session = Session.open(store)
    repo = session.repo
    rng = Rng(seed=1234, record=session.emit_log)
    client, client_name = _pick_client(force_scripted)
    loop = TurnLoop(session, rng, Brain(client))

    where = f"sqlite:{db}" if db else "in-memory"
    print(f"=== Oubliette Table (Phase 3) — {client_name} DM | log: {where} ===")
    print(f"  ({len(store.read_all())} events replayed)")
    print(_render_state(session))

    if transcript is not None:
        for line in transcript:
            print(f"\n> {line}")
            _print_report(await loop.take_turn(line), session)
        store.close()
        return

    print("\n(type 'quit' to exit)")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.lower() in {"quit", "exit"}:
            break
        if not line:
            continue
        _print_report(await loop.take_turn(line), session)
    store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Oubliette Table — Phase 0 REPL")
    parser.add_argument("--script", action="store_true",
                        help="auto-run the §14.1 acceptance transcript and exit")
    parser.add_argument("--combat", action="store_true",
                        help="auto-run the Phase 1 combat-boundary demo and exit")
    parser.add_argument("--canon", action="store_true",
                        help="auto-run the Phase 3 canonization demo and exit")
    parser.add_argument("--scripted", action="store_true",
                        help="force the scripted demo client even if a key is set")
    parser.add_argument("--db", metavar="PATH", default=None,
                        help="persist the event log to this SQLite file (reloads + replays on start)")
    args = parser.parse_args()

    _load_dotenv()  # pick up ANTHROPIC_API_KEY from a gitignored .env, if present

    try:  # keep em-dashes etc. from crashing a cp1252 Windows console
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    transcript = None
    if args.script:
        transcript = DEMO_TRANSCRIPT
    elif args.combat:
        transcript = COMBAT_TRANSCRIPT
    elif args.canon:
        transcript = CANON_TRANSCRIPT
    asyncio.run(_run(transcript, args.scripted, args.db))


if __name__ == "__main__":
    main()
