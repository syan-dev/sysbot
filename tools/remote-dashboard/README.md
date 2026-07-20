---
name: remote-dashboard
description: Launch a passcode-gated Gradio web dashboard (with public share link) to view/manage this machine remotely
platforms: all
requires: []
version: "1.2.0"
---
# remote-dashboard

Ask LeSysBot *"send me the dashboard link"* (or `/start_dashboard`) and it spins
up a **web dashboard** and replies with the link and a one-time passcode. By
default it also opens a public `*.gradio.live` share tunnel, so the page works
from anywhere — your phone on mobile data included — not just your home
network.

**Runs on:** Linux · macOS · Windows  ·  **Needs:** `gradio` (pip, see
requirements.txt); the public link needs internet access.

The link LeSysBot sends carries the passcode (`?t=…`), so opening it is one click
— there is no username, and nothing to type. The page:
- **Overview** — hostname/OS, uptime, then a stat tile per reading (CPU/GPU
  temperature, load, memory, disk) with a meter and a status band. Uses the
  same best-effort collectors as the startup notice, so readings the host
  can't answer are simply omitted. Auto-refreshes every 10 s.
- **Processes** — top 20 by CPU or memory, as a table with a share bar.
- **Logs** — tail of the LeSysBot log, 50–500 lines, with levels highlighted.

Under the tabs sits **Close dashboard** — shut the server down from the browser
when you're done, without going back to the chat. It asks for confirmation
first (it ends the session for every viewer, and only the chat can hand out a
new link), then leaves a goodbye panel and stops the page refreshing.

Status is never signalled by colour alone — every band carries an icon and a
word ("▲ Warm", "● Healthy"), so the page stays readable for colourblind
viewers and in grayscale.

## Look and feel
Gradio provides the server, the auto-refresh plumbing and the share tunnel, but
**every panel is hand-written HTML + CSS** (`_CSS` in `_app.py`) rather than
stock Gradio components. The stylesheet ships inline — there is no CDN and no
build step, deliberately: the LAN URL has to render on a network with no
internet access. Light and dark are both hand-picked (dark is its own set of
steps, not an inverted light), following the OS setting or Gradio's own theme
toggle.

## Tools
- `/start_dashboard [minutes] [public]` — launch and get link + passcode
  (LLM-initiated calls ask for confirmation first). `minutes` = auto-shutdown
  TTL, default 60 (5–720). `public=false` skips the share tunnel and gives a
  LAN-only URL. If it's already running you just get the current link again.
- `/dashboard_status` — is it up, link, passcode, time left.
- `/stop_dashboard` — shut it down now; the link and passcode die with it.
  (The page's own **Close dashboard** button does the same thing.)

## How it works / lifecycle
The server (`_app.py`) runs as a **detached process**, so it survives LeSysBot
restarts and tool hot-reloads. Its pid/port/passcode/URLs live in
`~/.lesysbot/remote_dashboard.json` (owner-only permissions); its log is
`~/.lesysbot/logs/remote-dashboard.log`. It shuts itself down when the TTL
expires, when the page's **Close dashboard** button is confirmed, when
`/stop_dashboard` is called, or when the state file no longer points at it.
LeSysBot pings you on the first two — the message says which happened, since a
link that died an hour early means something different from one that ran out.

## Security
- Every visit needs the random 10-char passcode before any page content is
  served; a fresh one is generated per launch. The server trades `?t=<passcode>`
  for an HttpOnly session cookie and redirects to the bare URL, so the passcode
  leaves the address bar (and the browser history, and any outgoing `Referer`);
  arriving without it gets a single passcode field, no username.
- The share link is a random `*.gradio.live` URL proxied over HTTPS; traffic
  passes through Gradio's tunnel servers. Use `public=false` if you only need
  LAN access (the local port binds all interfaces either way).
- The link + passcode go to whoever asked on the chat — so set
  `messaging.telegram.allowed_user_ids` in your config; with the default empty
  list, *anyone* who finds your bot could request a dashboard.
- Links expire: auto-shutdown after `minutes` (default 60).
- The Close button sits behind the same passcode gate as the rest of the page,
  so only someone you sent the link to can press it — and all it can do is end
  the session early.

## Copy-paste
Drop this `remote-dashboard/` folder into your `~/.lesysbot/tools/`, run
`pip install gradio`, and restart LeSysBot (or let hot-reload pick it up).
