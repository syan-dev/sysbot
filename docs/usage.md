# Using SysBot

Once SysBot is installed and running, this guide shows you how to actually use it day to day — chatting, running tools, and the built-in commands.

Everything here works the same in **CLI, Telegram, and Slack**. The examples use the CLI because it needs no setup; for adapter-specific setup (tokens, user IDs) see [Messaging Adapters](adapters.md).

---

## 1. Start a session

If your `config.yaml` already sets `provider: cli`, just run:

```bash
sysbot
```

Or force the CLI explicitly (handy if your config is set to Telegram/Slack):

```bash
sysbot --provider cli
```

You'll see a banner and a prompt:

```
SysBot — local AI assistant with tools
Type a message to chat, or use /commands directly. Type 'exit' to quit.

You:
```

> Already running SysBot as a background service (Telegram/Slack)? You can still open a separate interactive CLI session anytime with `sysbot --provider cli` — they don't conflict.

---

## 2. Two ways to interact

There are two distinct ways to talk to SysBot, and knowing the difference is the key to using it well:

| | **Natural language** | **Slash command** (`/...`) |
|---|---|---|
| Example | `what's my disk usage on /?` | `/disk_usage path=/` |
| Who handles it | The **LLM**, which decides whether to call a tool | The tool runs **directly** — the LLM is never involved |
| Needs a model running | Yes | **No** |
| Speed | Depends on the model | Instant |
| Best for | Questions, multi-step requests, anything conversational | Running a known tool exactly, quick checks, when the LLM is offline |

Both reach the same tools — they're just two front doors.

---

## 3. Chatting with the LLM

Type a normal sentence and press Enter. The CLI gives you a Claude-Code-like experience:

- A **`Thinking…` spinner** appears while the model works, switching to **`Running <tool>…`** when it calls a tool.
- The reply **streams live** and is **rendered as Markdown** — headings, **bold**, bullet lists, and `code` show with color and formatting instead of raw `##`/`**` symbols.
- If the model exposes its **reasoning** (some "thinking" models do, e.g. via `<think>` tags), it's shown dimmed above the answer.

```
You: what operating system is this machine running?
Bot: This machine is running Linux 6.8.0. (via get_system_info)

You: and how much free space is on / ?
Bot: The root filesystem has 143 GB free out of 980 GB (80% used).
```

> The background `httpx`/tool-watcher log lines don't interrupt the chat — they're written to `logs/sysbot.log` instead. Run with `-v` to see them (and DEBUG detail) on screen.

SysBot **remembers the conversation** within a session, so follow-up questions like "and how much free space…" work without repeating context. See [§7 Conversation history](#7-conversation-history) for the details and limits.

---

## 4. Built-in commands

These special commands are handled by SysBot itself (not the LLM) and work in every adapter:

| Command | What it does |
|---|---|
| `/help` *(or `/tools`)* | List every registered tool with its parameters |
| `/clear` | Forget the conversation so far and start fresh |
| `/history` | Show the recent messages in this conversation |
| `exit` / `quit` / `q` | Leave the CLI (CLI only) |
| `Ctrl+C` | Force-exit immediately (CLI only) |

`/help` output looks like this:

```
You: /help
Available commands — use /help to see this list

/get_system_info
  Return basic information about the current machine.

/disk_usage <path>
  Check how much free disk space is available at a given path

/fetch_url <url>
  Fetch the text content of a URL
```

In a tool's signature, `<angle>` means **required** and `[square]` means **optional**.

---

## 5. Running tools directly with `/`

Slash commands let you run a tool precisely, without the LLM. There are two ways to pass arguments:

**Positional** — values fill the parameters in order:

```
You: /fetch_url https://example.com
You: /disk_usage /
```

**Named** — `key=value`, in any order (clearer for multi-argument tools):

```
You: /disk_usage path=/tmp
```

**Values with spaces** — wrap them in quotes:

```
You: /search query="weekly report" folder=/docs
```

**If you miss a required argument**, SysBot shows you the usage instead of failing:

```
You: /disk_usage
Missing required parameter(s): path

Usage: /disk_usage <path>
  Check how much free disk space is available at a given path
```

**If you mistype a command**, it points you to `/help`:

```
You: /diskusage /
Unknown command: /diskusage
Available commands — use /help to see this list
...
```

> Slash commands do **not** go through the LLM and are **not** added to your conversation history — they're stateless, one-shot calls. This makes them reliable even when no model is running.

---

## 6. Confirmation prompts

Some tools are marked to require approval before they run (anything destructive, like deleting files or rebooting). The confirmation guards **LLM-initiated** calls — when the model decides to run such a tool, SysBot asks you first:

```
⚠ Confirmation required
  Tool : delete_logs
  directory = '/var/log/myapp'
  This will permanently delete log files — are you sure?
Proceed? [y/n] (n):
```

Press `y` to run it, anything else to cancel. In **Telegram** this appears as ✅/❌ buttons; in **Slack** it auto-approves by default. See [Messaging Adapters](adapters.md) and [Writing Tools → confirmation](writing-tools.md#3-requiring-confirmation).

> **Direct `/` calls skip the prompt.** When *you* type `/delete_logs ...` yourself, you've already made the decision, so it runs immediately. The confirmation exists to catch the *LLM* acting on your behalf — not to second-guess an explicit command.

---

## 7. Conversation history

- SysBot keeps a separate history **per user**, seeded with the system prompt from `config.yaml`.
- Only **natural-language** messages and the model's replies are stored — slash commands are not.
- Old messages are trimmed once the history passes `agent.max_history` (default 50); the system prompt is always kept. Tune it in [Configuration](configuration.md).
- `/history` shows what's currently remembered; `/clear` wipes it and starts over.

```
You: /clear
Conversation history cleared.
```

---

## 8. Switching model or backend on the fly

You don't have to edit `config.yaml` for a quick change — CLI flags and environment variables override it:

```bash
sysbot --model qwen3.5                     # different local model (pull it first)
sysbot --base-url https://api.openai.com/v1 --model gpt-4o   # talk to OpenAI
sysbot --provider telegram                 # run as the Telegram bot instead
SYSBOT_AGENT__MAX_HISTORY=100 sysbot       # env-var override
```

Precedence is **CLI flags → `SYSBOT_*` env vars → `config.yaml`**. The full list of flags and variables is in [Configuration](configuration.md).

---

## 9. Managing tools (enable / disable / remove)

Every installed tool can be managed from the terminal — no dashboard or running
bot needed. The commands act on the same state file and tools directory the bot
loads, so what you change here is what the bot sees:

```bash
sysbot tools install owner/repo  # install tool package(s) from a GitHub repo
sysbot tools list                # every tool: status, source package, origin
sysbot tools info gpu_temp       # details: params, platform gating, provenance
sysbot tools disable gpu_temp    # hide from the LLM; /gpu_temp refuses to run
sysbot tools enable gpu_temp     # turn it back on
sysbot tools remove gpu_temp     # DELETE its folder package / .py file (asks y/N)
```

- **disable/enable** is reversible and persisted (`tool_state.json`). A running
  bot applies it on its next restart; the [Dashboard](dashboard.md) applies it
  live instead.
- **remove** permanently deletes the tool's folder package (or loose `.py`) from
  the tools dir — including any other tools defined in the same package, which
  are listed before you confirm. An installed package's `tools.lock.json` entry
  is cleaned up too. A running bot with hot-reload drops it immediately.
- **install** fetches packages straight from a GitHub link — see
  [Installing Tools](installing-tools.md) for specs, pinning, and the trust
  model.

The same actions are available point-and-click in the [Dashboard](dashboard.md).

---

## 10. Where activity is logged

- `logs/sysbot.log` — plain-text application log (set `-v` for DEBUG detail).
- `logs/traces.jsonl` — one structured JSON line per request: which tools ran, with what arguments, and how long each step took. Great for debugging. Format is documented in [Configuration → traces](configuration.md#6-traces-log-format).

Disable either by setting its path to `null` in `config.yaml`.

---

## 11. Common issues

| Symptom | Cause & fix |
|---|---|
| `LLM unavailable: ...` | The backend isn't reachable. Check Ollama is running (`curl http://localhost:11434/`) and the model is pulled. Slash commands still work without a model. |
| Bot picked the wrong tool / didn't use one | Smaller models call tools less reliably. Try a stronger model (see [Models](models.md)) or call the tool directly with `/`. |
| First reply is slow | The model loads into memory on first use. Subsequent replies are faster. |
| A tool isn't in `/help` | Make sure its file is in `tools/`, doesn't start with `_`, and check the log for an import error. See [Writing Tools](writing-tools.md). |
| `model "x" not found` | Pull it first: `ollama pull x`, or fix `llm.model` in `config.yaml`. |

---

## Next steps

| Want to… | See |
|---|---|
| Set up Telegram or Slack | [Messaging Adapters](adapters.md) |
| Add your own tools | [Writing Tools](writing-tools.md) |
| Manage tools in a browser | [Dashboard](dashboard.md) |
| Change models, history, logging | [Configuration](configuration.md) |
| Run SysBot in the background | [Running as a Service](service.md) |
| Understand what happens under the hood | [Architecture](architecture.md) |
