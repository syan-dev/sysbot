"""Dashboard JSON API over a real aiohttp test server (status / toggle / remove)."""

from __future__ import annotations

import asyncio
import socket

import pytest

pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from lesysbot.core.config import Settings, resolve_paths  # noqa: E402
from lesysbot.dashboard.server import Dashboard  # noqa: E402
from lesysbot.mcp.registry import ToolRegistry  # noqa: E402

TOOL = '''
from lesysbot.mcp import tool

@tool(description="pingy")
async def pingy() -> str:
    return "pong"
'''


class _FakeLLM:
    async def health(self):
        return {"ok": True, "latency_ms": 1, "base_url": "x", "model": "m",
                "model_available": True, "models": ["m"]}


class _FakeAgent:
    def __init__(self, registry):
        self._registry = registry
        self._llm = _FakeLLM()

    @property
    def registry(self):
        return self._registry

    @property
    def llm(self):
        return self._llm


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / ".lesysbot"))
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "tools" / "net"
    pkg.mkdir(parents=True)
    (pkg / "tool.py").write_text(TOOL)

    settings = Settings.load()
    resolve_paths(settings)

    registry = ToolRegistry()
    registry.set_state_path(settings.dashboard.state_file)
    registry.load_directory(settings.mcp.tools_dir)

    dash = Dashboard(_FakeAgent(registry), settings)
    client = TestClient(TestServer(dash._make_app()))
    await client.start_server()
    yield client
    await client.close()


async def test_status_lists_tools_with_source(client):
    resp = await client.get("/api/status")
    data = await resp.json()
    tools = {t["name"]: t for t in data["tools"]}
    assert tools["pingy"]["enabled"] is True
    assert tools["pingy"]["source"]["unit"] == "net"


async def test_toggle_flips_enabled(client):
    resp = await client.post("/api/tools/pingy/toggle")
    assert (await resp.json())["enabled"] is False


async def test_remove_unknown_is_404(client):
    resp = await client.post("/api/tools/nope/remove")
    assert resp.status == 404


async def test_remove_deletes_package(client, tmp_path):
    resp = await client.post("/api/tools/pingy/remove")
    data = await resp.json()
    assert resp.status == 200
    assert data["removed"] == ["pingy"]
    assert not (tmp_path / "tools" / "net").exists()

    # gone from subsequent status calls too
    status = await (await client.get("/api/status")).json()
    assert status["tools"] == []


async def test_start_falls_back_when_port_taken(tmp_path, monkeypatch):
    import aiohttp

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / ".lesysbot"))
    monkeypatch.chdir(tmp_path)
    settings = Settings.load()
    resolve_paths(settings)

    # Occupy a port and point the dashboard at it — start() should walk
    # forward to a free one and record it on dash.port.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        taken = sock.getsockname()[1]
        settings.dashboard.port = taken

        dash = Dashboard(_FakeAgent(ToolRegistry()), settings)
        task = asyncio.create_task(dash.start())
        try:
            for _ in range(100):
                if dash.port is not None:
                    break
                await asyncio.sleep(0.05)
            assert dash.port is not None, "dashboard never bound a port"
            assert dash.port != taken

            async with aiohttp.ClientSession() as session:
                resp = await session.get(f"http://127.0.0.1:{dash.port}/api/status")
                assert resp.status == 200
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
