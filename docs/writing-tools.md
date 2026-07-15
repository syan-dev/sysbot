# Writing Tools

Tools are the heart of SysBot. The recommended form is a **folder package** — a
self-contained, copy-paste-shareable tool, like a Claude Skill:

```
tools/
  gpu-temp/                 # kebab-case folder = the package
    README.md               # human docs + frontmatter (name, description, platforms, requires)
    tool.py                 # @tool / CLITool definitions  (any non-_ .py is scanned)
    _helpers.py             # OPTIONAL shared helpers (underscore = never scanned)
    requirements.txt        # OPTIONAL pip deps
```

Drop a folder into `tools/` (or `~/.sysbot/tools/` for an installed setup) and it
auto-registers — no edits anywhere else. With `hot_reload: true` (the default),
changes take effect the moment you save.

The same folder shape is what `sysbot tools install owner/repo` downloads from
GitHub — push a package to a repo and anyone can install it (see
[installing-tools.md](installing-tools.md), and [sharing-tools.md](sharing-tools.md) for
sharing yours). The README frontmatter takes an optional `version: "1.0.0"`
field that `sysbot tools list/info` displays and records; bump it when you tag releases.

A **loose `.py` file** dropped straight into `tools/` also still works (default:
all OSes, no requirements) — handy for quick local tools. Files starting with `_`
are ignored, so use `_helpers.py` for shared utilities.

See `tools/README.md` for the shipped catalog. The sections below describe what
goes inside a package's `tool.py`.

---

## 1. Python tool — `@tool`

Use `@tool` for any logic you want to write in Python:

```python
# tools/weather.py
from sysbot.mcp import tool

@tool(description="Get the current weather for a city")
async def get_weather(city: str, units: str = "metric") -> str:
    # Call your API here
    return f"Sunny, 25°C in {city}"
```

That's it. SysBot builds the JSON schema from the type hints automatically.

### 1.1 Options

| Feature | How |
|---|---|
| Use docstring as description | Omit `description=` — the docstring is used instead |
| Sync functions | `def` works too; it's wrapped in `async` automatically |
| Optional parameter | Give it a default value: `units: str = "metric"` |
| Custom tool name | `@tool(name="weather")` — defaults to the function name |
| Require confirmation | `@tool(confirm=True)` or `@tool(confirm="Custom message")` |
| Limit to some OSes | `@tool(platforms=["linux", "macos"])` — see [§6](#6-cross-platform-support) |
| Require a binary on PATH | `@tool(requires=["nvidia-smi"])` — see [§6](#6-cross-platform-support) |

### 1.2 Supported type hints

| Python type | JSON schema type |
|---|---|
| `str` | `string` |
| `int` | `integer` |
| `float` | `number` |
| `bool` | `boolean` |
| `list` | `array` |
| `dict` | `object` |

Anything else defaults to `string`.

---

## 2. Shell command tool — `CLITool`

Use `CLITool` to wrap any shell command as a tool without writing Python logic:

```python
# tools/network.py
from sysbot.mcp import CLITool

ping = CLITool(
    name="ping",
    description="Check if a host is reachable and measure latency",
    command="ping -c 3 {host}",
    params={"host": "Hostname or IP address to ping"},
    timeout=15.0,
)
```

Parameters in `command` use Python's `str.format()` syntax — `{name}` is replaced with the value the LLM or user provides. All parameters in `params` are required.

| Option | Default | Description |
|---|---|---|
| `name` | — | Tool name (used in `/commands` and by the LLM) |
| `description` | — | What the tool does |
| `command` | — | Shell command with `{param}` placeholders |
| `params` | `{}` | Dict of `param_name → description` |
| `timeout` | `30.0` | Seconds before the command is killed |
| `confirm` | `False` | Set `True` or a string to require confirmation |
| `platforms` | `None` | OSes this runs on, e.g. `["linux", "macos"]` (None = all) |
| `requires` | `None` | Executables that must be on PATH, e.g. `["traceroute"]` |

---

## 3. Requiring confirmation

Mark any tool with `confirm` to make SysBot ask for approval before it runs:

```python
@tool(
    description="Delete all log files in a directory",
    confirm="This will permanently delete log files — are you sure?",
)
async def delete_logs(directory: str) -> str:
    import glob, os
    files = glob.glob(f"{directory}/*.log")
    for f in files:
        os.remove(f)
    return f"Deleted {len(files)} log file(s)."
```

```python
reboot = CLITool(
    name="reboot_server",
    description="Reboot the local machine",
    command="sudo reboot",
    params={},
    confirm="This will immediately reboot the machine. Proceed?",
)
```

**How confirmation works per adapter:**

| Adapter | Behaviour |
|---|---|
| CLI | Prints the tool name, args, and prompt; asks `y/n` |
| Telegram | Sends a message with **✅ Yes** / **❌ No** inline buttons; waits 120 s |
| Slack | Auto-approves by default (override `SlackAdapter.confirm` to add UI) |

> Confirmation applies only when the **LLM** decides to call the tool. A direct `/tool_name` invocation runs immediately — typing the command yourself is the confirmation.

Example in Telegram:

```
User: reboot the server

⚠️ This will immediately reboot the machine. Proceed?
Tool: reboot_server

  [ ✅ Yes ]  [ ❌ No ]
```

If no response within 120 seconds, the call is cancelled.

---

## 4. Mixing `@tool` and `CLITool` in one file

A single file can define as many tools as you like:

```python
# tools/system.py
from sysbot.mcp import tool, CLITool
import platform, shutil

@tool
async def get_system_info() -> str:
    """Return basic information about the current machine."""
    return (
        f"OS: {platform.system()} {platform.release()}\n"
        f"Python: {platform.python_version()}\n"
        f"Machine: {platform.machine()}"
    )

@tool(description="Check free disk space at a given path")
async def disk_usage(path: str) -> str:
    usage = shutil.disk_usage(path)
    return (
        f"Path: {path}\n"
        f"Total: {usage.total / 1e9:.1f} GB\n"
        f"Free: {usage.free / 1e9:.1f} GB\n"
        f"Used: {usage.used / usage.total * 100:.1f}%"
    )

df = CLITool(
    name="df",
    description="Show raw disk usage from the df command",
    command="df -h {path}",
    params={"path": "Filesystem path to check"},
)
```

---

## 5. Shared utilities

If you have helpers used by multiple tool files, put them in a file that starts with `_`:

```python
# tools/_helpers.py   ← ignored by the tool loader
def format_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
```

```python
# tools/storage.py
from _helpers import format_bytes
from sysbot.mcp import tool
```

A plain `from _helpers import ...` works: for a loose-file layout the `tools/`
directory is on `sys.path`; inside a folder package, the package's own directory
is, so each package gets its own `_helpers.py` (two packages can ship a
`_helpers.py` without clashing). Keep package helper imports at module top level.
Editing `_helpers.py` also triggers a hot reload.

---

## 6. Cross-platform support

SysBot runs on Linux, macOS, and Windows, but not every tool can run everywhere.
Declare what a tool needs and SysBot gates it gracefully:

- `platforms` — the OSes a tool runs on, from `{"linux", "macos", "windows"}`.
  Omit it (the default) to mean **all** OSes.
- `requires` — external **executables** that must be on `PATH` (checked with
  `shutil.which`), e.g. `["nvidia-smi"]`. Omit it to require nothing.

```python
@tool(
    description="Report NVIDIA GPU temperature",
    platforms=["linux", "windows"],
    requires=["nvidia-smi"],
)
async def gpu_temp() -> str: ...
```

When the current OS isn't in `platforms`, or a required executable is missing,
the tool is **still registered** — it stays visible in `/help` and to the LLM —
but calling it returns a one-line explanation instead of running:

```
/gpu_temp
'gpu_temp' is unavailable on this machine — requires 'nvidia-smi' on PATH (not found).
```

This way the bot can explain *why* something can't run rather than failing
cryptically. Each tool is gated independently, so one missing binary in a package
doesn't disable its siblings.

> **Python (pip) dependencies** aren't `requires:` entries — those are PATH
> binaries. Import a pip dependency inside the tool and handle `ImportError` with
> a helpful message (see `tools/web/tool.py`), and list it in the package's
> `requirements.txt`.

The decorator/`CLITool` args are what SysBot enforces; mirror them in your
package `README.md` frontmatter for humans and the catalog.

---

## 7. Hot reload

When `mcp.hot_reload: true` (the default), SysBot watches `tools/` for file changes and reloads all tools automatically. You'll see a log line like:

```
Tool files changed — reloading...
Loaded 3 tool(s) from system.py
```

This means you can iterate on a tool, save, and immediately test it without restarting.
