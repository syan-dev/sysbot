# LeSysBot Documentation

The docs are organized **top-down** — start with the overview, drill into
detail as you need it. Each guide walks step by step through one job. Read in
order the first time; jump straight to a stage once you know your way around.

```
Understand  →  Install  →  Use  →  Extend  →  Operate  →  Contribute
```

---

## 1. Understand — what LeSysBot is and how it works

| Guide | Read it to… |
|---|---|
| [README](../README.md) | Get the 2-minute pitch: what LeSysBot does, quick start, feature list |
| [Architecture](architecture.md) | Follow a message through the system; learn the layers and where to change what |

## 2. Install — from a fresh machine to a running bot

| Guide | Read it to… |
|---|---|
| [Getting Started](getting-started.md) | Install (guided wizard or manual), have your first conversation, write your first tool — **the main on-ramp** |
| [Models](models.md) | Pick a local model for your hardware, manage it with Ollama, point LeSysBot at it |

## 3. Use — day-to-day

| Guide | Read it to… |
|---|---|
| [Using LeSysBot](usage.md) | Chat vs. slash commands, passing arguments, confirmations, history, managing tools, common issues |
| [Messaging Adapters](adapters.md) | Reach the bot from your terminal, Telegram, or Slack — full token/app setup |
| [Dashboard](dashboard.md) | Manage tools and check LLM health from a browser |

## 4. Extend — make it yours

| Guide | Read it to… |
|---|---|
| [Writing Tools](writing-tools.md) | Add abilities with `@tool` / `CLITool`: schemas, confirmation, cross-platform gating, hot reload |
| [Writing Tools with Claude Code](claude-code.md) | Let Claude scaffold tool packages via the `lesysbot-tool-dev` plugin, in any repo |
| [Installing Tools](installing-tools.md) | Install community tools from GitHub; the lock file and trust model |
| [Sharing Tools](sharing-tools.md) | Publish your tools from your own GitHub repo |
| [Configuration](configuration.md) | Every setting: `config.yaml` reference, `LESYSBOT_*` env vars, CLI flags |

## 5. Operate — keep it running

| Guide | Read it to… |
|---|---|
| [Running as a Service](service.md) | Run in the background, auto-start on boot, manage the service, read logs |
| [Building a Windows .exe](building-windows-exe.md) | Ship a standalone `lesysbot.exe` to users with no Python |

## 6. Contribute — improve LeSysBot itself

| Guide | Read it to… |
|---|---|
| [Contributing](../CONTRIBUTING.md) | Dev setup, tests, lint, and the step-by-step for each kind of contribution |
| [Architecture](architecture.md) | The map of the code you'll be changing |
| [CLAUDE.md](../CLAUDE.md) | Fine-grained internals, written for AI coding assistants but useful to anyone |

---

**Shortest paths for common goals**

- *"I just want to try it"* → [Getting Started §5](getting-started.md#5-quick-start--guided-installer) (press Enter through the wizard).
- *"I want it to do X"* → [Writing Tools](writing-tools.md), or install an existing tool from GitHub: [Installing Tools](installing-tools.md).
- *"I want to message it from my phone"* → [Adapters §2 Telegram](adapters.md#2-telegram).
- *"Something's wrong"* → [Using LeSysBot §11 Common issues](usage.md#11-common-issues), then `logs/traces.jsonl` ([format](configuration.md#6-traces-log-format)).
- *"I want to fix or add something"* → [Architecture](architecture.md) then [Contributing](../CONTRIBUTING.md).
- *"An AI agent is doing this for me"* → [skills/](../skills/README.md) — self-contained, copyable skills covering every job above (install, configure, switch backends, manage tools, develop) without needing these docs or the code.
