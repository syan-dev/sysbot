"""Gradio server for the remote-dashboard tool — run as a detached subprocess.

Not a tool module (the ``_`` prefix keeps the loader away). Configuration
arrives via LESYSBOT_DASH_* environment variables (never argv — the passcode
must not show up in `ps`). Once the server accepts connections this process
writes the state file the parent tool is polling for, then sleeps until the
TTL expires, the page's own Close button sets ``_shutdown``, or the state file
stops pointing at this pid (which is how `stop_dashboard` wins even if its
signal got lost).

Gradio supplies the server, the refresh plumbing and the share tunnel, but not
the look: every panel below is hand-written HTML styled by ``_CSS``. No
component library and no CDN — the LAN URL has to render on a network with no
internet, so the stylesheet ships inline.

System readings reuse `lesysbot.core.sysinfo` — same best-effort collectors as
the startup notice, so the page simply omits what this host can't answer. The
collectors return display strings; the numbers behind the meters and status
bands are taken locally (`_memory`, `_disk`, `_hottest`) rather than by parsing
those strings back apart.
"""
from __future__ import annotations

import html
import inspect
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

import gradio as gr
from starlette.middleware import Middleware

from lesysbot.core import sysinfo
from lesysbot.core.paths import user_dir

PORT = int(os.environ["LESYSBOT_DASH_PORT"])
PASSCODE = os.environ["LESYSBOT_DASH_PASSCODE"]
TTL_MIN = int(os.environ["LESYSBOT_DASH_TTL_MIN"])
SHARE = os.environ.get("LESYSBOT_DASH_SHARE") == "1"
STATE_PATH = Path(os.environ["LESYSBOT_DASH_STATE"])

HOSTNAME = platform.node() or "unknown host"

# Set by the page's Close button (from a Gradio worker thread) and awaited by
# main() on the main thread — the one way the browser can end this process.
_shutdown = threading.Event()
# The click that sets it still has to get its reply rendered, so the teardown
# waits this long after the event before closing the server out from under it.
_CLOSE_GRACE_S = 1.5


def _write_state(state: dict) -> None:
    """Atomic write with owner-only permissions from the first byte."""
    tmp = STATE_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(STATE_PATH)


def _lan_ip() -> str | None:
    """This host's LAN address — no traffic is sent, connect() just picks a route."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


# -- readings ---------------------------------------------------------------

_DEGREES = re.compile(r"(-?\d+(?:\.\d+)?)\s*°C")


def _hottest(text: str) -> float | None:
    """Highest °C in a collector string — "62°C", or "GPU0: 55°C, GPU1: 61°C".

    Matching on the degree suffix rather than the first number keeps the GPU
    line's device *index* from being read as a temperature.
    """
    values = [float(v) for v in _DEGREES.findall(text)]
    return max(values) if values else None


def _memory() -> tuple[float, float, float] | None:
    """(free GB, total GB, % used) — Linux-only best effort via /proc/meminfo."""
    try:
        fields = {
            line.split(":")[0]: int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if ":" in line
        }
        total, available = fields["MemTotal"], fields["MemAvailable"]
    except (OSError, KeyError, ValueError, IndexError):
        return None
    if not total:
        return None
    return available / 1e6, total / 1e6, (total - available) / total * 100


def _disk() -> tuple[float, float, float] | None:
    """(free GB, total GB, % used) for the main drive.

    Same target as ``sysinfo.disk_usage_line`` — that one formats a sentence,
    this one keeps the numbers the meter needs.
    """
    target = Path.home().anchor or "/"
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return None
    if not usage.total:
        return None
    return usage.free / 1e9, usage.total / 1e9, usage.used / usage.total * 100


# -- status bands -----------------------------------------------------------

# (exclusive upper bound, status key, label). The icons make each band legible
# without colour — a status is never signalled by hue alone.
_TEMP_BANDS = ((60, "good", "Normal"), (75, "warning", "Warm"),
               (85, "serious", "Hot"), (None, "critical", "Critical"))
_USAGE_BANDS = ((70, "good", "Healthy"), (85, "warning", "Filling up"),
                (95, "serious", "Tight"), (None, "critical", "Critical"))
# Load is banded as a percentage of core count, so it means the same on any host.
_LOAD_BANDS = ((70, "good", "Light"), (100, "warning", "Busy"),
               (150, "serious", "Heavy"), (None, "critical", "Overloaded"))

_STATUS_ICON = {"good": "●", "warning": "▲", "serious": "◆", "critical": "■"}


def _band(value: float, bands: tuple) -> tuple[str, str]:
    for limit, key, label in bands:
        if limit is None or value < limit:
            return key, label
    return bands[-1][1], bands[-1][2]


# -- HTML fragments ---------------------------------------------------------

def _esc(value: object) -> str:
    return html.escape(str(value))


def _tile(
    label: str,
    value: str,
    unit: str = "",
    *,
    status: tuple[str, str] | None = None,
    meter: float | None = None,
    sub: str | None = None,
) -> str:
    """One stat tile. ``meter`` is a 0–100 fill that takes ``status``'s colour."""
    out = [f'<div class="sb-tile"><div class="sb-label">{_esc(label)}</div>']
    unit_html = f'<span class="sb-unit">{_esc(unit)}</span>' if unit else ""
    out.append(f'<div class="sb-value">{_esc(value)}{unit_html}</div>')
    key = status[0] if status else "good"
    if meter is not None:
        width = max(0.0, min(100.0, meter))
        out.append(
            f'<div class="sb-meter" data-st="{key}">'
            f'<span style="width:{width:.1f}%"></span></div>'
        )
    if status is not None:
        out.append(
            f'<div class="sb-status" data-st="{key}">'
            f'<span class="sb-ico">{_STATUS_ICON[key]}</span>{_esc(status[1])}</div>'
        )
    if sub:
        out.append(f'<div class="sb-sub">{_esc(sub)}</div>')
    out.append("</div>")
    return "".join(out)


def _temp_tile(label: str, reading: str) -> str:
    """Temperature tile; falls back to the raw reading if it has no parseable °C."""
    hottest = _hottest(reading)
    if hottest is None:
        return _tile(label, reading)
    # Multi-sensor lines ("GPU0: 55°C, GPU1: 61°C") keep the full text below the
    # headline number, which shows only the hottest.
    detail = reading if "," in reading else None
    # Metered on a flat 0–100 °C scale, so the bar reads as thermal headroom and
    # every tile in the grid keeps the same label/value/meter/status rhythm.
    return _tile(label, f"{hottest:.0f}", "°C", status=_band(hottest, _TEMP_BANDS),
                 meter=hottest, sub=detail)


def _usage_tile(label: str, reading: tuple[float, float, float]) -> str:
    free_gb, total_gb, pct = reading
    status = _band(pct, _USAGE_BANDS)
    return _tile(label, f"{pct:.0f}", "%", status=status, meter=pct,
                 sub=f"{free_gb:.1f} GB free of {total_gb:.0f} GB")


def _load_tile() -> str | None:
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):  # no getloadavg on Windows
        return None
    cores = os.cpu_count() or 1
    status = _band(load1 / cores * 100, _LOAD_BANDS)
    return _tile("Load average", f"{load1:.2f}", status=status,
                 meter=load1 / cores * 100,
                 sub=f"{load5:.2f} · {load15:.2f} over 5 / 15 min · {cores} cores")


def _panel(body: str, *, stamp: bool = True, note: str = "") -> str:
    foot = ""
    if stamp:
        foot = (f'<div class="sb-foot">{_esc(note)} · ' if note else '<div class="sb-foot">')
        foot += f'Last update {time.strftime("%H:%M:%S")}</div>'
    return f'<div class="sb">{body}{foot}</div>'


# -- panels -----------------------------------------------------------------

async def render_overview() -> str:
    up = sysinfo.uptime()
    meta = f"{platform.system()} {platform.release()}"
    head = (
        '<div class="sb-head">'
        f'<div class="sb-host">{_esc(HOSTNAME)}</div>'
        f'<div class="sb-meta">{_esc(meta)}</div>'
        + (f'<div class="sb-up">up {_esc(up)}</div>' if up else "")
        + "</div>"
    )

    tiles = []
    cpu = sysinfo.cpu_temperature()
    if cpu:
        tiles.append(_temp_tile("CPU temperature", cpu))
    gpu = await sysinfo.gpu_temperature()
    if gpu:
        tiles.append(_temp_tile("GPU temperature", gpu))
    load = _load_tile()
    if load:
        tiles.append(load)
    memory = _memory()
    if memory:
        tiles.append(_usage_tile("Memory", memory))
    disk = _disk()
    if disk:
        tiles.append(_usage_tile("Disk", disk))

    if not tiles:
        grid = '<div class="sb-empty">This host exposes none of the readings.</div>'
    else:
        grid = f'<div class="sb-grid">{"".join(tiles)}</div>'
    return _panel(head + grid, note="Auto-refreshes every 10 s")


_PS_ROWS = 20
# Ask for exactly the columns we render, `=` suppressing the headers. `ps aux`
# is *not* safe to split positionally: its START column is locale-formatted and
# becomes two tokens under some locales (vi_VN renders "Thg 7 19"), which shifts
# COMMAND along by one and drags the TIME value into the command text. With a
# pinned four-field prefix, everything after the 4th token is the command.
_PS_FIELDS = "pid=,user=,pcpu=,pmem=,args="


def _ps_command(sort_by: str) -> list[str]:
    if os.name != "posix":
        return ["tasklist"]
    if sys.platform == "darwin":  # BSD ps sorts with -r/-m, it has no --sort
        return ["ps", "-Ao", _PS_FIELDS, "-r" if sort_by == "CPU" else "-m"]
    return ["ps", "-eo", _PS_FIELDS,
            "--sort=-pcpu" if sort_by == "CPU" else "--sort=-pmem"]


def _parse_ps(text: str) -> list[tuple[str, str, float, float, str]]:
    """(user, pid, %cpu, %mem, command); empty when the output isn't that shape."""
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            cpu, mem = float(parts[2]), float(parts[3])
        except ValueError:
            continue  # a stray header line, or tasklist's own format
        rows.append((parts[1], parts[0], cpu, mem, parts[4]))
        if len(rows) == _PS_ROWS:
            break
    return rows


def render_processes(sort_by: str = "CPU") -> str:
    try:
        out = subprocess.run(_ps_command(sort_by), capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return _panel(f'<div class="sb-empty">Process list unavailable: {_esc(e)}</div>',
                      stamp=False)

    rows = _parse_ps(out.stdout)
    if not rows:  # Windows tasklist, or a ps that ignored the -o field list
        raw = out.stdout or out.stderr or "(no output)"
        return _panel(f'<pre class="sb-pre">{_esc(raw)}</pre>')

    # The bar is scaled to the busiest row, not to an absolute 100%: %MEM tops
    # out near 1% on a large-RAM host, so an absolute scale renders every bar as
    # the same stub. The exact figure is in its own column either way.
    shares = [cpu if sort_by == "CPU" else mem for _, _, cpu, mem, _ in rows]
    peak = max(shares) or 1.0

    body = []
    for (user, pid, cpu, mem, command), share in zip(rows, shares):
        body.append(
            "<tr>"
            f'<td class="sb-cmd" title="{_esc(command)}">{_esc(command)}</td>'
            f'<td class="sb-num">{cpu:.1f}</td>'
            f'<td class="sb-num">{mem:.1f}</td>'
            f'<td class="sb-num sb-dim">{_esc(pid)}</td>'
            f'<td class="sb-dim">{_esc(user)}</td>'
            f'<td class="sb-bar"><span style="width:{share / peak * 100:.1f}%"></span></td>'
            "</tr>"
        )
    table = (
        '<table class="sb-table"><thead><tr>'
        "<th>Command</th><th class=\"sb-num\">%CPU</th><th class=\"sb-num\">%MEM</th>"
        "<th class=\"sb-num\">PID</th><th>User</th>"
        f'<th class="sb-bar-h">{_esc(sort_by)}</th>'
        f"</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )
    return _panel(table, note=f"Top {len(rows)} by {sort_by.lower()}")


# Level tokens as the file logger writes them, checked in severity order so a
# line that names more than one level is tinted by the most severe.
_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "DEBUG")


def _log_line(line: str) -> str:
    """Escape a log line and tag its level so CSS can tint it."""
    safe = _esc(line)
    for level in _LOG_LEVELS:
        if level in line:
            return f'<span class="sb-log" data-lvl="{level}">{safe}</span>'
    return safe


def render_logs(lines: float = 100) -> str:
    log = _lesysbot_log_path()
    if log is None:
        return _panel('<div class="sb-empty">LeSysBot log file not found.</div>',
                      stamp=False)
    try:
        tail = log.read_text(errors="replace").splitlines()[-int(lines):]
    except OSError as e:
        return _panel(f'<div class="sb-empty">Cannot read {_esc(log)}: {_esc(e)}</div>',
                      stamp=False)
    if not tail:
        return _panel(f'<div class="sb-empty">{_esc(log)} is empty.</div>', stamp=False)
    body = "\n".join(_log_line(line) for line in tail)
    return _panel(f'<pre class="sb-pre sb-logs">{body}</pre>',
                  note=f"{len(tail)} lines from {log.name}")


def _ask_panel() -> str:
    return _panel(
        '<div class="sb-empty">Close the dashboard <b>for everyone</b>? '
        "The server stops and this link and passcode die with it — a new one "
        "only comes from the chat.</div>",
        stamp=False,
    )


def _closed_panel() -> str:
    return _panel(
        '<div class="sb-empty"><b>Dashboard closed.</b><br>'
        "This link and its passcode no longer work. Ask LeSysBot for a fresh one "
        "with <b>/start_dashboard</b>.</div>",
        stamp=False,
    )


def _lesysbot_log_path() -> Path | None:
    try:
        from lesysbot.core.config import Settings, resolve_paths

        settings = Settings.load()
        resolve_paths(settings)
        if settings.logging.file and Path(settings.logging.file).exists():
            return Path(settings.logging.file)
    except Exception:
        pass
    fallback = user_dir() / "logs" / "lesysbot.log"
    return fallback if fallback.exists() else None


# -- stylesheet -------------------------------------------------------------

# Dark is a selected set of steps, not an inverted light — declared once and
# applied under three scopes: the OS setting, a data-theme stamp, and Gradio's
# own `.dark` class (its theme toggle), so whichever drives the page wins.
_DARK_VARS = """
  color-scheme: dark;
  --surface: #1a1a19; --plane: #0d0d0d;
  --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
  --line: rgba(255,255,255,.10); --grid: #2c2c2a;
  --accent: #3987e5;
"""

_CSS = f"""
.sb {{
  color-scheme: light;
  --surface: #fcfcfb; --plane: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
  --line: rgba(11,11,11,.10); --grid: #e1e0d9;
  --accent: #2a78d6;
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--ink-1);
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .sb {{{_DARK_VARS}}}
}}
:root[data-theme="dark"] .sb {{{_DARK_VARS}}}
.dark .sb {{{_DARK_VARS}}}

/* Status steps are fixed — they never re-tone per mode. The icon carries the
   colour; the label stays in ink, so a state never reads by hue alone. */
.sb [data-st="good"]     {{ --st: #0ca30c; }}
.sb [data-st="warning"]  {{ --st: #fab219; }}
.sb [data-st="serious"]  {{ --st: #ec835a; }}
.sb [data-st="critical"] {{ --st: #d03b3b; }}

.sb, .sb * {{ box-sizing: border-box; }}
.sb {{ padding: 4px 2px 0; }}

.sb-head {{
  display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 12px;
  padding-bottom: 16px; margin-bottom: 20px; border-bottom: 1px solid var(--line);
}}
.sb-host {{ font-size: 20px; font-weight: 600; letter-spacing: -.01em; }}
.sb-meta {{ color: var(--ink-2); font-size: 13px; }}
.sb-up {{
  margin-left: auto; color: var(--ink-2); font-size: 13px;
  border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px;
}}

.sb-grid {{
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}}
.sb-tile {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px 15px;
}}
.sb-label {{ color: var(--ink-2); font-size: 13px; }}
.sb-value {{
  font-size: 30px; font-weight: 600; line-height: 1.15;
  letter-spacing: -.02em; margin-top: 2px;
}}
.sb-unit {{ font-size: 15px; font-weight: 500; color: var(--ink-2); margin-left: 2px; }}
.sb-sub {{ color: var(--ink-3); font-size: 12px; margin-top: 6px; }}

.sb-status {{
  display: flex; align-items: center; gap: 6px;
  color: var(--ink-2); font-size: 12px; margin-top: 8px;
}}
.sb-ico {{ color: var(--st); font-size: 10px; line-height: 1; }}

/* Meter: severity in the fill, the track a wash of that same colour so the
   state reads across the whole bar. 4px ends, anchored left. */
.sb-meter {{
  height: 6px; border-radius: 4px; margin-top: 10px; overflow: hidden;
  background: color-mix(in srgb, var(--st) 18%, var(--surface));
}}
.sb-meter span {{ display: block; height: 100%; border-radius: 4px; background: var(--st); }}

/* gr.HTML renders inside `.prose`, whose `td,th {{ border: 1px solid }}` +
   padding rules sit at specificity (0,2,1) and beat any single-class selector
   here — a full box border on every cell makes the table read as a spreadsheet
   grid. These four are the only declarations that have to be forced. */
.sb-table, .sb-table tr {{
  border: 0 !important;  /* .prose borders `table` and `tr` too, not just cells */
}}
.sb-table {{
  width: 100%; border-collapse: collapse; font-size: 13px; background: none;
}}
.sb-table th {{
  text-align: left; font-weight: 500; color: var(--ink-3); font-size: 12px;
  white-space: nowrap;
  border: 0 !important; border-bottom: 1px solid var(--grid) !important;
  padding: 0 10px 8px 0 !important;
}}
.sb-table td {{
  vertical-align: middle; background: none;
  border: 0 !important; border-bottom: 1px solid var(--line) !important;
  padding: 7px 10px 7px 0 !important;
}}
.sb-num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.sb-dim {{ color: var(--ink-2); }}
.sb-cmd {{
  max-width: 0; width: 45%; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}}
.sb-bar-h, .sb-table td.sb-bar {{ width: 90px; padding-right: 0; }}
.sb-bar span {{
  display: block; height: 6px; border-radius: 4px; background: var(--accent);
  min-width: 2px;
}}
.sb-table td.sb-bar {{
  background: linear-gradient(color-mix(in srgb, var(--accent) 16%, var(--surface)) 0 0)
              no-repeat 0 50% / 100% 6px;
}}

.sb-pre {{
  margin: 0; padding: 14px 16px; border-radius: 10px; overflow-x: auto;
  background: var(--surface); border: 1px solid var(--line);
  font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--ink-2); max-height: 60vh; white-space: pre;
}}
.sb-logs {{ white-space: pre-wrap; word-break: break-word; }}
.sb-log[data-lvl="DEBUG"]    {{ color: var(--ink-3); }}
.sb-log[data-lvl="WARNING"]  {{ color: #b8790a; }}
.sb-log[data-lvl="ERROR"],
.sb-log[data-lvl="CRITICAL"] {{ color: #d03b3b; font-weight: 600; }}
.dark .sb-log[data-lvl="WARNING"],
:root[data-theme="dark"] .sb-log[data-lvl="WARNING"] {{ color: #fab219; }}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .sb-log[data-lvl="WARNING"] {{ color: #fab219; }}
}}

.sb-empty {{
  color: var(--ink-2); font-size: 14px; padding: 24px 16px; text-align: center;
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
}}
.sb-foot {{ color: var(--ink-3); font-size: 12px; margin-top: 14px; }}

/* The close row sits outside `.sb`, so it can't use the palette vars — the
   rule is drawn from currentColor to stay right in both modes. */
.sb-actions {{
  margin-top: 20px; padding-top: 16px; flex-wrap: wrap;
  border-top: 1px solid color-mix(in srgb, currentColor 14%, transparent);
}}

.gradio-container {{ max-width: 1080px !important; }}
/* Gradio's footer links to the API playground and settings — noise on a page
   whose whole job is a read-only status view, and it invites poking at the
   endpoint on a dashboard that may be reachable over the share tunnel. */
footer {{ display: none !important; }}
"""


# Gradio 6 moved `css` from the Blocks constructor to launch(); Gradio 5 only
# accepts it on Blocks. Both are supported (requirements.txt says >=5), and the
# wrong one fails *silently* on 6 — its Blocks swallows unknown kwargs with a
# warning — so ask the signature which end takes it rather than guessing.
_CSS_ON_LAUNCH = "css" in inspect.signature(gr.Blocks.launch).parameters


def _close_controls(tabs: gr.Tabs, timer: gr.Timer) -> None:
    """Footer row that shuts the server down from the browser.

    Closing takes two clicks on purpose: it ends the session for every viewer,
    and only the chat can hand out a new link — a stray tap on a phone would
    otherwise strand whoever is holding the page. Hiding the tabs and stopping
    the timer on the way out leaves the goodbye panel alone on screen instead
    of a live view that starts throwing connection errors a second later.
    """
    notice = gr.HTML(visible=False)
    with gr.Row(elem_classes="sb-actions") as actions:
        close = gr.Button("Close dashboard", variant="stop", size="sm",
                          scale=0, min_width=150)
        confirm = gr.Button("Yes, close it", variant="stop", size="sm",
                            scale=0, min_width=150, visible=False)
        cancel = gr.Button("Keep it open", size="sm",
                           scale=0, min_width=150, visible=False)

    def ask():
        return (gr.update(visible=False), gr.update(visible=True),
                gr.update(visible=True), gr.update(value=_ask_panel(), visible=True))

    def keep():
        return (gr.update(visible=True), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False))

    def shut_down():
        # main() is waiting on this; the grace period there is what lets these
        # updates land in the browser before the server goes away.
        _shutdown.set()
        return (gr.update(visible=False), gr.update(active=False),
                gr.update(visible=False),
                gr.update(value=_closed_panel(), visible=True))

    close.click(ask, outputs=[close, confirm, cancel, notice])
    cancel.click(keep, outputs=[close, confirm, cancel, notice])
    confirm.click(shut_down, outputs=[tabs, timer, actions, notice])


def build_app() -> gr.Blocks:
    css_kwarg = {} if _CSS_ON_LAUNCH else {"css": _CSS}
    with gr.Blocks(title=f"LeSysBot — {HOSTNAME}", **css_kwarg) as demo:
        # The tab strip stays a Gradio component on purpose: the 10 s timer
        # replaces each panel's HTML wholesale, and a CSS-only tab (:checked)
        # would reset to the first tab on every tick.
        with gr.Tabs() as tabs:
            with gr.Tab("Overview"):
                overview = gr.HTML(_panel('<div class="sb-empty">Loading…</div>',
                                          stamp=False))
                timer = gr.Timer(10)
                timer.tick(render_overview, outputs=overview)
                demo.load(render_overview, outputs=overview)
            with gr.Tab("Processes"):
                sort_by = gr.Radio(["CPU", "Memory"], value="CPU", label="Sort by")
                procs = gr.HTML()
                refresh = gr.Button("Refresh", size="sm")
                for trigger in (refresh.click, sort_by.change, demo.load):
                    trigger(render_processes, inputs=sort_by, outputs=procs)
            with gr.Tab("Logs"):
                n_lines = gr.Slider(50, 500, value=100, step=50, label="Lines")
                logs = gr.HTML()
                log_refresh = gr.Button("Refresh", size="sm")
                for trigger in (log_refresh.click, n_lines.release, demo.load):
                    trigger(render_logs, inputs=n_lines, outputs=logs)
        _close_controls(tabs, timer)
    return demo


COOKIE_NAME = "lesysbot_dash"
# Gradio calls this on itself during launch(), before any user could have a
# cookie, and fails to start if it 401s. Unauthenticated in Gradio too — it
# runs the startup hooks once and returns a bool, so it gives nothing away.
_OPEN_PATHS = frozenset({"/gradio_api/startup-events"})

_GATE_PAGE = """<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeSysBot dashboard</title>
<style>
 body{font:16px system-ui,sans-serif;margin:0;display:grid;place-items:center;
      min-height:100vh;background:#f6f7f9;color:#1a1a1a}
 form{background:#fff;padding:2rem;border-radius:12px;width:min(22rem,90vw);
      box-shadow:0 1px 3px rgba(0,0,0,.12)}
 h1{font-size:1.1rem;margin:0 0 1.25rem}
 input{width:100%;box-sizing:border-box;padding:.65rem;font-size:1rem;
       border:1px solid #ccc;border-radius:6px;letter-spacing:.08em}
 button{width:100%;margin-top:1rem;padding:.7rem;font-size:1rem;font-weight:600;
        border:0;border-radius:6px;background:#f36f21;color:#fff;cursor:pointer}
 @media (prefers-color-scheme:dark){
  body{background:#16181d;color:#e8e8e8}form{background:#22252c;box-shadow:none}
  input{background:#2c3038;border-color:#3a3f49;color:inherit}}
</style>
<form method="get" action="/">
 <h1>Enter the passcode LeSysBot sent to your chat</h1>
 <input name="t" type="password" autofocus autocomplete="off"
        inputmode="latin" placeholder="passcode">
 <button type="submit">Open dashboard</button>
</form>
"""


def _matches(value: str) -> bool:
    """Constant-time passcode compare; non-ASCII can't be a passcode anyway."""
    return bool(value) and value.isascii() and secrets.compare_digest(value, PASSCODE)


def _authorized(request) -> str | None:
    """Gradio's ``auth_dependency`` hook — the cookie *is* the whole login."""
    return "lesysbot" if _matches(request.cookies.get(COOKIE_NAME, "")) else None


class TokenGate:
    """Trade ``?t=<passcode>`` for a session cookie — no username, anywhere.

    Gradio's ``auth=`` only speaks (user, password), so its login page always
    renders two fields. ``auth_dependency`` replaces that page with this: the
    link LeSysBot sends already carries the passcode, so the usual path is one
    click and zero typing; anyone arriving without it gets a single-field form.

    Raw ASGI rather than ``BaseHTTPMiddleware`` because Gradio streams its
    event queue over SSE, which that helper buffers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or scope.get("path") in _OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        query = parse_qs(scope.get("query_string", b"").decode(errors="replace"))
        if _matches(query.get("t", [""])[0]):
            # Redirect to the bare path so the passcode leaves the address bar
            # (and with it the browser history, and any Referer we'd send out).
            await self._redirect(scope, send)
            return

        cookies = SimpleCookie()
        cookies.load(headers.get(b"cookie", b"").decode(errors="replace"))
        morsel = cookies.get(COOKIE_NAME)
        if morsel is not None and _matches(morsel.value):
            await self.app(scope, receive, send)
            return

        await self._deny(scope, headers, send)

    async def _redirect(self, scope, send) -> None:
        cookie = (
            f"{COOKIE_NAME}={PASSCODE}; Path=/; Max-Age={TTL_MIN * 60}"
            "; HttpOnly; SameSite=Lax"  # no Secure: the LAN URL is plain http
        )
        await send({
            "type": "http.response.start",
            "status": 303,
            "headers": [
                (b"location", (scope.get("path") or "/").encode()),
                (b"set-cookie", cookie.encode()),
            ],
        })
        await send({"type": "http.response.body", "body": b""})

    async def _deny(self, scope, headers, send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        # A browser navigating here gets the passcode form; Gradio's own fetches
        # (and anyone probing the API) get a plain 401 they can act on.
        wants_html = b"text/html" in headers.get(b"accept", b"")
        body = _GATE_PAGE.encode() if wants_html else b'{"error":"passcode required"}'
        ctype = b"text/html; charset=utf-8" if wants_html else b"application/json"
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", ctype),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


def main() -> None:
    demo = build_app()
    kwargs = dict(
        server_name="0.0.0.0",
        server_port=PORT,
        auth_dependency=_authorized,
        # TokenGate is the real gate; auth_dependency is the belt to its braces,
        # so a route the middleware ever waves through still can't skip the check.
        app_kwargs={"middleware": [Middleware(TokenGate)]},
        # Keep every request on this ASGI app — the SSR front proxy would sit
        # in front of the middleware and see the cookie only second-hand.
        ssr_mode=False,
        prevent_thread_lock=True,
        quiet=False,
    )
    if _CSS_ON_LAUNCH:
        kwargs["css"] = _CSS
    share_url, share_error = None, None
    try:
        _, _, share_url = demo.launch(share=SHARE, **kwargs)
    except Exception as e:  # share tunnel can fail (offline, frpc blocked)
        if not SHARE:
            raise
        share_error = str(e)
        demo.launch(share=False, **kwargs)
    if SHARE and share_url is None and share_error is None:
        share_error = "share link could not be created (see dashboard log)"

    lan = _lan_ip()
    expires_at = time.time() + TTL_MIN * 60
    _write_state({
        "pid": os.getpid(),
        "port": PORT,
        "passcode": PASSCODE,
        "lan_url": f"http://{lan}:{PORT}" if lan else f"http://localhost:{PORT}",
        "share_url": share_url,
        "share_error": share_error,
        "started": time.time(),
        "expires_at": expires_at,
        "ready": True,
    })

    try:
        while time.time() < expires_at:
            if _shutdown.wait(5):  # the page's Close button
                time.sleep(_CLOSE_GRACE_S)
                break
            try:
                state = json.loads(STATE_PATH.read_text())
            except (OSError, ValueError):
                break  # state gone/corrupt → stop_dashboard cleared it
            if state.get("pid") != os.getpid():
                break  # someone else owns the state now
    finally:
        try:
            state = json.loads(STATE_PATH.read_text())
            if state.get("pid") == os.getpid():
                STATE_PATH.unlink()
        except (OSError, ValueError):
            pass
        demo.close()


if __name__ == "__main__":
    main()
