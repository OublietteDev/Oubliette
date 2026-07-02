# Oubliette Table — Playtester's Guide

Thanks for trying this out! **Oubliette Table** is an AI-narrated text RPG built on
the Dungeons & Dragons SRD. You play in your browser: tell the Dungeon Master (the
"Phantom") what your character does, and the story unfolds — while the *code* keeps
the rules, your gold, your inventory, and the dice honest behind the scenes.

This guide gets you from a fresh download to playing in a few minutes.

---

## 1. What you need

- **Windows 10 or 11.**
- **Python 3.11, 3.12, or 3.13** (⚠ NOT 3.14 or newer — the game's graphics
  library doesn't support it yet). It's a free, one-time install from
  <https://www.python.org/downloads/>. On the **first install screen, tick
  "Add Python to PATH"**, then click Install. If you already have Python 3.14,
  that's fine — install 3.13 *alongside* it and setup will pick the right one.
- **An Anthropic (Claude) API key** — see step 3. (You can poke around without one,
  but you'll only get the built-in demo script, not the real AI Dungeon Master.)

## 2. Install (once)

1. Unzip the project folder somewhere convenient (e.g. your Desktop).
2. **Double-click `setup.bat`.** It builds a private environment and downloads
   everything it needs. The first run takes a few minutes; you'll see
   "Setup complete!" when it's done.

If `setup.bat` says Python wasn't found — or that your Python is too new —
install Python 3.13 (step 1) and run it again; it sorts itself out from there.

## 3. Get your API key

The Dungeon Master is powered by Anthropic's Claude. You supply your own key:

1. Go to <https://console.anthropic.com/> and sign in (or create an account).
2. Add a little credit (the **Billing** page) — a play session costs cents, not
   dollars, but Anthropic requires a balance to use the API.
3. Open **API Keys**, create a new key, and copy it. It looks like
   `sk-ant-...`. Keep it private — it's tied to your account.

## 4. Play

1. **Double-click `play.bat`.** Your browser opens to the game.
2. Click **🔌 Connect your AI** on the start screen.
3. Make sure **Anthropic — Claude** is selected, paste your `sk-ant-...` key, and
   click **Save & connect**. You should see **● Claude Sonnet 5** at the top.
4. Click **New Game**, pick a world, and start telling the Phantom what you do.

Your key is saved **only on your computer** (never shared, never uploaded anywhere
but Anthropic) so you only paste it once.

**Offline Mode:** if you don't add a key, the game still runs — but the DM is a tiny
canned demo script, not the real AI. You'll see an **"Offline Mode"** banner reminding
you. It's fine for a quick look at the interface; connect a key for the actual game.

## 5. The Forge (optional)

`forge.bat` opens **The Forge**, the world-building tool — create your own towns,
characters, monsters, maps, and ambient sound. Not needed to play the shipped worlds;
explore it if you're curious.

---

## What I'd love your feedback on

You're not hunting for bugs (though shout if something breaks). I want a **taste
test** — your gut reactions as a longtime D&D player:

- **What helped?** Which features made it feel like a real game at the table?
- **What's missing?** What did you reach for that wasn't there?
- **What got in the way?** Anything clumsy, confusing, or that you'd cut?

Jot notes as you go — even half-formed reactions are gold. Thank you!
