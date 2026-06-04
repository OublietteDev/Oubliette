"""The dispatcher: validate a tool call, apply it to protected state, record it.

Append-then-commit ordering and the both-parties delta record (spec §5). Any
failure raises `ToolApplyError` and mutates nothing — the runtime turns that into
the D6 retry path.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..record.log import DebugLog
from ..schemas import ToolCall
from ..state.repository import Repository, StateError
from .schemas import TOOL_SCHEMAS, Give, Take, Transact, ValueEntry


class ToolApplyError(Exception):
    """A tool call that could not be validated or applied. Carries a message the
    runtime feeds back to the model on retry."""


class AppliedTool:
    def __init__(self, tool: str, deltas: dict, reason: str) -> None:
        self.tool = tool
        self.deltas = deltas        # {char_id: {"gold": +n, "items": {item_id: +/-n}}}
        self.reason = reason


class Dispatcher:
    def __init__(self, repo: Repository, log: DebugLog) -> None:
        self.repo = repo
        self.log = log

    def apply(self, call: ToolCall) -> AppliedTool:
        schema = TOOL_SCHEMAS.get(call.tool)
        if schema is None:
            raise ToolApplyError(f"unknown tool {call.tool!r}")
        try:
            parsed = schema.model_validate(call.args)
        except ValidationError as e:
            raise ToolApplyError(f"invalid args for {call.tool}: {e}") from e

        if isinstance(parsed, Transact):
            applied = self._apply_transact(parsed)
        elif isinstance(parsed, Give):
            applied = self._apply_give(parsed)
        elif isinstance(parsed, Take):
            applied = self._apply_take(parsed)
        else:  # pragma: no cover
            raise ToolApplyError(f"no applier for {call.tool!r}")

        # Record AFTER a successful apply (Phase 2: this becomes a TOOL_APPLIED event).
        self.log.append("tool_applied", tool=applied.tool, deltas=applied.deltas,
                        reason=applied.reason)
        return applied

    # --- appliers -------------------------------------------------------------
    def _apply_transact(self, t: Transact) -> AppliedTool:
        # Validate BOTH sides can cover their half before mutating anything.
        self._assert_can_cover(t.from_, t.give)
        self._assert_can_cover(t.counterparty, t.receive)

        deltas: dict = {t.from_: {"gold": 0, "items": {}},
                        t.counterparty: {"gold": 0, "items": {}}}
        # from_ gives -> counterparty receives
        self._move(t.from_, t.counterparty, t.give, deltas)
        # counterparty gives -> from_ receives
        self._move(t.counterparty, t.from_, t.receive, deltas)
        return AppliedTool("transact", deltas, t.reason)

    def _apply_give(self, g: Give) -> AppliedTool:
        deltas: dict = {g.to: {"gold": 0, "items": {}}}
        for e in g.items:
            self._credit(g.to, e, deltas)
        return AppliedTool("give", deltas, g.reason)

    def _apply_take(self, tk: Take) -> AppliedTool:
        self._assert_can_cover(tk.from_, tk.items)
        deltas: dict = {tk.from_: {"gold": 0, "items": {}}}
        for e in tk.items:
            self._debit(tk.from_, e, deltas)
        return AppliedTool("take", deltas, tk.reason)

    # --- helpers --------------------------------------------------------------
    def _assert_can_cover(self, char_id: str, entries: list[ValueEntry]) -> None:
        try:
            char = self.repo.get_character(char_id)
        except StateError as e:
            raise ToolApplyError(str(e)) from e
        need_gold = sum(e.gold for e in entries if e.gold is not None)
        if char.gold < need_gold:
            raise ToolApplyError(
                f"{char.name} cannot cover {need_gold}g (has {char.gold}g)")
        for e in entries:
            if e.item_id is not None and char.item_qty(e.item_id) < e.qty:
                raise ToolApplyError(
                    f"{char.name} lacks {e.qty}x {e.item_id} "
                    f"(has {char.item_qty(e.item_id)})")

    def _move(self, src: str, dst: str, entries: list[ValueEntry], deltas: dict) -> None:
        for e in entries:
            self._debit(src, e, deltas)
            self._credit(dst, e, deltas)

    def _debit(self, char_id: str, e: ValueEntry, deltas: dict) -> None:
        d = deltas.setdefault(char_id, {"gold": 0, "items": {}})
        try:
            if e.gold is not None:
                self.repo.adjust_gold(char_id, -e.gold)
                d["gold"] -= e.gold
            else:
                self.repo.remove_item(char_id, e.item_id, e.qty)
                d["items"][e.item_id] = d["items"].get(e.item_id, 0) - e.qty
        except StateError as ex:
            raise ToolApplyError(str(ex)) from ex

    def _credit(self, char_id: str, e: ValueEntry, deltas: dict) -> None:
        d = deltas.setdefault(char_id, {"gold": 0, "items": {}})
        try:
            if e.gold is not None:
                self.repo.adjust_gold(char_id, e.gold)
                d["gold"] += e.gold
            else:
                self.repo.add_item(char_id, e.item_id, e.qty)
                d["items"][e.item_id] = d["items"].get(e.item_id, 0) + e.qty
        except StateError as ex:
            raise ToolApplyError(str(ex)) from ex
