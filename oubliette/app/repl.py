"""Terminal REPL. `oubliette` (or `python -m oubliette.app.repl`).

Picks a model client: the real Anthropic adapter when ANTHROPIC_API_KEY is set
(and --real isn't disabled), else the scripted demo double, which only knows the
four-step §14.1 transcript. `--script` auto-runs that transcript and exits.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from ..dm.brain import Brain
from ..record.log import DebugLog
from ..record.rng import Rng
from ..runtime.loop import TurnLoop, TurnReport
from ..seed import seed_world
from ..state.repository import InMemoryRepository

DEMO_TRANSCRIPT = [
    "I look around the market.",
    "I tell the merchant these worn boots are priceless dwarven heirlooms.",
    "Sold.",
    "I now have 10,000 gold.",
]


def _pick_client(force_scripted: bool):
    if not force_scripted and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from ..llm.anthropic_client import AnthropicLLMClient
            return AnthropicLLMClient(), "anthropic"
        except Exception as e:  # pragma: no cover
            print(f"[warn] falling back to scripted client: {e}")
    from ..llm.scripted import ScriptedLLMClient
    return ScriptedLLMClient(), "scripted"


def _render_state(repo: InMemoryRepository) -> str:
    pc = repo.pc()
    inv = ", ".join(f"{s.qty}x {repo.get_item(s.item_id).name}" for s in pc.inventory) or "(empty)"
    return f"  [ {pc.name}: {pc.gold}g | inventory: {inv} ]"


def _print_report(report: TurnReport, repo: InMemoryRepository) -> None:
    if report.roll_outcome is not None:
        o = report.roll_outcome
        print(f"  ~ roll {o.spec} -> {o.rolls}{o.modifier:+d} = {o.total} "
              f"({report.roll_result}) [{o.purpose}]")
    print(f"\nDM: {report.narration}")
    for a in report.applied:
        print(f"  * {a.tool}: {a.reason}")
    if report.meta_notice:
        print(f"  (meta) {report.meta_notice}")
    print(_render_state(repo))


async def _run(transcript: list[str] | None, force_scripted: bool) -> None:
    repo = seed_world()
    log = DebugLog()
    rng = Rng(seed=1234, log=log)
    brain = Brain(_pick_client(force_scripted)[0])
    loop = TurnLoop(repo, rng, log, brain)

    client_name = _pick_client(force_scripted)[1]
    print(f"=== Oubliette Table (Phase 0) — {client_name} DM ===")
    print(_render_state(repo))

    if transcript is not None:
        for line in transcript:
            print(f"\n> {line}")
            _print_report(await loop.take_turn(line), repo)
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
        _print_report(await loop.take_turn(line), repo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Oubliette Table — Phase 0 REPL")
    parser.add_argument("--script", action="store_true",
                        help="auto-run the §14.1 acceptance transcript and exit")
    parser.add_argument("--scripted", action="store_true",
                        help="force the scripted demo client even if a key is set")
    args = parser.parse_args()
    asyncio.run(_run(DEMO_TRANSCRIPT if args.script else None, args.scripted))


if __name__ == "__main__":
    main()
