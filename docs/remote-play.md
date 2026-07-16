# Hosting a table for remote friends

Multiplayer was built LAN-first, but the server doesn't care where a browser
is — a remote friend is a *reachability* problem, not a feature. Your machine
is the table; getting their browser to it takes one of the three doors below.
Everything else (the join code, seats, streamed combat, audio) works
identically over any of them.

Whichever door you pick, hosting itself is unchanged: run **host.bat**, read
the 5-letter join code off the header badge, and tell your friends the code
plus the address for that door. The code is the only lock — treat it like a
house key, share it in the group chat, not in public.

## Door 1 — the built-in internet door (recommended; it's automatic)

Setup fetches a small helper (`tools\cloudflared.exe`, a Cloudflare "quick
tunnel"). When you run **host.bat** and the helper is there, the game opens
the internet door by itself:

1. Run `host.bat`.
2. The header badge shows your join code and, a few seconds later, a 🌐
   internet address.
3. Click **📋 Invite** — the game copies
   `Join my Oubliette table: https://… — join code ABCDE`
   to your clipboard. Paste it into the group chat. That's the whole job.

Your friends click the link, enter the code and a name, pick their hero,
and they're at the table — nothing for them to install, ever.

Notes:
- The address is new each game night — the Invite button makes that a
  non-event. For a permanent address, see Tailscale below.
- Traffic rides Cloudflare's network encrypted (https/wss); the streamed
  Arena works through it, browser clicks and all.
- The tunnel connects to your server from *inside* your machine, so even
  the Windows-firewall prompt is bypassed. (You may still see and allow
  it — harmless either way.)
- Skipped the helper at setup, or the download failed? Run setup.bat again
  — or place `cloudflared.exe` in the game's `tools\` folder yourself.
  Without it, hosting simply stays LAN-only.

## Door 2 — Tailscale (best for a standing weekly table)

A private network between your machine and your friends' — everyone installs
Tailscale and signs into the same "tailnet" (free tier covers a game group).
Your machine gets a stable address like `100.x.y.z` that only they can reach.

1. Host and each remote player install Tailscale and join your tailnet
   (invite them from the admin page).
2. Run `host.bat`; allow the Windows-firewall prompt the first time.
3. Friends visit `http://<your-tailscale-ip>:8000` and enter the code.

Same address every week — "sit back down at your chair" extends all the way
to the URL. No traffic leaves the private network.

## Door 3 — router port forwarding (works, least recommended)

Forward an external port to your machine's `:8000` in your router's admin
page, and friends visit `http://<your-public-ip>:<port>`. It works, but:
your public IP changes unless you pay for a static one, router UIs are their
own dungeon crawl, and the port is open to the whole internet with the join
code as the only lock. If you go this way, host only while you're playing.

## What to expect over the internet

- **Story play is feather-light** — text and small JSON events. Any
  connection that can load a web page can sit at the table.
- **Streamed combat costs real upstream bandwidth**: each remote viewer
  costs the host up to ~1 MB/s while the board is animating (an idle board
  costs nothing — frames are only sent when pixels change). Two or three
  remote players is comfortable on a typical home upload; if someone's view
  chops, that's the built-in protection working — they get a lower frame
  rate, never a growing lag.
- **Audio is cheap**: each sound file is fetched once and cached; after
  that, cues are a handful of bytes.
- **A dropped connection heals itself**: the browser reconnects, the seat
  cookie holds the chair for a week, and a mid-fight refresh rejoins the
  board cold.

## When a friend can't get in

- **"Connection timed out" / a Cloudflare error page.** First look at your
  own header badge. If the 🌐 address is gone, the tunnel died (the helper
  crashed, the network hiccuped, the machine slept) — restart `host.bat`
  and send a **fresh** invite. If the badge still shows 🌐, the problem is
  on their side: have them try the same link from a phone on cellular.
  If the phone works, their network (some offices and schools) is blocking
  the tunnel.
- **The invite link only lives while host.bat runs**, and every restart
  mints a new one. Never re-send yesterday's link — click Invite again.
- **The host machine must stay awake.** While hosting, the game asks
  Windows not to sleep on its own — but closing a laptop lid still
  overrides that, and so does shutting down. The table lives and dies
  with your machine; that's what "the host IS the server" means.
- **A friend who drops mid-session just reopens the link** — their seat
  cookie holds their chair for a week, and a mid-fight refresh rejoins
  the streamed board cold.

## The security picture, honestly

- The join code is required before any API or the event channel answers, and
  it's shown only in the host's own browser — never to visitors, tunnelled
  or LAN. A guest must be *told* the code.
- The Arena stream and its click channel are gated by a per-run secret the
  browsers never see raw; a stranger who finds your URL can't watch or click.
- The DM API key never leaves the host's process. Remote players never see
  or need it — the host pays for the table's turns (one call per turn no
  matter how many players, so a full table costs the same as solo).
- Anyone seated can act for any hero, confirm any proposal, and end a fight
  — by design. The join code decides who's at the table; the social
  contract decides everything after that. Play with better friends.
