"""Remote dashboard — start/stop/status for a passcode-gated Gradio web UI.

The Gradio server (``_app.py`` in this package) is spawned as a *detached*
process in its own session/process group, so it outlives bot restarts and tool
hot-reloads. The subprocess — not this module — writes the state file
(pid, port, passcode, URLs, expiry) once the server is actually accepting
connections, so ``start_dashboard`` simply waits for that file to appear and
replies with the link + passcode. With ``public=True`` (the default) Gradio
opens a ``*.gradio.live`` share tunnel, so the link works from anywhere, not
just the LAN; the passcode gates the page either way.

The passcode never travels anywhere except the state file (owner-only perms)
and the chat reply — pair this tool with a non-empty
``messaging.telegram.allowed_user_ids`` so strangers can't ask for a link.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from lesysbot.core.paths import user_dir
from lesysbot.mcp import notify_later, tool

# No ambiguous glyphs (0/o, 1/l/i) — the passcode may be retyped from a phone.
_PASSCODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_PASSCODE_LEN = 10
_BASE_PORT = 7860
_PORT_ATTEMPTS = 10
# First launch may download Gradio's share-tunnel binary, so be generous.
_READY_TIMEOUT = 90.0
_STOP_TIMEOUT = 8.0
# How often to check whether the server went away before its TTL.
_WATCH_POLL = 10.0
_MIN_TTL_MIN, _MAX_TTL_MIN, _DEFAULT_TTL_MIN = 5, 720, 60

# Popen handle for a server spawned by *this* bot process — kept so poll() can
# reap the child if it exits (otherwise it lingers as a zombie until we do).
# The state file, not this handle, is the source of truth: it survives bot
# restarts and tool hot-reloads, which reset module globals.
_proc: subprocess.Popen | None = None
_expiry_announce: asyncio.Task | None = None


def _state_path() -> Path:
    return user_dir() / "remote_dashboard.json"


def _log_path() -> Path:
    return user_dir() / "logs" / "remote-dashboard.log"


def _read_state() -> dict | None:
    try:
        state = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _clear_state() -> None:
    try:
        _state_path().unlink()
    except OSError:
        pass


def _dashboard_running(state: dict | None) -> bool:
    """True if the state file's pid is alive and still looks like our server.

    The cmdline check guards against pid reuse after a reboot, and doubles as
    the zombie detector on Linux (a reaped-but-unwaited process has an empty
    /proc cmdline). Windows offers no cheap cmdline lookup, so there a live
    pid is trusted.
    """
    global _proc
    if _proc is not None and _proc.poll() is not None:
        _proc = None  # reap
    pid = (state or {}).get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    except PermissionError:
        return True
    if sys.platform.startswith("linux"):
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        except OSError:
            return True
        return "_app.py" in cmdline
    if os.name == "posix":
        try:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return True
        return "_app.py" in out.stdout
    return True


def _pick_port() -> int | None:
    import socket

    for port in range(_BASE_PORT, _BASE_PORT + _PORT_ATTEMPTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    return None


def _tail_log(lines: int = 15) -> str:
    try:
        return "\n".join(_log_path().read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log available)"


def _fmt_minutes(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    return f"{minutes} min"


def _format_live(state: dict, header: str) -> str:
    # The passcode rides in the link (?t=…), so opening it is one click and no
    # typing; the server swaps it for a cookie and drops it from the address bar.
    passcode = state.get("passcode", "")
    tokenized = f"?t={passcode}" if passcode else ""

    lines = [header, ""]
    if state.get("share_url"):
        lines.append(
            f"🔗 {state['share_url']}{tokenized}  (public link — works from anywhere)"
        )
    if state.get("lan_url"):
        lines.append(f"🏠 {state['lan_url']}{tokenized}  (local network only)")
    if state.get("share_error"):
        lines.append(f"⚠️ Public link unavailable: {state['share_error']}")
    lines += [
        "",
        f"🔑 Passcode (if the page asks): {passcode or '?'}",
    ]
    expires_at = state.get("expires_at")
    if expires_at:
        lines.append(
            f"⏳ Auto-shutdown in ~{_fmt_minutes(expires_at - time.time())} — "
            "close it early with /stop_dashboard or the button on the page; "
            "/dashboard_status to check."
        )
    return "\n".join(lines)


async def _announce(text: str) -> None:
    task = notify_later(text, 0)
    if task is not None:
        await task


async def _announce_when_gone(deadline: float) -> None:
    """Ping the requester once the server is gone, saying which way it went.

    Polling rather than a plain timer at the TTL is what tells the two apart:
    the page's own Close button and the TTL shutdown both just leave the state
    file missing, so only the moment it disappears distinguishes them.
    (`stop_dashboard` cancels this task first — that path already replies.)
    """
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(_WATCH_POLL, remaining))
        if not _dashboard_running(_read_state()):
            await _announce(
                "🛑 The dashboard was closed from its web page — the link and "
                "passcode no longer work."
            )
            return
    await _announce("🕐 The dashboard link has expired — the server shut itself down.")


def _schedule_expiry_announce(delay: float) -> None:
    global _expiry_announce
    _cancel_expiry_announce()
    _expiry_announce = asyncio.create_task(_announce_when_gone(time.time() + delay))


def _cancel_expiry_announce() -> None:
    global _expiry_announce
    if _expiry_announce is not None and not _expiry_announce.done():
        _expiry_announce.cancel()
    _expiry_announce = None


def _spawn(port: int, passcode: str, ttl_min: int, public: bool) -> subprocess.Popen:
    """Launch _app.py detached, logging to its own file."""
    env = os.environ | {
        "LESYSBOT_DASH_PORT": str(port),
        "LESYSBOT_DASH_PASSCODE": passcode,
        "LESYSBOT_DASH_TTL_MIN": str(ttl_min),
        "LESYSBOT_DASH_SHARE": "1" if public else "0",
        "LESYSBOT_DASH_STATE": str(_state_path()),
        "GRADIO_ANALYTICS_ENABLED": "False",
    }
    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = (
        {"start_new_session": True}
        if os.name == "posix"
        else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        }
    )
    with open(log_path, "ab") as log:
        return subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("_app.py"))],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env=env, **kwargs,
        )


async def _wait_ready(proc: subprocess.Popen) -> dict | str:
    """Wait for the server to publish its state file; return error text on failure."""
    deadline = time.monotonic() + _READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return (
                f"❌ Dashboard failed to start (exit {proc.returncode}). Last log lines:\n"
                f"{_tail_log()}"
            )
        state = _read_state()
        if state and state.get("pid") == proc.pid and state.get("ready"):
            return state
        await asyncio.sleep(0.5)
    _terminate(proc.pid)
    return (
        f"❌ Dashboard didn't come up within {_READY_TIMEOUT:.0f}s — killed it. "
        f"Last log lines:\n{_tail_log()}"
    )


def _terminate(pid: int, sig: signal.Signals = signal.SIGTERM) -> None:
    try:
        if os.name == "posix":
            os.killpg(pid, sig)  # start_new_session=True makes pid the pgid
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


@tool(
    description=(
        "Launch the live web dashboard (Gradio) for remotely viewing/managing this "
        "system and send back its link and passcode. Use when the user asks for "
        "the dashboard link, a way to monitor the machine from a browser, or "
        "remote access. If already running, returns the current link."
    ),
    confirm="🌐 Launch the web dashboard and send a link + passcode to this chat?",
)
async def start_dashboard(minutes: int = _DEFAULT_TTL_MIN, public: bool = True) -> str:
    """Start the dashboard (or report the running one) and return link + passcode.

    minutes: auto-shutdown after this long (5–720). public: also open a
    *.gradio.live share link reachable from outside the LAN.
    """
    state = _read_state()
    if _dashboard_running(state):
        return _format_live(state, "ℹ️ The dashboard is already running.")
    _clear_state()

    if importlib.util.find_spec("gradio") is None:
        return "gradio not installed. Run: pip install gradio"
    port = _pick_port()
    if port is None:
        return f"❌ No free port in {_BASE_PORT}–{_BASE_PORT + _PORT_ATTEMPTS - 1}."

    minutes = max(_MIN_TTL_MIN, min(_MAX_TTL_MIN, minutes))
    passcode = "".join(secrets.choice(_PASSCODE_ALPHABET) for _ in range(_PASSCODE_LEN))

    global _proc
    _proc = _spawn(port, passcode, minutes, public)
    result = await _wait_ready(_proc)
    if isinstance(result, str):
        _proc = None
        _clear_state()
        return result

    _schedule_expiry_announce(minutes * 60)
    return _format_live(result, "🌐 Dashboard is live!")


@tool(description="Stop the running web dashboard and invalidate its link and passcode")
async def stop_dashboard() -> str:
    """Terminate the dashboard server and clear its state."""
    global _proc
    state = _read_state()
    _cancel_expiry_announce()
    if not _dashboard_running(state):
        _clear_state()
        return "The dashboard isn't running."

    pid = state["pid"]  # type: ignore[index]  # _dashboard_running verified it
    _terminate(pid)
    deadline = time.monotonic() + _STOP_TIMEOUT
    while time.monotonic() < deadline and _dashboard_running(state):
        await asyncio.sleep(0.3)
    if _dashboard_running(state):
        _terminate(pid, signal.SIGKILL)
    _proc = None
    _clear_state()

    started = state.get("started")  # type: ignore[union-attr]
    ran_for = f" after {_fmt_minutes(time.time() - started)}" if started else ""
    return f"🛑 Dashboard stopped{ran_for}. The link and passcode are no longer valid."


@tool(description="Check whether the web dashboard is running, with its link and time left")
async def dashboard_status() -> str:
    """Report dashboard state: running (with URL/passcode/time left) or not."""
    state = _read_state()
    if not _dashboard_running(state):
        _clear_state()
        return "The dashboard isn't running. Use /start_dashboard to launch it."
    return _format_live(state, "✅ Dashboard is running.")  # type: ignore[arg-type]
