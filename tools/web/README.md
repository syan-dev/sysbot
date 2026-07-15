---
name: web
description: Fetch the text content of a URL
platforms: all
requires: []
---
# web

Fetch a URL and return its text. Cross-platform.

**Runs on:** Linux · macOS · Windows  ·  **Needs:** the `httpx` pip package

`httpx` is a Python dependency (not a PATH binary), so it isn't a `requires:`
entry. If it's missing, `/fetch_url` tells you to `pip install httpx`. See
`requirements.txt`.

## Tools
- `/fetch_url <url>` — first ~3000 chars of the response body.

## Copy-paste
Drop this `web/` folder into your `~/.sysbot/tools/`, run
`pip install -r web/requirements.txt`, and restart SysBot.
