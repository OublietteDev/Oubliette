"""The dispatcher: validate a tool call against current state and RESOLVE it into
replayable `StateOp`s. It does NOT mutate — the session appends the event and
applies the ops (one application path for live + replay).

Because resolution is pure (read-only validation), the runtime can resolve ALL
of a turn's tool calls before applying any, so a turn is atomic: either every
tool applies or none does (no partial-application gap).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from ..record.events import StateOp
from ..schemas import ToolCall
from ..state.repository import Repository, StateError
from .schemas import TOOL_SCHEMAS, Give, Take, Transact, ValueEntry


class ToolApplyError(Exception):
    """A tool call that fails validation. Carries a message fed back to the model
    on retry (D6). Nothing is mutated."""


@dataclass
class ResolvedTool:
    tool: str
    ops: list[StateOp]
    reason: str


class Dispatcher:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def resolve(self, call: ToolCall) -> ResolvedTool:
        schema = TOOL_SCHEMAS.get(call.tool)
        if schema is None:
            raise ToolApplyError(f"unknown tool {call.tool!r}")
        try:
            parsed = schema.model_validate(call.args)
        except ValidationError as e:
            raise ToolApplyError(f"invalid args for {call.tool}: {e}") from e

        if isinstance(parsed, Transact):
            ops = self._resolve_transact(parsed)
            reason = parsed.reason
        elif isinstance(parsed, Give):
            ops = [self._credit_op(parsed.to, e) for e in parsed.items]
            reason = parsed.reason
        elif isinstance(parsed, Take):
            self._assert_can_cover(parsed.from_, parsed.items)
            ops = [self._debit_op(parsed.from_, e) for e in parsed.items]
            reason = parsed.reason
        else:  # pragma: no cover
            raise ToolApplyError(f"no resolver for {call.tool!r}")

        return ResolvedTool(tool=call.tool, ops=ops, reason=reason)

    # --- resolvers ------------------------------------------------------------
    def _resolve_transact(self, t: Transact) -> list[StateOp]:
        # Validate BOTH sides can cover their half (transact symmetry, §5).
        self._assert_can_cover(t.from_, t.give)
        self._assert_can_cover(t.counterparty, t.receive)
        ops: list[StateOp] = []
        for e in t.give:        # from_ -> counterparty
            ops += self._move_ops(t.from_, t.counterparty, e)
        for e in t.receive:     # counterparty -> from_
            ops += self._move_ops(t.counterparty, t.from_, e)
        return ops

    # --- helpers --------------------------------------------------------------
    def _assert_can_cover(self, char_id: str, entries: list[ValueEntry]) -> None:
        try:
            char = self.repo.get_character(char_id)
        except StateError as e:
            raise ToolApplyError(str(e)) from e
        need_gold = sum(e.gold for e in entries if e.gold is not None)
        if char.gold < need_gold:
            raise ToolApplyError(f"{char.name} cannot cover {need_gold}g (has {char.gold}g)")
        for e in entries:
            if e.item_id is not None and char.item_qty(e.item_id) < e.qty:
                raise ToolApplyError(
                    f"{char.name} lacks {e.qty}x {e.item_id} (has {char.item_qty(e.item_id)})")

    def _move_ops(self, src: str, dst: str, e: ValueEntry) -> list[StateOp]:
        return [self._debit_op(src, e), self._credit_op(dst, e)]

    def _debit_op(self, char_id: str, e: ValueEntry) -> StateOp:
        if e.gold is not None:
            return StateOp.gold(char_id, -e.gold)
        return StateOp.item(char_id, e.item_id, -e.qty)

    def _credit_op(self, char_id: str, e: ValueEntry) -> StateOp:
        if e.gold is not None:
            return StateOp.gold(char_id, e.gold)
        return StateOp.item(char_id, e.item_id, e.qty)
