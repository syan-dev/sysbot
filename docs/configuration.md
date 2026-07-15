# Configuration

SysBot is configured via a YAML file and optionally overridden by environment variables or CLI flags.

---

## 1. Config file

Copy the default config and edit it:

```bash
cp config/default.yaml config.yaml
```

SysBot looks for config in this order:
1. Path given with `-c / --config`
2. `config.yaml` in the working directory
3. `~/.sysbot/config.yaml` — the per-user home the installer writes to
4. `config.yaml` next to the executable (frozen `.exe` builds)
5. `config/default.yaml`
6. Built-in defaults (no file needed)

### `~/.sysbot/` — the installed home

`scripts/install.sh` / `install.ps1` write your settings to **`~/.sysbot/config.yaml`**
and seed **`~/.sysbot/tools/`** there, decoupled from wherever you cloned the source.
The background service (systemd/launchd/Task Scheduler) runs from this directory, so
this is the one place to edit and apply settings:

```bash
$EDITOR ~/.sysbot/config.yaml
systemctl --user restart sysbot     # Linux  (launchctl kickstart -k … on macOS)
```

Relative `mcp.tools_dir` (`./tools`) and `logging.file`/`trace_file` (`logs/…`) are
resolved against the directory the loaded `config.yaml` lives in — so for an installed
setup they point at `~/.sysbot/tools` and `~/.sysbot/logs`, and for a dev checkout with
a local `./config.yaml` they stay relative to the repo (unchanged). Set `SYSBOT_HOME`
to use a directory other than `~/.sysbot`.

---

## 2. Full reference

```yaml
# ── Messaging ──────────────────────────────────────────────────────────────────
messaging:
  provider: cli              # cli | telegram | slack

  telegram:
    token: "YOUR_BOT_TOKEN"
    allowed_user_ids: []     # empty = allow everyone
                             # e.g. [123456789, 987654321]

  slack:
    bot_token: "xoxb-..."
    app_token: "xapp-..."    # Socket Mode app token

# ── LLM ───────────────────────────────────────────────────────────────────────
llm:
  base_url: "http://localhost:11434/v1"   # Ollama default
  model: "llama3.2"
  api_key: "ollama"          # use your OpenAI key for OpenAI; any string for Ollama/vLLM
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0             # seconds before an LLM request is abandoned

# ── Tools ─────────────────────────────────────────────────────────────────────
mcp:
  tools_dir: "./tools"
  hot_reload: true           # watch tools/ and reload on any .py change

# ── Agent behaviour ───────────────────────────────────────────────────────────
agent:
  system_prompt: >
    You are a helpful assistant with access to tools.
    Use tools when they help answer the user's question.
    Be concise and clear.
  max_history: 50            # messages kept per user (system message not counted)
  max_tool_calls: 10         # max LLM → tool → LLM loops per user message

# ── Dashboard ─────────────────────────────────────────────────────────────────
dashboard:
  enabled: false             # or run `sysbot --dashboard`; needs `pip install aiohttp`
  host: "127.0.0.1"          # localhost only, no auth — change deliberately if exposing
  port: 8765                 # http://localhost:8765
  state_file: tool_state.json   # persisted disabled tools; anchored like tools_dir → ~/.sysbot/



# ── Logging ───────────────────────────────────────────────────────────────────
logging:
  level: INFO                # DEBUG | INFO | WARNING | ERROR | CRITICAL
  file: logs/sysbot.log      # plain-text log; null to disable
  trace_file: logs/traces.jsonl   # structured per-request JSON traces; null to disable
  when: midnight             # rotation interval: midnight | H | D | W0..W6 | S
  backup_count: 7            # keep this many rotated files, then delete oldest
```

Both `file` and `trace_file` rotate on time (Python's `TimedRotatingFileHandler`), so neither grows without bound: at each `when` rollover the current file is renamed with a date suffix (e.g. `sysbot.log.2026-06-21`) and only the newest `backup_count` are kept. `level` sets how much detail is written (and shown on the console for the Telegram/Slack daemons); `-v` forces `DEBUG`. In interactive CLI the console is always kept at `WARNING` or above so logs don't interrupt the chat — the file still gets everything at `level`.

---

## 3. LLM backends

All backends use the same OpenAI-compatible API — only `base_url`, `model`, and `api_key` differ:

| Backend | `base_url` | `api_key` |
|---|---|---|
| **Ollama** (default) | `http://localhost:11434/v1` | `ollama` |
| **vLLM** | `http://localhost:8000/v1` | `vllm` |
| **LlamaCpp server** | `http://localhost:8080/v1` | `llama` |
| **OpenAI** | `https://api.openai.com/v1` | your API key |

Example — switching to OpenAI:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "sk-..."
```

---

## 4. Environment variable overrides

Every config value can be set via an environment variable. The format is `SYSBOT_` + the key path with `__` as the nesting separator:

```bash
SYSBOT_LLM__MODEL=qwen3.5
SYSBOT_LLM__BASE_URL=http://localhost:8000/v1
SYSBOT_MESSAGING__PROVIDER=telegram
SYSBOT_MESSAGING__TELEGRAM__TOKEN=1234567890:ABCDEFabcdef
SYSBOT_AGENT__MAX_HISTORY=100
SYSBOT_LOGGING__LEVEL=DEBUG
```

Environment variables take precedence over `config.yaml`.

---

## 5. CLI flags

```
sysbot [-c CONFIG] [-v] [--provider PROVIDER] [--model MODEL] [--base-url URL] [--dashboard]
sysbot tools …           # install/list/enable/disable/remove tools — see docs/installing-tools.md
```

| Flag | Overrides | Example |
|---|---|---|
| `-c / --config` | config file path | `-c /etc/sysbot/config.yaml` |
| `-v / --verbose` | `logging.level` → DEBUG | `-v` |
| `--provider` | `messaging.provider` | `--provider telegram` |
| `--model` | `llm.model` | `--model qwen3.5` |
| `--base-url` | `llm.base_url` | `--base-url http://localhost:8000/v1` |
| `--dashboard` | `dashboard.enabled` → true | `--dashboard` |

CLI flags take precedence over environment variables and `config.yaml`.

---

## 6. Traces log format

When `logging.trace_file` is set, each user message produces one JSON line:

```json
{
  "ts": "2026-06-21T12:00:00+00:00",
  "trace_id": "ab29aaf98c9b",
  "user_id": "cli-user",
  "input": "what is my disk usage?",
  "turns": [
    {
      "index": 1,
      "model": "llama3.2",
      "messages": 3,
      "response_type": "tool_calls",
      "ms": 840.0,
      "tools": [
        {"name": "disk_usage", "args": {"path": "/"}, "result": "...", "ms": 42.5}
      ]
    },
    {
      "index": 2,
      "model": "llama3.2",
      "messages": 5,
      "response_type": "text",
      "ms": 620.0,
      "tools": []
    }
  ],
  "reply": "Your disk at / is 80% full with 40 GB free.",
  "total_ms": 1460.0
}
```

Useful for measuring latency, debugging tool calls, and auditing what the LLM decided to do.
