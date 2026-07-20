"""Local web dashboard — manage tools and check LLM backend health.

A small aiohttp server, run concurrently with the messaging adapter
from ``__main__._run`` when ``dashboard.enabled`` / ``--dashboard``. It serves one
self-contained HTML page plus a tiny JSON API:

    GET  /                       the dashboard page
    GET  /api/status             {provider, model, llm: <health>, tools: [...]}
    POST /api/tools/{name}/toggle flip a tool on/off (persisted), returns its new row
    POST /api/tools/{name}/remove delete the tool's folder package / loose .py
    GET  /api/llm/health         LLM backend health only

Binds to ``127.0.0.1`` by default with no auth — it's a single-user local tool.
If the configured port is taken, the next free port is used (up to 10 tries);
``Dashboard.port`` holds the port actually bound.
``aiohttp`` is an optional dependency (``pip install -e ".[dashboard]"``); the import
is guarded so the rest of LeSysBot works without it.
"""
from __future__ import annotations

import asyncio
import errno
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lesysbot.core.agent import Agent
    from lesysbot.core.config import Settings

# aiohttp is the optional `dashboard` extra: import it once here and let
# start() report the friendly install hint, so the rest of LeSysBot imports fine
# without it and the handlers below can just use `web`.
try:
    from aiohttp import web
except ImportError:  # pragma: no cover - exercised by installs without the extra
    web = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# How many consecutive ports to try when the configured one is taken.
_PORT_ATTEMPTS = 10


class Dashboard:
    def __init__(self, agent: "Agent", settings: "Settings") -> None:
        self._agent = agent
        self._settings = settings
        self._cfg = settings.dashboard
        # The port actually bound (may differ from config when it was taken);
        # None until start() succeeds.
        self.port: int | None = None

    def _make_app(self):
        app = web.Application()
        app.add_routes([
            web.get("/", self._page),
            web.get("/api/status", self._api_status),
            web.get("/api/llm/health", self._api_health),
            web.post("/api/tools/{name}/toggle", self._api_toggle),
            web.post("/api/tools/{name}/remove", self._api_remove),
        ])
        return app

    async def start(self) -> None:
        if web is None:
            logger.error(
                "Dashboard needs aiohttp — install it with: pip install aiohttp "
                '(or pip install -e ".[dashboard]"). Skipping dashboard.'
            )
            return

        runner = web.AppRunner(self._make_app())
        await runner.setup()

        # The configured port may be taken (another lesysbot instance, or an
        # unrelated app) — walk forward to the next free port instead of dying
        # silently in the background task.
        for candidate in range(self._cfg.port, self._cfg.port + _PORT_ATTEMPTS):
            site = web.TCPSite(runner, self._cfg.host, candidate)
            try:
                await site.start()
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    continue
                logger.error(
                    "Dashboard could not bind %s:%d: %s — dashboard not started.",
                    self._cfg.host, candidate, e,
                )
                await runner.cleanup()
                return
            self.port = candidate
            break
        else:
            logger.error(
                "Dashboard ports %d-%d are all in use — dashboard not started "
                "(pick a free one with dashboard.port or --port).",
                self._cfg.port, self._cfg.port + _PORT_ATTEMPTS - 1,
            )
            await runner.cleanup()
            return

        if self.port != self._cfg.port:
            logger.warning(
                "Dashboard port %d is in use — serving on %d instead.",
                self._cfg.port, self.port,
            )
        logger.info("Dashboard at http://%s:%d", self._cfg.host, self.port)
        print(f"📊 Dashboard: http://{self._cfg.host}:{self.port}")

        try:
            await asyncio.Event().wait()  # run until cancelled
        finally:
            await runner.cleanup()

    # -- API ----------------------------------------------------------------

    def _status_payload(self, llm: dict) -> dict:
        return {
            "provider": self._settings.messaging.provider,
            "model": self._settings.llm.model,
            "llm": llm,
            "tools": self._agent.registry.tool_status(),
        }

    async def _api_status(self, request):
        health = await self._agent.llm.health()
        return web.json_response(self._status_payload(health))

    async def _api_health(self, request):
        return web.json_response(await self._agent.llm.health())

    async def _api_toggle(self, request):
        name = request.match_info["name"]
        registry = self._agent.registry
        if registry.get_tool_meta(name) is None:
            return web.json_response({"error": f"unknown tool: {name}"}, status=404)
        registry.set_enabled(name, not registry.is_enabled(name))
        # Return the refreshed row for this tool.
        row = next((t for t in registry.tool_status() if t["name"] == name), None)
        return web.json_response(row)

    async def _api_remove(self, request):
        name = request.match_info["name"]
        registry = self._agent.registry
        if registry.get_tool_meta(name) is None:
            return web.json_response({"error": f"unknown tool: {name}"}, status=404)
        try:
            info = registry.remove_tool(name)
        except (KeyError, ValueError) as e:
            return web.json_response({"error": str(e)}, status=400)
        except OSError as e:
            return web.json_response(
                {"error": f"could not delete {name}: {e}"}, status=500
            )
        # Keep the install lock honest when the removed package was installed
        # via `lesysbot tools install`.
        if info["kind"] == "package":
            from lesysbot.install.lockfile import drop_entries
            drop_entries(Path(self._settings.mcp.lock_file), [info["unit"]])
        return web.json_response({"removed": info["tools"], "path": info["path"]})

    async def _page(self, request):
        return web.Response(text=_PAGE, content_type="text/html")


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LeSysBot Dashboard</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e6e6; }
  header { padding: 18px 24px; border-bottom: 1px solid #262a33; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 24px; }
  .banner { padding: 14px 18px; border-radius: 10px; margin-bottom: 24px; border: 1px solid #262a33; background: #171a21; }
  .banner.ok { border-color: #1f7a3d; }
  .banner.bad { border-color: #9a2b2b; }
  .banner .dot { font-size: 18px; }
  .banner .meta { color: #9aa3b2; font-size: 13px; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #21252e; vertical-align: top; }
  th { color: #9aa3b2; font-weight: 500; font-size: 13px; }
  .name { font-weight: 600; }
  .desc { color: #9aa3b2; font-size: 13px; margin-top: 2px; }
  .tag { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 999px; border: 1px solid #3a4150; color: #aeb6c4; margin-right: 4px; }
  .tag.warn { border-color: #9a6b2b; color: #d7a25a; }
  .tag.gate { border-color: #9a2b2b; color: #d98a8a; }
  .tag.confirm { border-color: #6b4d9a; color: #b39ad9; }
  button.toggle { cursor: pointer; border: 1px solid #3a4150; background: #1d2128; padding: 6px 12px; border-radius: 8px; color: #e6e6e6; min-width: 78px; }
  button.toggle.on { background: #16331f; border-color: #1f7a3d; color: #79d999; }
  button.toggle.off { background: #2a1d1d; border-color: #6b3a3a; color: #d99; }
  button.rm { cursor: pointer; border: 1px solid #6b3a3a; background: transparent; padding: 6px 10px; border-radius: 8px; color: #d99; margin-left: 6px; }
  button.rm:hover { background: #2a1d1d; }
  td.actions { white-space: nowrap; text-align: right; }
  .muted { color: #6b7280; font-size: 12px; }
  .row.disabled .name, .row.disabled .desc { opacity: .55; }
</style>
</head>
<body>
<header><h1>📊 LeSysBot Dashboard</h1><span class="muted" id="sub"></span></header>
<div class="wrap">
  <div id="banner" class="banner">Loading…</div>
  <table>
    <thead><tr><th style="width:55%">Tool</th><th>Status</th><th style="width:170px"></th></tr></thead>
    <tbody id="tools"></tbody>
  </table>
  <p class="muted" id="foot"></p>
</div>
<script>
async function api(path, opts) { const r = await fetch(path, opts); return r.json(); }

function renderBanner(s) {
  const b = document.getElementById('banner');
  const llm = s.llm;
  document.getElementById('sub').textContent = `${s.provider} · ${s.model}`;
  if (llm.ok) {
    b.className = 'banner ok';
    const model = llm.model_available
      ? `model <b>${s.model}</b> available`
      : `<span style="color:#d7a25a">model <b>${s.model}</b> NOT in backend list</span>`;
    b.innerHTML = `<span class="dot">✅</span> <b>LLM backend reachable</b> · ${llm.latency_ms} ms`
      + `<div class="meta">${llm.base_url} · ${model} · ${(llm.models||[]).length} models</div>`;
  } else {
    b.className = 'banner bad';
    b.innerHTML = `<span class="dot">❌</span> <b>LLM backend unreachable</b>`
      + `<div class="meta">${llm.base_url}<br>${llm.error || ''}</div>`;
  }
}

function tags(t) {
  let out = '';
  if (!t.available) out += `<span class="tag gate">⚠ ${t.unavailable_reason}</span>`;
  if (t.platforms) out += `<span class="tag">${t.platforms.join(', ')}</span>`;
  if (t.requires && t.requires.length) out += `<span class="tag warn">needs ${t.requires.join(', ')}</span>`;
  if (t.confirm) out += `<span class="tag confirm">confirm</span>`;
  return out;
}

function renderTools(tools) {
  const tb = document.getElementById('tools');
  tb.innerHTML = '';
  for (const t of tools) {
    const tr = document.createElement('tr');
    tr.className = 'row' + (t.enabled ? '' : ' disabled');
    tr.innerHTML = `<td><div class="name">/${t.name}</div><div class="desc">${t.description||''}</div><div>${tags(t)}</div></td>`
      + `<td>${t.enabled ? '<span style="color:#79d999">enabled</span>' : '<span style="color:#d99">disabled</span>'}</td>`
      + `<td class="actions"></td>`;
    const btn = document.createElement('button');
    btn.className = 'toggle ' + (t.enabled ? 'on' : 'off');
    btn.textContent = t.enabled ? 'Disable' : 'Enable';
    btn.onclick = async () => { btn.disabled = true; await api(`/api/tools/${t.name}/toggle`, {method:'POST'}); await refresh(); };
    tr.children[2].appendChild(btn);
    const rm = document.createElement('button');
    rm.className = 'rm';
    rm.textContent = 'Remove';
    rm.title = 'Delete this tool from the tools directory';
    rm.onclick = async () => {
      if (!t.source) { alert(`/${t.name} wasn't loaded from the tools directory, so it can't be removed here.`); return; }
      const others = t.source.tools.filter(n => n !== t.name);
      let msg = `Remove /${t.name}?\\n\\nThis permanently deletes ${t.source.path}`;
      if (others.length) msg += `\\n\\nAlso removes: ${others.map(n => '/' + n).join(', ')}`;
      if (!confirm(msg)) return;
      rm.disabled = true;
      const res = await api(`/api/tools/${t.name}/remove`, {method:'POST'});
      if (res && res.error) alert('Remove failed: ' + res.error);
      await refresh();
    };
    tr.children[2].appendChild(rm);
    tb.appendChild(tr);
  }
  const on = tools.filter(t => t.enabled).length;
  document.getElementById('foot').textContent = `${on}/${tools.length} tools enabled · auto-refreshes every 5s`;
}

async function refresh() {
  try {
    const s = await api('/api/status');
    renderBanner(s);
    renderTools(s.tools);
  } catch (e) {
    document.getElementById('banner').innerHTML = '⚠ dashboard API error: ' + e;
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""
