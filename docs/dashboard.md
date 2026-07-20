# Dashboard

A small **local web dashboard** to manage LeSysBot at a glance: see every tool with
its status, enable/disable or remove tools, and check whether the LLM backend is
healthy. It runs alongside the bot in any provider mode (CLI, Telegram, Slack).
Everything here can also be done from the terminal with `lesysbot tools …`
([Using LeSysBot §9](usage.md#9-managing-tools-enable--disable--remove)).

```
http://localhost:8765
┌──────────────────────────────────────────────┐
│ ✅ LLM backend reachable · 42 ms               │
│    http://localhost:11434/v1 · model llama3.2  │
│ ─────────────────────────────────────────────  │
│ /speedtest                                     │  Disable
│ /gpu_temp     ⚠ requires 'nvidia-smi' …        │  Disable
│ /reboot       confirm                  disabled│  Enable
└──────────────────────────────────────────────┘
```

## Install & launch

The dashboard needs the optional `aiohttp` dependency:

```bash
pip install ".[dashboard]"       # already included by scripts/install.{sh,ps1}
```

Then start the bot with `--dashboard`:

```bash
lesysbot --provider cli --dashboard
# → 📊 Dashboard: http://127.0.0.1:8765

lesysbot --provider cli --port 9000    # pick the port (implies --dashboard)
# → 📊 Dashboard: http://127.0.0.1:9000
```

If the port is already taken, the dashboard moves to the next free one (it tries
up to 10 consecutive ports) and logs a warning — the `📊 Dashboard:` line always
shows the URL actually being served.

Or turn it on in `config.yaml` so it's always served:

```yaml
dashboard:
  enabled: true
  host: "127.0.0.1"   # localhost only, no auth
  port: 8765
  state_file: tool_state.json   # persists disabled tools (relative → ~/.lesysbot/)
```

It runs as a background service beside the messaging adapter — when the CLI session
ends (or a daemon is stopped) the dashboard shuts down with it.

## What it shows

**LLM health banner** — probes the backend's `/models` endpoint (5 s timeout):
- ✅ reachable, with round-trip latency;
- whether your configured `model` is present in the backend's list;
- ❌ with the error if the backend is unreachable.

**Tools table** — every registered tool with:
- **enabled/disabled** state and a toggle button;
- **availability** — gated tools show why they can't run here (wrong OS, missing
  binary), mirroring `/help`;
- tags for `platforms`, required executables (`requires`), and `confirm`.

## Enabling / disabling tools

Click **Disable** to turn a tool off. A disabled tool:
- is **hidden from the LLM** (removed from the function schemas), so the model can't
  call it;
- **refuses direct `/tool` calls**, returning a "disabled" message;
- still appears in the dashboard and `/help` (marked disabled) so you can turn it
  back on.

Choices are **persisted** to `state_file` (`~/.lesysbot/tool_state.json` for an
installed setup) and survive restarts and hot-reloads.

## Removing tools

Click **Remove** to delete a tool from the tools directory — the whole folder
package (e.g. `~/.lesysbot/tools/gpu-temp/`), or the loose `.py` file for a quick
local tool. The confirmation dialog shows exactly which path will be deleted and,
if the package defines several tools, which other tools go with it.

- Removal is **permanent** — the files are deleted, not just disabled. If you may
  want a tool back later, disable it instead (or reinstall it afterwards with
  `lesysbot tools install`).
- If the package was installed by `lesysbot tools install`, its entry in
  `tools.lock.json` is cleaned up too, so `lesysbot tools list` stays accurate.
- With `hot_reload` on (the default) the running bot drops the tool immediately.

## Managing tools from the CLI

Everything above is also available without the dashboard (or a running bot)
via `lesysbot tools list|info|enable|disable|remove|install`, acting on the same
state file and tools dir — see
[Using LeSysBot §9](usage.md#9-managing-tools-enable--disable--remove).
`enable`/`disable` from the CLI apply on the bot's next restart, whereas the
dashboard applies them live.

## API

The page is backed by a tiny JSON API you can script against:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/status` | `{provider, model, llm: <health>, tools: [...]}` |
| `GET` | `/api/llm/health` | LLM backend health only |
| `POST` | `/api/tools/{name}/toggle` | flip a tool on/off, returns its new row |
| `POST` | `/api/tools/{name}/remove` | delete the tool's folder package / loose `.py`, returns `{removed, path}` |

## Security

The dashboard binds to **`127.0.0.1` with no authentication** — it's a single-user
local tool. Don't change `host` to a public interface unless you put it behind your
own auth/proxy; anyone who can reach the port can toggle tools. On a Telegram/Slack
server deployment it stays localhost-only unless you change `host`.
