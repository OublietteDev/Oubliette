"""The turn loop (spec §12). Wires assess -> roll -> resolve -> apply -> render.
Async at this edge (D2); the appliers it calls are sync-pure."""
