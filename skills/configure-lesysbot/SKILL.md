---
name: configure-lesysbot
description: Change any LeSysBot setting — where the config file lives, the full YAML reference (messaging, llm, tools, agent, dashboard, logging), environment-variable and CLI-flag overrides, and how to apply changes. Use when asked to "change a setting", "edit the config", "increase history", "turn off logging", "change the system prompt", or "where is config.yaml".
---

# Configure LeSysBot

## Which config file is active?

LeSysBot loads the **first** match:

1. Path given with `-c / --config`
2. `config.yaml` in the working directory
3. **`~/.lesysbot/config.yaml`** — the per-user home the installer writes (this
   is the one to edit on an installed setup; `LESYSBOT_HOME` relocates it)
4. `config.yaml` next to the executable (frozen `.exe` builds)
5. `config/default.yaml` in the repo
6. Built-in defaults (no file at all)

Relative paths inside the config (`mcp.tools_dir: ./tools`,
`logging.file: logs/…`, `dashboard.state_file`, `mcp.lock_file`) resolve
**next to the loaded config file** — so an installed setup uses
`~/.lesysbot/tools` and `~/.lesysbot/logs`, while a dev checkout with a local
`./config.yaml` stays inside the repo.

## Applying a change

```bash
$EDITOR ~/.lesysbot/config.yaml
systemctl --user restart lesysbot                          # Linux service
launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot    # macOS service
```

```powershell
Stop-ScheduledTask -TaskName LeSysBot; Start-ScheduledTask -TaskName LeSysBot  # Windows
```

CLI sessions just pick up the new config on the next launch.

## Full reference

```yaml
messaging:
  provider: cli              # cli | telegram | slack
  telegram:
    token: "YOUR_BOT_TOKEN"
    allowed_user_ids: []     # empty = allow EVERYONE; e.g. [123456789]
  slack:
    bot_token: "xoxb-..."
    app_token: "xapp-..."    # Socket Mode app token
  startup_notice:            # ping when the bot comes up (Telegram/Slack only)
    enabled: true            # for a service this doubles as a boot notification
    notify: []               # Telegram chat ids / Slack channel ids;
                             # Telegram falls back to allowed_user_ids when empty
    speedtest: true          # include internet speed (downloads speedtest_mb MB)
    speedtest_mb: 5

llm:
  base_url: "http://localhost:11434/v1"   # Ollama default
  model: "llama3.2"
  api_key: "ollama"          # real key for OpenAI; any string for Ollama/vLLM
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0             # seconds before an LLM request is abandoned

mcp:
  tools_dir: "./tools"       # where tool packages load from (anchored to config dir)
  hot_reload: true           # reload tools/ on any .py change
  # lock_file: tools.lock.json   # install provenance (repo, pinned commit)

agent:
  system_prompt: >
    You are a helpful assistant with access to tools. ...
  max_history: 50            # messages kept per user (system message not counted)
  max_tool_calls: 10         # max LLM → tool → LLM loops per user message

dashboard:
  enabled: false             # or run `lesysbot --dashboard`; needs the `dashboard` extra
  host: "127.0.0.1"          # localhost only, no auth — change deliberately
  port: 8765
  state_file: tool_state.json   # persisted disabled tools

logging:
  level: INFO                # DEBUG | INFO | WARNING | ERROR | CRITICAL
  file: logs/lesysbot.log      # plain-text log; null to disable
  trace_file: logs/traces.jsonl   # per-request JSON traces; null to disable
  when: midnight             # rotation: midnight | H | D | W0..W6 | S
  backup_count: 7            # rotated files kept, oldest deleted
```

Both log files rotate on time (date-suffixed, e.g. `lesysbot.log.2026-06-21`) so
neither grows unbounded. In interactive CLI the console only shows WARNING+
(the file still gets everything at `level`); the Telegram/Slack daemons honour
`level` on the console too. `-v` forces DEBUG.

## Environment-variable overrides

Any value: `LESYSBOT_` + key path with `__` as the nesting separator. Env vars
beat the config file:

```bash
LESYSBOT_LLM__MODEL=qwen3.5
LESYSBOT_LLM__BASE_URL=http://localhost:8000/v1
LESYSBOT_MESSAGING__PROVIDER=telegram
LESYSBOT_MESSAGING__TELEGRAM__TOKEN=1234567890:ABCDEFabcdef
LESYSBOT_AGENT__MAX_HISTORY=100
LESYSBOT_LOGGING__LEVEL=DEBUG
```

## CLI flags (beat env vars and the file)

| Flag | Overrides |
|---|---|
| `-c / --config PATH` | config file path |
| `-v / --verbose` | `logging.level` → DEBUG |
| `--provider cli\|telegram\|slack` | `messaging.provider` |
| `--model NAME` | `llm.model` |
| `--base-url URL` | `llm.base_url` |
| `--dashboard` | `dashboard.enabled` → true |
| `--port N` | `dashboard.port` (implies `--dashboard`) |

## Traces (`logs/traces.jsonl`)

One JSON line per user message: `ts`, `trace_id`, `user_id`, `input`, per-LLM
`turns` (model, ms, `tools` with name/args/result/ms), final `reply`,
`total_ms`. Slash commands aren't traced. Results truncate at 2000 chars.
Useful to audit what the LLM decided and where time went.

## Related

- LLM backend switching in detail: [switch-llm-backend](../switch-llm-backend/SKILL.md).
- Telegram/Slack credentials: [setup-messaging](../setup-messaging/SKILL.md).
- Restart/log commands per OS: [manage-service](../manage-service/SKILL.md).
