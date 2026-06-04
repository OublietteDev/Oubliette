"""Pure SRD resolution. No I/O, no LLM, no randomness — results in, decision out.

This package depends on nothing else in the tree (spec §2 dependency rule), which
is what keeps replay trivial: every function here is a pure function of its inputs.
"""
