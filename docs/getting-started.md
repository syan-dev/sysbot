# Getting Started with SysBot

This guide takes you from a fresh machine to a working bot with your first custom tool.

There are **two ways to install**, and they are documented separately so you can pick one and follow it top to bottom:

- **[Quick Start — guided installer](#5-quick-start--guided-installer)** — one command runs a wizard that asks a few questions and sets everything up for you (including an optional background service). Best for most people. Every question is explained below.
- **[Manual installation — step by step](#6-manual-installation--step-by-step)** — you install the package, write the config file yourself, and run it. Best if you want full control or are scripting the setup.

Do **Sections 1–2 first** (they apply to both paths), then jump to whichever install path you prefer.

---

## 1. Prerequisites

| Requirement | Version | Install | Why |
|---|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) | Runs SysBot. On Windows, tick **"Add Python to PATH"** in the installer. |
| pip | any | bundled with Python | Installs the package. |
| Ollama *(optional)* | latest | [ollama.com](https://ollama.com) | Runs an LLM locally. Skip if you'll use OpenAI or another remote backend. |

Check Python is available:

```bash
python --version      # should print 3.11 or higher (try python3 on Linux/macOS)
```

---

## 2. Install Ollama and pull a model

Ollama runs the language model locally on your machine — no cloud, no API key. **Skip this section** if you plan to use OpenAI or another remote backend.

**Install Ollama:**

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# Windows — download and run the installer from:
# https://ollama.com/download
```

**Pull a model.** `llama3.2` is a small, capable starting point (~2 GB):

```bash
ollama pull llama3.2
```

**Verify Ollama is running:**

```bash
curl http://localhost:11434/
# should print: Ollama is running
```

> Pick a model that fits your hardware in [MODELS.md](../MODELS.md) (by GPU VRAM).
> Manage the Ollama server itself in [OLLAMA.md](../OLLAMA.md).

---

## 3. Get the code

Both install paths start from a local clone of the repository:

```bash
git clone https://github.com/syan-dev/sysbot.git
cd sysbot
```

Now choose **one** of the two paths below.

---

## 4. Which install path should I use?

| | Quick Start (wizard) | Manual installation |
|---|---|---|
| **Effort** | Answer a few prompts | Edit a YAML file yourself |
| **Config file** | Written for you | You copy and edit it |
| **Background service** | Optional, set up for you | You set it up later (see [SERVICE.md](../SERVICE.md)) |
| **Best for** | Most users, first-time setup | Power users, servers, automation |
| **Go to** | [Section 5](#5-quick-start--guided-installer) | [Section 6](#6-manual-installation--step-by-step) |

---

## 5. Quick Start — guided installer

Run the installer for your OS:

```bash
# Linux / macOS
bash scripts/install.sh
```

```powershell
# Windows (PowerShell)
.\scripts\install.ps1
```

> **Windows execution policy.** If PowerShell blocks the script with a red error, run it this way instead:
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts\install.ps1
> ```

The wizard installs the package, then asks the questions below. **Press Enter to accept the value shown in `[brackets]`** — the defaults are chosen so that just pressing Enter through everything gives you a working local CLI bot.

### 5.1 The wizard, question by question

Each prompt looks like `?  Question [default]:`. Here is every question you may see, what to type, and why it matters.

> **Menus are navigable.** For any multiple-choice question (LLM backend, messaging provider, Ollama model) you can move the highlight with the **↑/↓ arrow keys** and press **Enter** to confirm, or just **press the option's number**. The number-based instructions below still apply if you prefer typing. When the installer is run without an interactive terminal (e.g. piped input), it falls back to a plain "type a number" prompt.

#### Q1. "config.yaml already exists — overwrite with new settings?" `[y/N]`

- **Only appears if** you've installed before and a `config.yaml` is already present.
- **Type `n` (default)** to keep your existing settings and skip straight to the service step.
- **Type `y`** to start fresh and re-answer everything.
- *Why:* protects a config you may have hand-edited from being overwritten by accident.

#### Q2. "LLM Backend — Choice" `[1]`

```
  1) Ollama    — local, recommended (no API key needed)
  2) OpenAI    — cloud API
  3) vLLM      — self-hosted OpenAI-compatible server
  4) Custom    — any OpenAI-compatible endpoint
```

- **Type `1` (default)** if you installed Ollama in Section 2. This is the recommended local setup.
- **Type `2`** to use OpenAI's cloud models (you'll need an API key).
- **Type `3`** if you run a [vLLM](https://docs.vllm.ai) server.
- **Type `4`** for any other OpenAI-compatible endpoint (LlamaCpp server, LM Studio, a proxy, etc.).
- *Why:* this picks the `base_url`/`api_key` pair SysBot talks to. All backends use the same OpenAI-compatible protocol, so only these connection details change.

**Follow-up questions depend on the backend you chose:**

**If you chose `1) Ollama`:**

- The wizard runs `ollama list` for you and shows a **numbered menu of the models you already have installed** — just type the number to pick one (no need to remember exact names). The last entry, **"Pull a different model (enter a name)"**, lets you type any model id (e.g. `qwen3.5`, `gemma3:4b`) and the wizard runs `ollama pull` immediately so it's ready before SysBot starts.
- If **no models are installed yet**, the wizard offers to download one on the spot (default `llama3.2`).
- If the **Ollama CLI isn't found**, it falls back to asking for a model name to use once Ollama is available, and points you to [ollama.com](https://ollama.com).
- *The API key is set to `ollama` automatically — Ollama ignores it but the client requires a value.*

**If you chose `2) OpenAI`:**

- **"Model"** `[gpt-4o]` — an OpenAI model id such as `gpt-4o` or `gpt-4o-mini`.
- **"API key (sk-...)"** — paste your secret key from [platform.openai.com](https://platform.openai.com/api-keys). *This is stored in `config.yaml`, so keep that file private.*

**If you chose `3) vLLM`:**

- **"vLLM base URL"** `[http://localhost:8000/v1]` — where your vLLM server listens. Keep the default if it's local.
- **"Model"** `[meta-llama/Llama-3.2-8B-Instruct]` — the model id your vLLM server serves. *API key is set to `vllm` automatically.*

**If you chose `4) Custom`:**

- **"Base URL"** `[http://localhost:8000/v1]` — the full OpenAI-compatible endpoint, including `/v1`.
- **"Model"** `[llama3.2]` — the model id that endpoint expects.
- **"API key"** `[none]` — a key if the endpoint needs one, otherwise leave the default.

#### Q3. "Messaging Provider — Choice" `[1]`

```
  1) CLI       — terminal, no credentials needed
  2) Telegram
  3) Slack
```

- **Type `1` (default)** to chat in your terminal. Nothing else to configure — great for trying SysBot out.
- **Type `2`** to talk to your bot from Telegram.
- **Type `3`** to use it in Slack.
- *Why:* this decides where you message the bot from. You can change it later by editing `config.yaml` or passing `--provider`.

**Follow-up questions depend on the provider you chose:**

**If you chose `2) Telegram`:**

- **"Bot token (from @BotFather)"** — create a bot by messaging [@BotFather](https://t.me/BotFather) with `/newbot`; it gives you a token like `1234567890:ABC...`. Paste it here.
- **"Allowed Telegram user IDs, comma-separated (blank = allow everyone)"** — your numeric Telegram ID (find it via [@userinfobot](https://t.me/userinfobot)), e.g. `123456789`. **Leave blank to let anyone message your bot** — only do that for a public bot. *Why:* this is an allow-list so strangers can't drive your tools.

**If you chose `3) Slack`:**

- **"Bot token (xoxb-...)"** — the Bot User OAuth Token from your Slack app's **OAuth & Permissions** page.
- **"App token (xapp-...)"** — an app-level token with `connections:write`, used for Socket Mode.
- *See [Messaging Adapters](adapters.md#3-slack) for the exact Slack app setup steps.*

#### Q4. "Start SysBot automatically after reboot?" `[Y/n]`

- **Only appears for Telegram or Slack.** Those providers run in the background to poll for incoming messages, so they're installed as a service (systemd on Linux, launchd on macOS, Task Scheduler on Windows). The **CLI** provider is an interactive terminal session you start on demand — it installs no service, so this question is skipped entirely.
- **Type `y` (default)** to have the service start now and again on every boot/login.
- **Type `n`** to install the service but start it yourself when you want it.
- *Why:* a chat bot you message from your phone should be always-on; a terminal session shouldn't be a background daemon (it has no terminal to read from).

#### Q5. "Apply these settings?" `[Y/n]`

- The wizard prints a **summary** (model, provider, startup, config path). **Type `y`** to apply, or **`n`** to abort without changing anything.
- *Why:* a last chance to review before the installer writes files and starts the service.

### 5.2 What the wizard does for you

After you confirm, the installer:

1. Writes your answers to **`config.yaml`** in the repo root.
2. Installs the **`sysbot`** command.
3. **For Telegram/Slack only:** installs and starts a **background service** that restarts on failure and (if you chose auto-start) on reboot. For **CLI**, nothing is installed to run in the background — you start a chat with `sysbot --provider cli` when you want it.

When it finishes, your bot is configured — and already running if you set up a Telegram/Slack service. Continue to [Section 7](#7-have-your-first-conversation).

> Managing the background service (start/stop/logs) is covered in [SERVICE.md](../SERVICE.md).

---

## 6. Manual installation — step by step

Use this path if you'd rather not run the wizard. It does the same three things by hand: install the package, create a config, run it.

### 6.1 Install the package

```bash
# Standard install
pip install .

# …or a development install (adds pytest + ruff)
pip install -e ".[dev]"
```

Verify the command is available:

```bash
sysbot --help
```

> If you get "command not found", pip's scripts directory isn't on your `PATH`. See [SERVICE.md](../SERVICE.md#91-sysbot-command-not-found).

### 6.2 Create your config file

Copy the documented default and open it in an editor:

```bash
cp config/default.yaml config.yaml
```

Edit the parts that matter for your setup. The essentials:

```yaml
messaging:
  provider: cli                 # cli | telegram | slack

llm:
  base_url: "http://localhost:11434/v1"   # Ollama default
  model: "llama3.2"             # a model you've pulled (ollama list)
  api_key: "ollama"             # any non-empty string for Ollama/vLLM; real key for OpenAI

mcp:
  hot_reload: true              # reload tools/ when you save a .py file
```

To use **OpenAI** instead of Ollama, change three lines:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "sk-..."             # your real key — keep config.yaml private
```

For Telegram/Slack credentials and every available setting, see the [Configuration reference](configuration.md).

### 6.3 Run it

```bash
sysbot                          # uses ./config.yaml (or config/default.yaml)
sysbot --provider cli -v        # force CLI + verbose logging
sysbot -c /path/to/config.yaml  # use a config in another location
```

You can also override settings ad-hoc without editing the file:

```bash
sysbot --model qwen3.5 --base-url http://localhost:11434/v1
```

That's the manual install done — continue below.

---

## 7. Have your first conversation

Start a CLI session (if the service is already running, this just opens a second, interactive session):

```bash
sysbot --provider cli
```

Try a few things:

```
You: what is 2 + 2?
Bot: 4.

You: /help
Bot: Available commands — use /help to see this list

/get_system_info
  Return basic information about the current machine.

/disk_usage <path>
  Check how much free disk space is available at a given path

/ping <host>
  Ping a host to check connectivity and measure latency
...

You: what's the disk usage of /tmp?
Bot: The /tmp directory has 2.3 GB free out of 20 GB total (11% used).

You: /disk_usage path=/tmp
Bot: Path: /tmp
     Total: 20.0 GB   Free: 2.3 GB   Used: 11.0%
```

Notice the last two — one used the LLM to understand the question and pick the right tool, the other called the tool directly with `/` (no LLM involved).

> **Want the full usage guide?** [Using SysBot](usage.md) covers chatting vs. slash commands, passing arguments, confirmations, conversation history, and switching models on the fly.

---

## 8. Write your first tool

Create a new file in the `tools/` directory:

```python
# tools/hello.py
from sysbot.mcp import tool

@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}! Nice to meet you."
```

Save the file. SysBot hot-reloads it immediately — no restart needed.

```
You: /hello name=World
Bot: Hello, World! Nice to meet you.

You: say hello to Alice
Bot: Hello, Alice! Nice to meet you.
```

The tool is available both as a `/command` and through natural language.

---

## 9. Wrap a shell command as a tool

```python
# tools/ops.py
from sysbot.mcp import CLITool

df = CLITool(
    name="df",
    description="Show disk usage for a filesystem path",
    command="df -h {path}",
    params={"path": "Filesystem path to check"},
)
```

Again, save and it's live:

```
You: /df path=/
Bot: Filesystem      Size  Used Avail Use% Mounted on
     /dev/sda1       200G  155G   45G  78% /
```

---

## 10. Next Steps

| Topic | Where to look |
|---|---|
| Use it day to day (chat, slash commands, history) | [Using SysBot](usage.md) |
| All tool options (`confirm`, type hints, multiple tools per file) | [Writing Tools](writing-tools.md) |
| Set up Telegram or Slack in detail | [Messaging Adapters](adapters.md) |
| Change model, adjust history size, disable logging | [Configuration](configuration.md) |
| Run as a background service / auto-start on boot | [Installation & Service](../SERVICE.md) |
| Ship a standalone `sysbot.exe` to Windows users | [Building a Windows .exe](building-windows-exe.md) |
| Pick the best model for your hardware | [Model Comparison](../MODELS.md) |
