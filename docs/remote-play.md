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

## Door 1 — cloudflared (recommended: free, no account, no router surgery)

A "quick tunnel": one small program on the host's machine that hands you a
temporary public https address and relays visitors to your local server.

1. Download `cloudflared.exe` (one file, no install):
   <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
2. Start hosting as usual (`host.bat`).
3. In a second terminal:

   ```
   cloudflared tunnel --url http://127.0.0.1:8000
   ```

4. It prints an address like `https://random-words.trycloudflare.com` —
   send that to your friends along with the join code. Done.

Notes:
- The address is new each run — fine for a game night, annoying for a
  standing campaign (Tailscale below is the standing-campaign answer).
- Traffic rides Cloudflare's network encrypted (https/wss); the streamed
  Arena works through it, browser clicks and all.
- The tunnel connects to your server from *inside* your machine, so even the
  Windows-firewall prompt is bypassed. (You may still see and allow it —
  harmless either way.)

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
