# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, includes dev deps; [dev] pulls [all] = telegram+slack+dashboard)
pip install -e ".[dev]"
# NOTE: the `lesysbot` console script imports whatever `lesysbot` is installed. A stale
# NON-editable build in site-packages can shadow this repo, making code/tool edits
# (e.g. newly added tools) appear to do nothing — `/help` may even show no tools.
# Check with: python -c "import lesysbot; print(lesysbot.__file__)"  → must point here.
# Fix by re-running:  pip install -e .

# Run the bot (CLI mode — no messaging credentials needed)
lesysbot --provider cli --model llama3.2

# Run with verbose logging
lesysbot --provider cli -v

# Run against an explicit config (otherwise ~/.lesysbot/config.yaml is the installed default)
lesysbot -c ~/.lesysbot/config.yaml

# Install and manage tools (bare `lesysbot` still runs the bot; `tool` = alias)
lesysbot tools install owner/repo[/subdir][@ref]    # or a github.com URL
lesysbot tools list | info NAME | enable NAME | disable NAME | remove NAME

# Interactive setup wizard (config + service; scripts/install.{sh,ps1} exec this)
lesysbot setup [--repo PATH]

# Lint
ruff check lesysbot/

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

Three independent layers wired together by `Agent` in `lesysbot/core/agent.py`:

```
MessagingAdapter → Agent.handle(user_id, text) → LLMClient → ToolRegistry → reply
```

**Request flow:** Messages arrive at a `MessagingAdapter`, which calls `Agent.handle`. If the text starts with `/`, it's dispatched directly to `_handle_slash()` — the LLM is never called. Otherwise, the agent appends the message to the per-user `ConversationHistory`, calls `LLMClient.chat()` with all registered tool schemas, and if the LLM returns `tool_calls`, executes them and loops. Tool calls run in parallel via `asyncio.gather` unless any tool has `confirm=True/str`, in which case they run sequentially so each confirmation can be awaited.

### LLM (`lesysbot/llm/client.py`)

Single `AsyncOpenAI` client with a configurable `base_url`. Always streams (`stream=True`). `LLMClient.health()` is a non-streaming probe used by the dashboard: it times a `models.list()` call (5 s timeout override, not the 120 s chat timeout) and returns `{ok, latency_ms, base_url, model, model_available, models}` or `{ok: False, error, ...}`. Three optional callbacks flow from `CLIAdapter` through `Agent.handle` into the stream loop: `on_token` (answer text, `delta.content`), `on_reasoning` (`delta.reasoning_content`, for reasoning models that expose it), and `on_status` — emitted by `Agent.handle` itself, not the LLM: `"Thinking…"` before each LLM turn and `"Running <tool>…"` before executing tools. `on_reasoning`/`on_status` are keyword-only with `None` defaults on `Agent.handle`, so Telegram/Slack (which call `handler(user_id, text)` with no extras) are unaffected. All local backends (Ollama, vLLM, LlamaCpp) expose an OpenAI-compatible API, so no backend-specific code exists.

### Tool registry (`lesysbot/mcp/registry.py`)

Tools live in `tools/` in two layouts: **folder packages** — each subdirectory (e.g. `gpu-temp/`) is a self-contained, copy-paste tool with its own `README.md` + `tool.py` (the recommended, shareable form, like a Claude Skill) — and **loose `.py` files** dropped straight in `tools/` (quick local tools, still supported). At startup `ToolRegistry.load_directory()` imports every non-`_`-prefixed `.py` (loose files first, then each subdir via `_load_package()`) and scans their module attributes. Anything with `__tool_meta__` dict (set by `@tool`) or that is a `CLITool` instance is registered. With `hot_reload: true`, `watchfiles.awatch` (recursive) re-runs this on any `.py` change without restarting.

`load_directory()` inserts the resolved tools directory into `sys.path` (for loose files); `_load_package()` temporarily inserts each package's own directory so its files can `from _helpers import ...`. Because helpers are imported by their bare name (globally cached), `_drop_user_helpers()` evicts top-level `_`-prefixed **user** helper modules **both before and after** each package load — guarded by `_stdlib_dirs()` so stdlib/site `_`-modules (`_thread`, `_py_abc`, …) survive. That forces each package to re-import the `_helpers.py` sitting next to it, so a like-named helper cached from another package or tools dir can't shadow it (and package helper imports must stay at module top level — the package dir is on `sys.path` only during load). Package tool modules import under a unique `_lesysbot_tools.<folder>.<stem>` name. On `reload()`, `_invalidate_cached_modules()` drops any cached `sys.modules` entry whose `__file__` lives under the tools dir (plus `importlib.invalidate_caches()`), so edits to helpers hot-reload too.

**Enable/disable:** the registry tracks a `_disabled` set (names turned off via the dashboard). `is_enabled`/`enable`/`disable`/`set_enabled` mutate it; `get_openai_schemas()` omits disabled tools (hidden from the LLM) and `call()` refuses them with a "disabled" message (so `/slash` calls respect it too). The set is an instance attr so it survives `reload()` (hot-reload); `set_state_path()`/`load_state()`/`_save_state()` persist it as `{"disabled": [...]}` JSON to `dashboard.state_file` (anchored like `tools_dir` → `~/.lesysbot/tool_state.json`) across restarts. `tool_status()` returns the per-tool dashboard rows (`enabled`, `available`, `unavailable_reason`, `platforms`, `requires`, `confirm`, `params`, `source`).

**Source mapping & removal:** `register()` records each tool's defining file as `meta["source"]` (passed down from `_load_file`), and `load_directory()` remembers the resolved tools dir. `tool_source(name)` maps a tool back to its removable unit — the folder package directly under the tools dir, or the loose `.py` itself — as `{path, kind: "package"|"file", unit, tools}` where `tools` lists every registered tool sharing the unit (one file/package can define several). `remove_tool(name)` deletes that unit (`force_rmtree` from `core/paths.py`, shared with the installer), deregisters all its tools, purges them from `_disabled` (state saved), and refuses paths that aren't a direct child of the tools dir. Callers keep `tools.lock.json` in sync via `install/lockfile.py:drop_entries()` when the removed unit was installed from GitHub. Both the dashboard (`POST /api/tools/{name}/remove`) and `lesysbot tools remove` go through this; tools registered programmatically (no `source`) return `None`/raise.

**Cross-platform gating:** `register()` calls `availability(platforms, requires)` (`lesysbot/mcp/platform.py`) once per tool. `platforms` (subset of `{linux, macos, windows}`, `None` = all) is checked against `current_os()`; `requires` is a list of executables checked via `shutil.which`. If unavailable the tool is **still registered** (visible in `/help` and to the LLM) but its `fn` is swapped for `_make_stub()`, which returns a one-line explanation when called; `meta["available"]`/`["unavailable_reason"]` are recorded and `list_tools_text()` appends a `⚠ unavailable here:` note. Pip deps are **not** `requires` (those are PATH binaries) — tools import them and handle `ImportError` themselves (see `tools/web/tool.py`).

**Important:** `CLITool.__tool_meta__` is a `@property` (not a plain attribute like `@tool`), which is why `_is_tool()` uses `isinstance(obj, CLITool)` as a separate branch from checking `__tool_meta__` on callables.

### `@tool` decorator (`lesysbot/mcp/decorators.py`)

Sets `fn.__tool_meta__` as a plain dict `{name, description, parameters, fn, confirm, platforms, requires}`. The `parameters` field is a JSON schema built from Python type hints via `_build_schema`. `platforms`/`requires` (both `None` by default) drive the registry's cross-platform gating described above. Type hint → JSON type mapping covers `str/int/float/bool/list/dict`; anything else defaults to `"string"`. Both sync and async functions are supported; sync functions are wrapped in `async def`.

`_build_schema` resolves hints via `typing.get_type_hints()` (not raw `func.__annotations__`), so tool files that use `from __future__ import annotations` (PEP 563 string annotations) still get correctly typed schemas instead of everything collapsing to `"string"`.

The `confirm` field (`bool | str`) propagates all the way to `Agent.handle`, which checks it before calling `adapter.confirm(user_id, tool_name, prompt, args)`. Set `confirm=True` for a generic prompt or pass a string for a custom message.

### `CLITool` (`lesysbot/mcp/cli_tool.py`)

Wraps a shell command template string (`command="ping -c 3 {host}"`) as a tool. Uses `str.format(**kwargs)` for interpolation. `command` may also be a dict keyed by OS name (`linux`/`macos`/`windows`) — `_run` executes the current OS's variant, and `__tool_meta__` derives `platforms` from the dict keys unless set explicitly, so the tool gates itself off where it has no command. All params in `params={}` are treated as required strings. Has its own `timeout` (default 30 s) and the same `platforms`/`requires` gating fields as `@tool` (surfaced through its `__tool_meta__` property).

### Config (`lesysbot/core/config.py`)

`Settings.load()` tries, in order: CLI `-c` flag → `config.yaml` (cwd) → `~/.lesysbot/config.yaml` → `config.yaml` next to the executable (frozen builds) → `config/default.yaml` → `app_dir()/config/default.yaml` → hardcoded defaults. String values may reference environment variables as `${VAR}` — expanded at load time by `_expand_env()` (unset vars keep the literal text and log a warning). All fields are also overridable via `LESYSBOT_` env vars with `__` as the nested delimiter (e.g. `LESYSBOT_LLM__MODEL=llama3.1`); env vars and CLI flags take precedence over the file. To customize by hand, copy `config/default.yaml` to `config.yaml` (or edit `~/.lesysbot/config.yaml`).

`from_yaml()` records the loaded file's absolute path on a `PrivateAttr`; `Settings.config_dir` exposes its directory (or `None` when running on built-in defaults). The two `config/default.yaml` candidates are loaded with `bundled=True`: they ship **with the package**, not as a config the user edits, so their values apply but `config_dir` stays `None` — otherwise a fresh checkout would anchor `./tools` to `<repo>/config/tools` and load no tools at all (`tests/test_config.py::test_bundled_default_does_not_anchor_paths_to_itself`). This is what lets relative `tools_dir`/log paths anchor next to the config the user actually edits — see **Paths** below.

### Paths & the `~/.lesysbot` home (`lesysbot/core/paths.py`)

`~/.lesysbot/` is the **installed per-user home** — one stable place for `config.yaml`, `tools/` and `logs/`, decoupled from wherever the source was cloned. The install wizard writes `config.yaml` and seeds `tools/` there, and the Telegram/Slack background service runs from it, so the supported workflow is: **edit `~/.lesysbot/config.yaml`, restart the service, done.**

- `user_dir()` → `~/.lesysbot`, overridable with the `LESYSBOT_HOME` env var (also used to make tests hermetic).
- `app_dir()` → the cwd normally, or the folder containing the executable in a frozen (PyInstaller) build.
- `anchor(path, base=None)` resolves a relative path against `base`, falling back to `app_dir()` when `base is None`; absolute paths pass through unchanged.

`config.resolve_paths(settings)` anchors `mcp.tools_dir`, `mcp.lock_file`, `logging.file`/`logging.trace_file`, and `dashboard.state_file` against `settings.config_dir` (the directory the active config came from). It's called from `__main__.main()` on the bot path **and** from `mcp/cli.py:run()`, so `lesysbot tools install` writes into exactly the tools dir the bot loads. An installed setup resolves `./tools` → `~/.lesysbot/tools` and `logs/…` → `~/.lesysbot/logs`; a dev checkout with a local `./config.yaml`, or a shipped `.exe` with config beside it, keeps resolving them next to that config; and built-in defaults — including the bundled `config/default.yaml` — fall back to `app_dir()`. See `docs/configuration.md`, `docs/building-windows-exe.md` and `packaging/`.

### Messaging (`lesysbot/messaging/`)

Each adapter implements `MessagingAdapter.start(handler)` and `send(user_id, text)`. The optional `confirm()` method defaults to auto-approve; CLI and Telegram override it. Adapters are imported lazily in `__main__.py` so missing optional deps (Telegram, Slack) don't break CLI usage. Wire new adapters in the `if/elif` block in `__main__.py` and call `agent.set_confirm_fn(adapter.confirm)`.

**CLI adapter** renders LLM answers as **live Markdown** (color/bold/headings/lists/code) by accumulating `on_token` chunks into a `rich.live.Live` + `Markdown`. While generating it shows a `Thinking…` / `Running <tool>…` spinner (driven by `on_status`); reasoning — from `on_reasoning` or inline `<think>…</think>` tags split out by `_split_think()` — renders dim above the answer. **Slash-command/instant results and `/help` are still printed verbatim** (`markup=False`): Markdown would strip `<param>` signatures and collapse column whitespace (e.g. `df`); a status spinner runs while they execute. `confirm()` pauses the active `Live` (`self._live.stop()` then `.start()`) so the confirmation prompt renders cleanly. `_format_history` uses plain `LABEL:` lines, not `**bold**`.

**Startup notice (`lesysbot/messaging/notice.py`):** with Telegram/Slack and `messaging.startup_notice.enabled` (default true), `__main__._run` spawns `send_startup_notice()` as a background task. It waits on the adapter's `ready` event (a lazily created `asyncio.Event` on `MessagingAdapter`; Telegram sets it after `start_polling()`, Slack before the blocking `start_async()` since `send()` uses the Web API), builds `core/sysinfo.startup_report()`, and `send()`s it to `startup_notice.notify` (Telegram falls back to `allowed_user_ids`; Slack needs an explicit channel id), retrying failed sends. For an installed service this is the "machine just booted" ping. `core/sysinfo.py` holds the best-effort collectors — CPU temp (Linux `/sys` thermal zones + hwmon), GPU temp (nvidia-smi), disk usage, internet speed (Cloudflare, `speedtest`/`speedtest_mb` config keys), uptime — each returning `None` when the host can't answer, so the report omits those lines. It deliberately does **not** call registered tools (must work regardless of tools-dir contents); the bundled `cpu-temp`/`gpu-temp`/`speedtest` packages duplicate the readings for chat, on purpose (packages stay copy-paste self-contained).

**Out-of-band pushes (`lesysbot/core/notify.py`):** tools normally only *return* text, so they can't say anything after their reply. `Agent.handle` stamps the requesting user on a `ContextVar` before dispatch (slash and LLM paths) and `__main__._run` wires the active adapter's `send` via `notify.set_sender`, so a tool can call `notify_later(text, delay)` (re-exported from `lesysbot.mcp`) to push a follow-up message to that user. It returns the `asyncio.Task` (cancel it to drop the announcement) or `None` when no sender/user is wired — best-effort by design; send failures are logged, not raised. The `power` package uses it for a "powering off now" heads-up ~10 s before a scheduled shutdown/reboot fires, cancelled again by `cancel_shutdown`.

**Telegram adapter** targets python-telegram-bot v20+ (no `Updater.idle()` — `start()` awaits an `asyncio.Event` and shuts the app down on cancel). Replies go through `_reply_safe()`, which tries `parse_mode="Markdown"` and falls back to plain text on `BadRequest`, so malformed LLM Markdown never drops a message.

**Optional dependencies:** only the CLI provider, the registry and the `tools`/`setup` subcommands are in the base install. Chat platforms and the dashboard are extras — `telegram` (`python-telegram-bot`), `slack` (`slack-bolt` **plus `aiohttp`**, which slack-bolt itself does not declare but its async socket handler imports), `dashboard` (`aiohttp`), and `all` (all three; `dev` pulls `all`). `scripts/install.{sh,ps1}` install `.[all]` so every option the wizard offers works. `_run()` wraps the lazy adapter imports in one `try/except ImportError` that names the missing extra instead of dumping a traceback — for a background service that message is the user's only clue. CI's `base-install` job installs bare `.`, asserts `telegram`/`slack_bolt`/`aiohttp` are absent, and smoke-tests the CLI, so the base install can't silently regain a heavy dep.

### Dashboard (`lesysbot/dashboard/server.py`)

Optional local web UI to manage tools and check LLM health, enabled via `--dashboard`, `--port N` (sets `dashboard.port` and implies `--dashboard`), or `dashboard.enabled` (`DashboardConfig`: `host`/`port`/`state_file`). If the configured port is taken, `start()` walks forward up to 10 consecutive ports (warning logged; `Dashboard.port` records what was actually bound) and gives up with a logged error rather than crashing the background task. `Dashboard(agent, settings).start()` builds an **aiohttp** app (`aiohttp` is an optional dep — the `dashboard` extra; the import is guarded with a friendly message) via `_make_app()` (factored out so tests can drive the routes with `aiohttp.test_utils`) serving `GET /` (one self-contained inline HTML page, no build step/CDN), `GET /api/status` (`{provider, model, llm: health(), tools: registry.tool_status()}`), `GET /api/llm/health`, `POST /api/tools/{name}/toggle` (flips `registry.set_enabled`, persisted), and `POST /api/tools/{name}/remove` (`registry.remove_tool` + install-lock cleanup; the UI's Remove button `confirm()`s with the exact path and any sibling tools that go with it). It reads the registry and LLM via the `Agent.registry`/`Agent.llm` properties.

**Tools CLI (`lesysbot/mcp/cli.py`):** `lesysbot tools install|list|info|enable|disable|remove` (`tool` is an argparse alias) — the whole tool lifecycle without a running bot, registered in `build_parser()` (each leaf repeats `-c` with `default=argparse.SUPPRESS` so a root-level `-c` isn't clobbered) and dispatched in `main()` before any bot setup. `install` accepts **GitHub links only** (`owner/repo[/subdir][@ref]` or a github.com URL — a bare word gets a usage error) and hands a parsed `ToolSource` to `ToolInstaller`. The other verbs build a real `ToolRegistry` over the resolved `tools_dir` (imports tool code, as the bot does); `list`/`info` join registry rows with the lock for provenance (`origin` = `repo@commit7` or `local`); enable/disable persist to `dashboard.state_file` (a running bot picks that up on restart — the dashboard applies it live); `remove` confirms y/N (`--yes` skips) before `registry.remove_tool()` + `drop_entries()` lock cleanup; a running bot's hot reload notices deletions immediately.

**Single-instance guard (`lesysbot/core/singleton.py`):** two copies of the same bot fight over the same updates (Telegram 409s both), so for remote providers `main()` takes an OS-level lock (flock / msvcrt byte lock on `user_dir()/lesysbot.<provider>.<token-digest>.lock`) before starting and exits 1 with a "stop the service first" message when it's held, naming the holder's PID from the lock file. Keyed on a token digest so different bots coexist; the kernel drops the lock on process exit (crash included) so stale files never wedge a restart; CLI provider skips the guard (doesn't poll). Held handles stay referenced in a module-global so GC can't release them. Tests: `tests/test_singleton.py` (subprocess-based, hermetic via `LESYSBOT_HOME`).

**Concurrency pattern (`__main__._run`):** the messaging adapter is the **primary** coroutine; the dashboard and the startup notice run as `asyncio.create_task` **background** tasks. Tools only ever run in response to a user message or `/command` — there is deliberately no scheduler or other unattended trigger (the startup notice reports via `core/sysinfo.py` collectors, not tools). `await adapter.start(...)` in a `try`, and the `finally` cancels the background tasks (`await asyncio.gather(*background, return_exceptions=True)`). This is what lets a CLI `exit` actually terminate the process — the dashboard's `await asyncio.Event().wait()` would otherwise keep `gather` alive forever. Binds `127.0.0.1`, no auth (documented in `docs/dashboard.md`).

### Tracing (`lesysbot/core/trace.py`)

`TraceWriter` appends one JSON line per user message to the resolved `logging.trace_file` (default `logs/traces.jsonl`, anchored to the config dir — so `~/.lesysbot/logs/traces.jsonl` for an installed setup). Slash commands aren't traced — they return before `_tracer.start()`. It writes through a dedicated non-propagating logger backed by a `TimedRotatingFileHandler`, so traces rotate on `logging.when` and keep `logging.backup_count` dated files. `ActiveTrace` accumulates per-LLM-turn and per-tool-call timings during a single `Agent.handle()` call, then flushes on `finish()`. Tracing has no levels — it's all-or-nothing per message; `result`/`reply` are truncated at 2000 characters.

### Logging (`lesysbot/__main__.py`)

`_setup_logging(verbose, log_cfg, interactive)` attaches a Rich console handler plus a **`TimedRotatingFileHandler`** on the resolved `logging.file` that rotates per `logging.when` (default `midnight`) and keeps `logging.backup_count` dated files (e.g. `lesysbot.log.2026-06-21`) — neither file grows unbounded. The baseline level is `logging.level` (wired here; `-v` forces DEBUG). Root sits at DEBUG so each handler filters independently: the **file** logs at the config level, while the **console** is clamped to `WARNING+` in interactive CLI mode (keeps the chat clean — no `httpx`/`watchfiles`/`Tools loaded` INFO) and honours the config level for the Telegram/Slack daemons. `main()` passes `interactive=(settings.messaging.provider == "cli")`. Set `logging.file`/`logging.trace_file` to `null` to disable either.

### Tool installer (`lesysbot/install/`)

The engine behind `lesysbot tools install`: fetches **tool folder packages from GitHub** into the same `tools_dir` the bot loads (hot reload activates them live). There is deliberately **no registry/catalog concept** — installs are by GitHub link only, and the CLI (`mcp/cli.py`) calls `Settings.load()` + `config.resolve_paths()` so it writes into exactly the tools dir the bot resolves.

Module layout: `spec.py` parses `owner/repo[/subdir][@ref]` + GitHub URLs into a frozen `ToolSource`; `fetch.py` downloads **codeload zipballs via stdlib urllib** (no git binary, no GitHub API calls — candidate order tries `refs/tags/` before `refs/heads/`; `GITHUB_TOKEN`/`GH_TOKEN` sent as a Bearer header for private repos); `archive.py` extracts with zip-slip/symlink/zip-bomb guards and reads the pinned commit SHA from the **zip archive comment**; `meta.py` parses README frontmatter (the only frontmatter parser in the codebase — optional, never blocks an install) and discovers packages (root-with-`.py` = single-package repo, else immediate subdirs — of `tools/` when that folder yields any, else of the root; package code is **never imported** pre-consent); `manager.py` (`ToolInstaller`) stages extraction to a temp dir then `shutil.move`s each package in (one clean hot-reload event) and records provenance in `tools.lock.json` via `lockfile.JsonState` (root key `LOCK_KEY = "tools"`; atomic write, corrupt → `.bad` backup). The lock path is `mcp.lock_file`, anchored to the config dir like `tools_dir`.

Installer rules: y/N confirmation before install (`--yes` skips; tool packages are arbitrary code), refuse overwriting folders not in the lock (`--force` to overwrite; installer-seeded bundled tools count as "unmanaged"), and `requirements.txt` prints the pip command instead of running it (`--install-deps` opts in). `ToolInstaller` **only installs**: reading back what's installed is `lesysbot tools list/info` (registry rows joined with the lock), and removal is `registry.remove_tool()` + `lockfile.drop_entries()`. One path each, so there is never a second source of truth about the tools dir. Tests (`tests/test_install_*.py`) are network-free via `tests/install_utils.py`: `make_github_zip` builds GitHub-shaped zipballs (incl. comment SHA) and `FakeFetcher` records requested URLs so tests can assert the candidate fallback order. Docs: `docs/installing-tools.md` (user guide, trust model), `docs/sharing-tools.md` (author guide).

## Adding a new tool

Create a **folder package** `tools/<name>/` with a `README.md` (frontmatter: name, description, platforms, requires) and a `tool.py`. Use `@tool` for Python logic or `CLITool` for shell commands. Declare `platforms=[...]`/`requires=[...]` when a tool isn't universal (gating is enforced; the README mirrors it for humans). Files starting with `_` are ignored — use a package-local `_helpers.py` for shared utilities (`from _helpers import ...`; the package dir is on `sys.path`). A loose `.py` in `tools/` still works for quick local tools. The `.claude/skills/add-tool/` project skill and `tools/README.md` (the catalog) encode this — prefer the skill when scaffolding a tool. For a bundled package, also add a row to the `tools/README.md` catalog table; the README frontmatter takes an optional `version:` that `lesysbot tools list/info` displays.

```python
# tools/find-files/tool.py
from lesysbot.mcp import tool, CLITool

@tool(description="Search files by pattern", confirm="This will scan the filesystem — proceed?")
async def find_files(pattern: str, directory: str = ".") -> str:
    import glob
    return "\n".join(glob.glob(f"{directory}/**/{pattern}", recursive=True))

df = CLITool(
    name="df",
    description="Show disk usage",
    command="df -h {path}",
    params={"path": "Filesystem path"},
    platforms=["linux", "macos"],   # omit for all OSes; requires=[...] gates on PATH binaries
)
```

The package is hot-reloaded on save when `mcp.hot_reload: true` (default). For an installed setup, the live tools dir is `~/.lesysbot/tools/`; for a dev checkout it's the repo's `tools/`.

## Adding a new messaging adapter

Subclass `MessagingAdapter` (`lesysbot/messaging/base.py`) and implement `start()` and `send()`. Override `confirm()` to add confirmation UI (default auto-approves). Wire it in the `if/elif` block in `lesysbot/__main__.py` and pass `adapter.confirm` to `agent.set_confirm_fn`.

## LLM backend switching

All backends accept the same config shape — only `base_url`, `model`, and `api_key` differ:

| Backend | base_url | api_key |
|---|---|---|
| Ollama | `http://localhost:11434/v1` | `ollama` |
| vLLM | `http://localhost:8000/v1` | `vllm` |
| OpenAI | `https://api.openai.com/v1` | actual key |

## Tests

`tests/` holds the pytest suite (`test_registry.py`, `test_decorators.py`, `test_agent.py`, `test_config.py`, `test_llm_health.py`, `test_sysinfo.py` (startup-report collectors over a fake `/sys` tree and fake fetcher), `test_startup_notice.py` (recipient resolution + send flow over a fake adapter), `test_notify.py` (out-of-band pushes: user stamping via `Agent.handle`, delayed send, cancellation), `test_tool_manage.py` (source mapping + removal), `test_cli_tools.py` (`lesysbot tools …` grammar/dispatch over a real temp tools dir, incl. the install subcommand via a stubbed `ToolInstaller`), `test_dashboard_api.py` (routes via `aiohttp.test_utils`, `importorskip`-guarded), `test_setup_wizard.py` (the `lesysbot setup` step chain via a scripted FakeUI — see the setup-wizard section), plus the installer suite: `test_install_{spec,archive,meta,lockfile,fetch,manager}.py`). They construct registries/agents over temp tool dirs and don't need a running LLM, messaging backend, or network. `test_config.py` covers the search order and the `~/.lesysbot` home via a monkeypatched `LESYSBOT_HOME` (`test_load_picks_up_user_dir`) plus `config_dir` tracking and `resolve_paths` anchoring. Installer tests share `tests/install_utils.py`: `make_github_zip()` builds GitHub-shaped zipballs (single `repo-ref/` root + commit SHA in the archive comment) and `FakeFetcher` serves them from a dict while recording requested URLs (used to assert the zipball candidate fallback order); hermeticity comes from the same `LESYSBOT_HOME` monkeypatch. `asyncio_mode = "auto"` means async tests need no decorator.

## Setup wizard (`lesysbot/setup/`) and install scripts (`scripts/install.{sh,ps1}`)

The install scripts are **bootstrap only**: check Python ≥3.11, `pip install ".[all]"` (so Telegram/Slack/dashboard all work), locate the `lesysbot` binary, then hand off to **`lesysbot setup --repo <checkout>`** (bash `exec`s it; ps1 forwards `$LASTEXITCODE`; `-NoService` skips the hand-off). The wizard itself is **one cross-platform Python implementation** in `lesysbot/setup/`, shared by every OS. `lesysbot setup` also runs standalone at any time to reconfigure an existing install (without `--repo` it skips tools seeding). It writes `config.yaml` and seeds `tools/` into **`~/.lesysbot/`** (`user_dir()`, overridable via `LESYSBOT_HOME`) and points the service's `WorkingDirectory` there; `tools_dir`/log paths stay relative in the written config and anchor to `~/.lesysbot` at load time; an existing `~/.lesysbot/tools` is never clobbered. `scripts/uninstall.{sh,ps1}` still offer to remove `~/.lesysbot`.

Module layout — `ui.py`: Rich-panel widgets (`InteractiveUI.menu/text/confirm_yn`) rendered in a transient `Live` that leaves a one-line `❯ label · answer` echo behind; `read_key()` reads **raw bytes from the stdin fd via `os.read` inside a `raw_mode()` (cbreak) context held for the whole widget** — per-keypress termios toggling loses queued bytes to the canonical line buffer (fast typing/paste kept only the first char), and `sys.stdin` readahead hides bytes from `select()`, desyncing escape parsing. Escape sequences are collected byte-by-byte with a 0.25 s timeout and whole CSI sequences are slurped so Home/Del/F-keys can't leak. `PlainUI` is the no-terminal fallback (numbered "type a number" menus via `input()`, EOF → default + `eof` flag); `make_ui()` picks by `isatty`. `wizard.py`: `WizardState` dataclass + the step chain (`step_llm`/`step_messaging`/`step_autostart` + `run_steps`, `step_summary`) and the Ollama picker. `apply.py`: config template, tools seeding, per-OS service setup/stale-cleanup (Windows via PowerShell `ScheduledTask` cmdlets), epilogue; service functions take a `runner` param so tests record instead of touching the host. `cli.py`: argparse wiring + the top-level flow; dispatched in `__main__.main()` before the tools CLI.

- **Navigation contract**: ↑/↓ move, Enter/→ confirm, number keys jump; when a menu has a "← …" entry, ←/Esc confirms it directly (inert otherwise); Esc at a text prompt returns `None` and the step loops re-show that step's menu with answers intact. The summary is a menu (Apply / Change LLM backend / Change how to reach LeSysBot / Change startup behaviour (service only) / Quit); nothing is written until Apply. Revisited steps offer previous answers as defaults — except LLM follow-ups, cleared when the backend choice changes. The kept-config path (existing config not overwritten) has no chain — just y/N service + apply questions.
- **Messaging step is framed as "How to reach LeSysBot"**: option 1 is the terminal (default → `provider: cli`); Telegram/Slack are additive remote channels. A **background service (systemd/launchd/Task Scheduler) is installed only for Telegram/Slack** (`WizardState.needs_service`). Telegram requires a non-empty allow-list — the IDs loop re-asks until valid, and in `PlainUI` mode aborts (`SetupAborted`) when piped input runs dry (`ui.eof`). The wizard ends with a provider-aware "How to use" epilogue that names `lesysbot setup` for reconfiguring.
- **Stale-service cleanup on the CLI path**: `apply.remove_stale_service*` detects a leftover Telegram/Slack service and offers to stop & remove it; the service path instead stops-and-replaces + `restart`s so a changed config actually takes effect.
- **No sudo, ever**: the wizard never uses sudo — "Enter through the prompts" must stay password-free. Root-requiring setup lives with the tools that need it: the optional `shutdown-wake` package (lesysbot-linux-tools-official; not bundled) ships a `setup-sudoers.sh` that writes the narrow `rtcwake` rule (`/etc/sudoers.d/lesysbot-rtcwake`). `uninstall.sh` still offers to delete that rule if present.

Tests: `tests/test_setup_wizard.py` drives the chain through a scripted `FakeUI` (navigation, defaults preservation, backend-switch clearing, Telegram validation/EOF, summary jumps), plus config/seeding round-trips and service functions via a recording runner (hermetic through `LESYSBOT_HOME`/`HOME` monkeypatching). Every prompt is documented in `docs/getting-started.md`. Naming note: `lesysbot/setup/` is the *install wizard*; `lesysbot/install/` is the *tool installer* — unrelated modules.

## Documentation structure

Docs are deliberately **top-down (overview → detail) and step-by-step**, organized as a journey: understand → install → use → extend → operate → contribute. All guides live in `docs/` (the root keeps only `README.md`, `CONTRIBUTING.md`, and this file): `docs/README.md` is the index/reading order; `docs/architecture.md` is the human-oriented counterpart to this file (life of a message, layer detail, where-to-change-what); `docs/models.md` covers model choice + Ollama basics; `docs/service.md` covers background-service operation (install/uninstall themselves live in `docs/getting-started.md` — don't re-document them elsewhere); `CONTRIBUTING.md` holds dev setup + per-change-type checklists. When changing behaviour, update the guide that documents it; when adding a page, slot it into `docs/README.md` and the README's documentation table. Keep early sections of every page self-sufficient, push internals toward the end, and cross-link rather than repeat — each fact has one home (tool management commands: `docs/usage.md` §9).

`skills/` holds **agent-facing skills** (Claude Skill format, one `SKILL.md` per job) distilled from the docs so an AI agent can operate/extend LeSysBot without reading `docs/` or source — deliberately copyable as a unit, so unlike the docs it *duplicates* facts. The mapping mirrors the docs (`docs/configuration.md` ↔ `skills/configure-lesysbot/`, `docs/service.md` ↔ `skills/manage-service/`, …; `skills/README.md` is the routing index). When a behaviour change updates a doc page, update the matching skill too. (`.claude/skills/` is separate: project skills for working *on this repo* in Claude Code.)

This repo is also a **Claude Code plugin marketplace** (`.claude-plugin/marketplace.json` + the `lesysbot-tool-dev` plugin in `claude-plugin/`): it distributes a repo-agnostic `add-tool` skill to tool authors in *other* repos — the official tools collections commit a `.claude/settings.json` (`extraKnownMarketplaces`/`enabledPlugins`) so cloners get prompted to install it (docs: `docs/claude-code.md`). The plugin is deliberately unversioned (every push is a new version). When tool-package conventions change, update **both** `.claude/skills/add-tool/` (core-repo variant) and `claude-plugin/lesysbot-tool-dev/skills/add-tool/` (generalized variant — no relative doc links, no `tools/`-dir or catalog/tests assumptions).

## Packaging (Windows .exe)

`packaging/` (PyInstaller `lesysbot.spec` + `entry.py`) and `scripts/build-exe.ps1` build a standalone `lesysbot.exe`. The spec bundles core deps and optionally Telegram/Slack/httpx (skipped if absent). Frozen builds rely on `lesysbot/core/paths.py`: `app_dir()` resolves `config.yaml`/`tools/`/`logs/` next to the executable, and `Settings.load()` still checks `~/.lesysbot/config.yaml` ahead of the exe-adjacent file. Full guide: `docs/building-windows-exe.md`. Build artifacts (`build/`, `dist/`, `.build-venv/`) are git-ignored.
