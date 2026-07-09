"""Sentence chunking for streamed narration.

The model delivers narration as sub-word fragments; the TTS wants whole
sentences (that's what keeps time-to-first-audio short — sentence one goes to
the synthesizer while the model is still writing sentence five). The chunker
buffers raw deltas and emits (raw_sentence, upto) pairs, where `upto` is the
cumulative count of RAW streamed characters through the end of that sentence —
the browser's movie mode uses it to reveal text in step with the voice, so it
must index into exactly the text the client accumulated (markdown and all).
"""

from __future__ import annotations

import re

# A sentence ends at terminal punctuation (plus any closing quotes/brackets),
# followed by whitespace. Decimal numbers ("3.5 gp") survive because the digit
# after the dot isn't whitespace; abbreviations ("Mr. Smith") do split, which
# costs a breath mid-name — livable, and far better than a clever list of
# exceptions that misses the fantasy ones anyway.
_BOUNDARY = re.compile(r'[.!?…]+["\'”’)\]]*\s+')

# A run-on sentence longer than this is force-split at the last space so a
# single breathless paragraph can't stall the voice (nor feed the synthesizer
# a monster it chokes on).
MAX_SENTENCE = 360


class SentenceChunker:
    """Feed streamed deltas in, get finished sentences out. Single-consumer —
    the turn's model worker thread owns it."""

    def __init__(self, max_sentence: int = MAX_SENTENCE):
        self.max_sentence = max_sentence
        self._buf = ""
        self.consumed = 0          # raw chars emitted so far (== last upto)
        self.fed = 0               # raw chars fed so far — emitted OR still buffered.
                                   # This is the "did anything stream?" question; `consumed`
                                   # is 0 for a single sentence still waiting in the buffer.

    def feed(self, delta: str) -> list[tuple[str, int]]:
        self.fed += len(delta)
        self._buf += delta
        return self._drain()

    def flush(self) -> list[tuple[str, int]]:
        """End of turn: whatever remains is the last sentence."""
        out = self._drain()
        if self._buf:
            self.consumed += len(self._buf)
            if self._buf.strip():
                out.append((self._buf, self.consumed))
            self._buf = ""
        return out

    def _drain(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        while True:
            m = _BOUNDARY.search(self._buf)
            if m is not None:
                cut = m.end()      # trailing whitespace rides along so upto stays exact
            elif len(self._buf) > self.max_sentence:
                space = self._buf.rfind(" ", 0, self.max_sentence)
                cut = space + 1 if space > 0 else self.max_sentence
            else:
                return out
            raw, self._buf = self._buf[:cut], self._buf[cut:]
            self.consumed += len(raw)
            if raw.strip():
                out.append((raw, self.consumed))


# --- markdown → speakable text --------------------------------------------

_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), " "),          # fenced code: unreadable aloud
    (re.compile(r"`([^`]*)`"), r"\1"),              # inline code → its text
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # image → alt text
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),   # link → its label
    (re.compile(r"^\s{0,3}#{1,6}\s+", re.M), ""),   # heading marks
    (re.compile(r"^\s{0,3}>\s?", re.M), ""),        # blockquote marks
    (re.compile(r"^\s{0,3}[-*+]\s+", re.M), ""),    # list bullets
    (re.compile(r"[*_~]{1,3}"), ""),                # emphasis marks
]


def clean_for_speech(text: str) -> str:
    """Strip markdown down to the words a narrator would actually say."""
    for pat, repl in _MD_PATTERNS:
        text = pat.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()
