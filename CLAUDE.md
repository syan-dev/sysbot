# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, includes dev deps)
pip install -e ".[dev]"

# Run the bot (CLI mode — no messaging credentials needed)
sysbot --provider cli --model llama3.2

# Run with verbose logging
sysbot --provider cli -v

# Lint
ruff check sysbot/

# Run tests
pytest

# Run a single test file
pytest tests/test_registry.py

# Run a single test
pytest tests/test_registry.py::test_tool_discovery

# Build a standalone Windows executable (run on Windows)
.\scripts\build-exe.ps1
```

`pytest` uses `asyncio_mode = "auto"` (set in `pyproject.toml`), so async test functions work without extra decorators.

## Architecture

Three independent layers wired together by `Agent` in `sysbot/core/agent.py`:

```
MessagingAdapter → Agent.handle(user_id, text) → LLMClient → ToolRegistry → reply
```

**Request flow:** Messages arrive at a `MessagingAdapter`, which calls `Agent.handle`. If the text starts with `/`, it's dispatched directly to `_handle_slash()` — the LLM is never called. Otherwise, the agent appends the message to the per-user `ConversationHistory`, calls `LLMClient.chat()` with all registered tool schemas, and if the LLM returns `tool_calls`, executes them and loops. Tool calls run in parallel via `asyncio.gather` unless any tool has `confirm=True/str`, in which case they run sequentially so each confirmation can be awaited.

### LLM (`sysbot/llm/client.py`)

Single `AsyncOpenAI` client with a configurable `base_url`. Always streams (`stream=True`). Three optional callbacks flow from `CLIAdapter` through `Agent.handle` into the stream loop: `on_token` (answer text, `delta.content`), `on_reasoning` (`delta.reasoning_content`, for reasoning models that expose it), and `on_status` — emitted by `Agent.handle` itself, not the LLM: `"Thinking…"` before each LLM turn and `"Running <tool>…"` before executing tools. `on_reasoning`/`on_status` are keyword-only with `None` defaults on `Agent.handle`, so Telegram/Slack (which call `handler(user_id, text)` with no extras) are unaffected. All local backends (Ollama, vLLM, LlamaCpp) expose an OpenAI-compatible API, so no backend-specific code exists.

### Tool registry (`sysbot/mcp/registry.py`)

At startup, `ToolRegistry.load_directory()` imports every non-`_`-prefixed `.py` file from `tools/` and scans their module attributes. Anything with `__tool_meta__` dict (set by `@tool`) or that is a `CLITool` instance is registered. With `hot_reload: true`, `watchfiles.awatch` re-runs this on any `.py` change without restarting.

`load_directory()` also inserts the resolved tools directory into `sys.path`, so tool files can import sibling helper modules with a plain `from _helpers import ...`. On `reload()`, `_invalidate_cached_modules()` drops any cached `sys.modules` entry whose `__file__` lives under the tools dir (plus `importlib.invalidate_caches()`), so edits to `_`-prefixed helpers are hot-reloaded too — not just the tool files themselves.

**Important:** `CLITool.__tool_meta__` is a `@property` (not a plain attribute like `@tool`), which is why `_is_tool()` uses `isinstance(obj, CLITool)` as a separate branch from checking `__tool_meta__` on callables.

### `@tool` decorator (`sysbot/mcp/decorators.py`)

Sets `fn.__tool_meta__` as a plain dict `{name, description, parameters, fn, confirm}`. The `parameters` field is a JSON schema built from Python type hints via `_build_schema`. Type hint → JSON type mapping covers `str/int/float/bool/list/dict`; anything else defaults to `"string"`. Both sync and async functions are supported; sync functions are wrapped in `async def`.

`_build_schema` resolves hints via `typing.get_type_hints()` (not raw `func.__annotations__`), so tool files that use `from __future__ import annotations` (PEP 563 string annotations) still get correctly typed schemas instead of everything collapsing to `"string"`.

The `confirm` field (`bool | str`) propagates all the way to `Agent.handle`, which checks it before calling `adapter.confirm(user_id, tool_name, prompt, args)`. Set `confirm=True` for a generic prompt or pass a string for a custom message.

### `CLITool` (`sysbot/mcp/cli_tool.py`)

Wraps a shell command template string (`command="ping -c 3 {host}"`) as a tool. Uses `str.format(**kwargs)` for interpolation. All params in `params={}` are treated as required strings. Has its own `timeout` (default 30 s).

### Config (`sysbot/core/config.py`)

`Settings.load()` tries: CLI `-c` flag → `config.yaml` (cwd) → `config.yaml` next to the executable → `config/default.yaml` → hardcoded defaults. All fields are also overridable via `SYSBOT_` env vars with `__` as the nested delimiter (e.g. `SYSBOT_LLM__MODEL=llama3.1`). To customize, copy `config/default.yaml` to `config.yaml`.

`sysbot/core/paths.py` resolves `config.yaml`, `tools/` and `logs/` relative to `app_dir()` — the current working directory normally, or the folder containing the executable in a frozen (PyInstaller) build. `__main__.main()` anchors the relative `tools_dir`/log paths through `anchor()` so a shipped `.exe` finds its files next to itself. See `docs/building-windows-exe.md` and `packaging/`.

### Messaging (`sysbot/messaging/`)

Each adapter implements `MessagingAdapter.start(handler)` and `send(user_id, text)`. The optional `confirm()` method defaults to auto-approve; CLI and Telegram override it. Adapters are imported lazily in `__main__.py` so missing optional deps (Telegram, Slack) don't break CLI usage. Wire new adapters in the `if/elif` block in `__main__.py` and call `agent.set_confirm_fn(adapter.confirm)`.

**CLI adapter** renders LLM answers as **live Markdown** (color/bold/headings/lists/code) by accumulating `on_token` chunks into a `rich.live.Live` + `Markdown`. While generating it shows a `Thinking…` / `Running <tool>…` spinner (driven by `on_status`); reasoning — from `on_reasoning` or inline `<think>…</think>` tags split out by `_split_think()` — renders dim above the answer. **Slash-command/instant results and `/help` are still printed verbatim** (`markup=False`): Markdown would strip `<param>` signatures and collapse column whitespace (e.g. `df`); a status spinner runs while they execute. `confirm()` pauses the active `Live` (`self._live.stop()` then `.start()`) so the confirmation prompt renders cleanly. `_format_history` uses plain `LABEL:` lines, not `**bold**`.

**Telegram adapter** targets python-telegram-bot v20+ (no `Updater.idle()` — `start()` awaits an `asyncio.Event` and shuts the app down on cancel). Replies go through `_reply_safe()`, which tries `parse_mode="Markdown"` and falls back to plain text on `BadRequest`, so malformed LLM Markdown never drops a message. **Slack** needs the optional `aiohttp` dependency (pulled in for the frozen build; install it manually for `--provider slack` from a plain `pip install`).

### Tracing (`sysbot/core/trace.py`)

`TraceWriter` appends one JSON line per user message to `logs/traces.jsonl` (slash commands aren't traced — they return before `_tracer.start()`). It writes through a dedicated non-propagating logger backed by a `TimedRotatingFileHandler`, so traces rotate on `logging.when` and keep `logging.backup_count` dated files. `ActiveTrace` accumulates per-LLM-turn and per-tool-call timings during a single `Agent.handle()` call, then flushes on `finish()`. Tracing has no levels — it's all-or-nothing per message; `result`/`reply` are truncated at 2000 characters.

### Logging (`sysbot/__main__.py`)

`_setup_logging(verbose, log_cfg, interactive)` attaches a Rich console handler plus a **`TimedRotatingFileHandler`** that rotates per `logging.when` (default `midnight`) and keeps `logging.backup_count` dated files (e.g. `sysbot.log.2026-06-21`) — neither file grows unbounded. The baseline level is `logging.level` (wired here; `-v` forces DEBUG). Root sits at DEBUG so each handler filters independently: the **file** logs at the config level, while the **console** is clamped to `WARNING+` in interactive CLI mode (keeps the chat clean — no `httpx`/`watchfiles`/`Tools loaded` INFO) and honours the config level for the Telegram/Slack daemons. `main()` passes `interactive=(settings.messaging.provider == "cli")`. Set `logging.file`/`logging.trace_file` to `null` to disable either.

## Adding a new tool

Drop a `.py` file in `tools/`. Use `@tool` for Python logic or `CLITool` for shell commands. Files starting with `_` are ignored — use `_helpers.py` for shared utilities and import them from a tool file with `from _helpers import ...` (the tools dir is on `sys.path`).

```python
from sysbot.mcp import tool, CLITool

@tool(description="Search files by pattern", confirm="This will scan the filesystem — proceed?")
async def find_files(pattern: str, directory: str = ".") -> str:
    import glob
    return "\n".join(glob.glob(f"{directory}/**/{pattern}", recursive=True))

df = CLITool(
    name="df",
    description="Show disk usage",
    command="df -h {path}",
    params={"path": "Filesystem path"},
)
```

The file is hot-reloaded on save when `mcp.hot_reload: true` (default).

## Adding a new messaging adapter

Subclass `MessagingAdapter` (`sysbot/messaging/base.py`) and implement `start()` and `send()`. Override `confirm()` to add confirmation UI (default auto-approves). Wire it in the `if/elif` block in `sysbot/__main__.py` and pass `adapter.confirm` to `agent.set_confirm_fn`.

## LLM backend switching

All backends accept the same config shape — only `base_url`, `model`, and `api_key` differ:

| Backend | base_url | api_key |
|---|---|---|
| Ollama | `http://localhost:11434/v1` | `ollama` |
| vLLM | `http://localhost:8000/v1` | `vllm` |
| OpenAI | `https://api.openai.com/v1` | actual key |

## Tests

`tests/` holds the pytest suite (`test_registry.py`, `test_decorators.py`, `test_agent.py`, `test_config.py`). They construct registries/agents over temp tool dirs and don't need a running LLM or messaging backend. `asyncio_mode = "auto"` means async tests need no decorator.

## Install scripts (`scripts/install.sh`, `scripts/install.ps1`)

The guided wizard for Linux/macOS (bash) and Windows (PowerShell). Both share the same UX, kept in sync:

- **Arrow-key menus** (`menu` / `Menu`): ↑/↓ + Enter, number keys jump, with a typed-number fallback when no interactive terminal is available. The bash version draws to `/dev/tty` (so it works inside `$(…)` capture) and gates interactivity on `[[ -t 2 ]]`.
- **Ollama-aware model picker** (`select_ollama_model` / `Select-OllamaModel`): lists installed models via `ollama list`, offers a "pull a different model" entry that runs `ollama pull`, prompts to download one if none exist, and falls back to a name prompt if the Ollama CLI is missing.
- **Messaging step is framed as "How to reach SysBot"**: option 1 is the terminal (default → `provider: cli`); Telegram/Slack are additive remote channels. A **background service (systemd/launchd/Task Scheduler) is installed only for Telegram/Slack** (`NEEDS_SERVICE` / `$NeedsService`) — the CLI adapter reads stdin and would exit immediately as a daemon. The wizard ends with a provider-aware "How to use" hint.

`install.sh` runs under `set -euo pipefail`, so menu arithmetic uses assignment forms (`i=$((i+1))`, `var=$(( … ))`) rather than `((i++))`/`(( var = … ))`, which return exit status 1 on a zero result and would abort the script. PowerShell can't be exercised in CI here — verify it by inspection. Every prompt is documented in `docs/getting-started.md`.

## Packaging (Windows .exe)

`packaging/` (PyInstaller `sysbot.spec` + `entry.py`) and `scripts/build-exe.ps1` build a standalone `sysbot.exe`. The spec bundles core deps and optionally Telegram/Slack/httpx (skipped if absent). Frozen builds rely on `sysbot/core/paths.py` to locate `config.yaml`/`tools/`/`logs/` next to the executable. Full guide: `docs/building-windows-exe.md`. Build artifacts (`build/`, `dist/`, `.build-venv/`) are git-ignored.
