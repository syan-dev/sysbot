# SysBot

A local AI assistant you can chat with via CLI, Telegram, or Slack — extended by tools you drop into a folder.

Runs entirely on your machine with [Ollama](https://ollama.com). No cloud required.

---

## 1. Features

- **Chat with a local LLM** — Ollama, vLLM, LlamaCpp, or OpenAI
- **Extend with tools** — drop a `.py` file in `tools/` and it's live; no restart needed
- **Use tools without the LLM** — call any tool directly with `/tool_name args`
- **Three messaging adapters** — CLI terminal, Telegram, Slack
- **Confirmation prompts** — mark a tool `confirm=True` to require approval before it runs
- **Structured traces** — every request logged to `logs/traces.jsonl` for debugging

---

## 2. Quick Start

**1. Install Ollama and pull a model**

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
```

See [OLLAMA.md](OLLAMA.md) for macOS/Windows and [MODELS.md](MODELS.md) to pick the right model for your GPU.

**2. Install SysBot** — pick one of two paths:

**Path A — guided installer (recommended).** A wizard asks which model and messaging provider to use and whether to auto-start on boot, then writes `config.yaml` and starts SysBot for you. **Just press Enter to accept the defaults** for a working local CLI bot.

```bash
bash scripts/install.sh        # Linux / macOS
```
```powershell
.\scripts\install.ps1          # Windows (PowerShell)
```

Every prompt — including the backend- and provider-specific follow-ups — is explained in [Getting Started → the wizard, question by question](docs/getting-started.md#51-the-wizard-question-by-question).

**Path B — manual install.** Install the package, write your own config, and run it:

```bash
pip install .
cp config/default.yaml config.yaml      # then edit model / provider
sysbot --provider cli
```

Full step-by-step for both paths: [Getting Started](docs/getting-started.md).

**3. Start chatting**

Step 2 already started SysBot for you. If it isn't running (or you closed it), launch it again:

```bash
sysbot --provider cli
```

You'll see the welcome banner and can start chatting:

```
SysBot — local AI assistant with tools
Type a message to chat, or use /commands directly. Type 'exit' to quit.

You: what's the disk usage on /?
Bot: The root filesystem has 45 GB free out of 200 GB total (78% used).

You: /disk_usage path=/tmp
Bot: Path: /tmp   Total: 20.0 GB   Free: 2.3 GB   Used: 11.0%
```

---

## 3. Run it with different settings

Every setting can be supplied three ways, in increasing priority: **`config.yaml`** → **`SYSBOT_*` env vars** → **CLI flags**. The examples below use whichever is most convenient — see [Configuration](docs/configuration.md) for the full matrix.

**Default — Ollama, local, CLI chat:**

```bash
sysbot --provider cli --model llama3.2
```

**Use a different local model (one-off, no config edit):**

```bash
sysbot --model qwen3.5            # must be pulled first: ollama pull qwen3.5
```

**OpenAI instead of Ollama:**

```bash
export SYSBOT_LLM__BASE_URL=https://api.openai.com/v1
export SYSBOT_LLM__API_KEY=sk-...
sysbot --model gpt-4o
```

**vLLM (self-hosted OpenAI-compatible server):**

```bash
sysbot --base-url http://localhost:8000/v1 --model meta-llama/Llama-3.2-8B-Instruct
```

**LlamaCpp server:**

```bash
sysbot --base-url http://localhost:8080/v1 --model llama
```

**Run on Telegram (after putting your bot token in `config.yaml`):**

```bash
sysbot --provider telegram
```

**Run on Slack:**

```bash
sysbot --provider slack
```

**Point at a specific config file:**

```bash
sysbot -c /etc/sysbot/config.yaml
```

**Verbose logging (DEBUG) to see tool calls and LLM requests:**

```bash
sysbot -v
```

**Tweak agent behaviour without touching the file:**

```bash
SYSBOT_AGENT__MAX_HISTORY=100 SYSBOT_AGENT__MAX_TOOL_CALLS=5 sysbot
```

| Backend | `--base-url` | `--model` (example) | API key |
|---|---|---|---|
| Ollama (default) | `http://localhost:11434/v1` | `llama3.2` | `ollama` |
| vLLM | `http://localhost:8000/v1` | `meta-llama/Llama-3.2-8B-Instruct` | `vllm` |
| LlamaCpp | `http://localhost:8080/v1` | `llama` | `llama` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` | `sk-...` |

---

## 4. Documentation

**Start here**

| Guide | Description |
|---|---|
| [Getting Started](docs/getting-started.md) | Install (guided or manual) → first conversation → first tool |
| [Using SysBot](docs/usage.md) | How to chat, run tools, slash commands, history — the day-to-day guide |

**Connect a chat app**

| Guide | Description |
|---|---|
| [Messaging Adapters](docs/adapters.md) | Full CLI / Telegram / Slack setup — creating the bot, tokens, user IDs |

**Extend & configure**

| Guide | Description |
|---|---|
| [Writing Tools](docs/writing-tools.md) | `@tool` decorator, `CLITool`, confirmation prompts, hot reload |
| [Configuration](docs/configuration.md) | Full `config.yaml` reference, environment variables, CLI flags |

**Run & operate**

| Guide | Description |
|---|---|
| [Installation & Service](SERVICE.md) | Background service, auto-start on boot — Linux, macOS, Windows |
| [Building a Windows .exe](docs/building-windows-exe.md) | Ship a standalone `sysbot.exe` to end users — no Python required |
| [Ollama Reference](OLLAMA.md) | Managing Ollama models and the server |
| [Model Comparison](MODELS.md) | Recommended models by GPU VRAM |

---

## 5. Built-in Commands

These work in every adapter (CLI, Telegram, Slack):

| Command | What it does |
|---|---|
| `/help` | List all registered tools with their signatures |
| `/clear` | Clear your conversation history |
| `/history` | Show recent messages |
| `/tool_name arg` | Call a tool directly — no LLM involved |

See **[Using SysBot](docs/usage.md)** for the full guide — natural language vs. slash commands, passing arguments, confirmations, and history.

---

## 6. Contributing

1. Fork the repo and create a branch.
2. Add your tool in `tools/` or your adapter in `sysbot/messaging/`.
3. Run `ruff check sysbot/` and `pytest` before opening a PR.

See [CLAUDE.md](CLAUDE.md) for architecture notes aimed at AI coding assistants.

---

## 7. License

MIT
