# Journal art — drop a file, get an option

Everything in this folder is discovered by filename prefix and offered in the
game automatically (`GET /api/journal/art`). No code changes, no registration:
drop a file here, restart the app server, and it's in the Bookbinder.
Formats: `.svg`, `.png`, `.jpg`, `.webp`.

## Papers — `paper-<name>.png`
A full page background, stretched to fit the page. The `<name>` becomes the
option (and is stored in the save), so `paper-vellum.png` shows up as "vellum".
- Recommended size: **~900 × 1150 px** or larger (pages are ~465 × 560 on
  screen; extra resolution keeps zoomed/high-DPI screens crisp).
- Ink is dark and semi-transparent highlights sit on top, so keep the paper
  **light** (think cream/tan) and low-contrast — busy texture fights handwriting.
- `paper-clean` is the fallback when a save references a paper that isn't
  installed, so don't delete it.

## Wax seals — `seal-<key>.png`
The image replaces the CSS wax circle for that stamp; the status text is drawn
on top and the image is auto-scaled to the stamp (currently 50 × 50 px, any
source resolution works).
- Keys: `seal-progress`, `seal-done`, `seal-failed`, `seal-important` (the four
  presets) and `seal-custom` (used for player-written stamp text).
- Make it **square with a transparent background**, wax roughly filling the
  canvas with ~8–10% padding. **No writing on the wax** — the game stamps the
  words. Light text goes on top, so darker waxes read best.
- No `seal-*` file → the built-in CSS wax circle is used. Ship any subset.

## Cover emblems — `emblem-<name>.svg`
Shown gold-embossed on the leather cover (~120 px) and as a picker thumbnail
(~56 px). Line art on transparency reads best on dark leather; the bundled
ones are stroke-only SVGs in `#c9a457` gold. PNG works too.
This folder is also the hook for the planned Forge emblem editor — it will
simply write files here.
