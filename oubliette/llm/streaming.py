"""Incremental extraction of a string field from streaming (partial) JSON.

The DM's narration arrives inside a forced-tool-use structured output, so to
stream it we accumulate the tool's partial `input` JSON and re-extract the
`narration` value as it grows. This decodes JSON escapes and stops cleanly at an
incomplete trailing escape, so we never emit a half-decoded character.
"""

from __future__ import annotations

_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b",
                   "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def extract_string_field(partial: str, field: str) -> str:
    """Return the decoded value-so-far of top-level string `field` in `partial`
    JSON. Returns "" until the field's opening quote has arrived. Stops before the
    closing quote (value not yet complete) and before any incomplete escape."""
    key = '"' + field + '"'
    i = partial.find(key)
    if i == -1:
        return ""
    j = partial.find(":", i + len(key))
    if j == -1:
        return ""
    k = j + 1
    while k < len(partial) and partial[k] in " \t\n\r":
        k += 1
    if k >= len(partial) or partial[k] != '"':
        return ""
    k += 1  # first char of the value
    out: list[str] = []
    n = len(partial)
    while k < n:
        c = partial[k]
        if c == '"':
            break  # closing quote — value complete
        if c == "\\":
            if k + 1 >= n:
                break  # incomplete escape; wait for more
            e = partial[k + 1]
            if e in _SIMPLE_ESCAPES:
                out.append(_SIMPLE_ESCAPES[e])
                k += 2
                continue
            if e == "u":
                if k + 6 > n:
                    break  # incomplete \uXXXX
                try:
                    out.append(chr(int(partial[k + 2:k + 6], 16)))
                except ValueError:
                    break
                k += 6
                continue
            break  # unknown escape — stop
        out.append(c)
        k += 1
    return "".join(out)
