"""The living-world layer (post-v0.9 arc): authored content that makes the
world act on its own — keyed encounters now; factions and timed events in
later slices. Every module here is a PURE derivation over the event log +
authored pack data, same contract as quest offers: nothing stored mutably,
replay reproduces it byte-for-byte, and a pack that authors none of it
behaves exactly as before."""
