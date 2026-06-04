"""Unit tests for the partial-JSON narration extractor (the risky streaming bit)."""

from __future__ import annotations

from oubliette.llm.streaming import extract_string_field


def test_grows_as_json_arrives():
    chunks = ['{"narrat', 'ion": "You st', 'ep into the ', 'market."', ', "tool_calls": []}']
    acc = ""
    seen = []
    for c in chunks:
        acc += c
        seen.append(extract_string_field(acc, "narration"))
    assert seen[0] == ""                      # field name not complete yet
    assert seen[-1] == "You step into the market."
    # monotonically non-decreasing prefix growth
    for a, b in zip(seen, seen[1:]):
        assert b.startswith(a)


def test_decodes_escapes_and_holds_incomplete_ones():
    # complete escapes decode
    assert extract_string_field('{"narration": "a\\nb\\"c"', "narration") == 'a\nb"c'
    # a trailing backslash (incomplete escape) is held back, not emitted raw
    assert extract_string_field('{"narration": "hello\\', "narration") == "hello"
    # incomplete \u escape is held
    assert extract_string_field('{"narration": "x\\u26', "narration") == "x"


def test_stops_at_closing_quote_ignores_later_fields():
    full = '{"narration": "Done.", "tool_calls": [{"tool": "transact"}]}'
    assert extract_string_field(full, "narration") == "Done."


def test_field_absent_returns_empty():
    assert extract_string_field('{"tool_calls": []}', "narration") == ""
    assert extract_string_field("", "narration") == ""
