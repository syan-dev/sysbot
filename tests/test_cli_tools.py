"""`sysbot tools …` CLI: parser grammar and dispatch over a real temp tools dir."""

from __future__ import annotations

import json

import pytest

from sysbot.__main__ import build_parser
from sysbot.mcp import cli as tool_cli

TOOL = '''
from sysbot.mcp import tool

@tool(description="say hi")
async def greet() -> str:
    return "hi"
'''


def test_tool_grammar():
    args = build_parser().parse_args(["tools", "remove", "greet", "-y"])
    assert (args.command, args.tool_cmd) == ("tools", "remove")

    # `tool` works as an alias
    args = build_parser().parse_args(["tool", "remove", "greet", "-y"])
    assert (args.command, args.tool_cmd) == ("tool", "remove")
    assert args.name == "greet" and args.yes

    args = build_parser().parse_args(["tools", "list", "--json"])
    assert args.as_json

    with pytest.raises(SystemExit):
        build_parser().parse_args(["tools"])


def test_config_flag_both_positions():
    args = build_parser().parse_args(["-c", "root.yaml", "tool", "list"])
    assert args.config == "root.yaml"  # leaf SUPPRESS keeps the root value

    args = build_parser().parse_args(["tools", "list", "-c", "leaf.yaml"])
    assert args.config == "leaf.yaml"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic home + cwd: paths anchor to tmp_path (no config file found)."""
    monkeypatch.setenv("SYSBOT_HOME", str(tmp_path / ".sysbot"))
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "tools" / "greet"
    pkg.mkdir(parents=True)
    (pkg / "tool.py").write_text(TOOL)
    return tmp_path


def _run(argv: list[str]) -> int:
    return tool_cli.run(build_parser().parse_args(argv))


def test_list_shows_tool(env, capsys):
    assert _run(["tools", "list"]) == 0
    assert "greet" in capsys.readouterr().out


def test_disable_enable_persist_state(env):
    assert _run(["tools", "disable", "greet"]) == 0
    state = json.loads((env / "tool_state.json").read_text())
    assert state["disabled"] == ["greet"]

    assert _run(["tools", "enable", "greet"]) == 0
    state = json.loads((env / "tool_state.json").read_text())
    assert state["disabled"] == []


def test_unknown_tool_errors(env):
    assert _run(["tools", "enable", "nope"]) == 1
    assert _run(["tools", "info", "nope"]) == 1
    assert _run(["tools", "remove", "nope", "-y"]) == 1


def test_info(env, capsys):
    assert _run(["tools", "info", "greet"]) == 0
    out = capsys.readouterr().out
    assert "say hi" in out
    assert "package" in out


def test_remove_deletes_package_and_lock_entry(env):
    from sysbot.install.lockfile import LOCK_KEY, JsonState

    lock = JsonState(env / "tools.lock.json", LOCK_KEY)
    lock.save({"greet": {"repo": "acme/greet"}})

    assert _run(["tools", "remove", "greet", "-y"]) == 0
    assert not (env / "tools" / "greet").exists()
    assert lock.load() == {}


def test_remove_without_confirmation_aborts(env, monkeypatch):
    monkeypatch.setattr(tool_cli, "_confirm", lambda msg: False)
    assert _run(["tools", "remove", "greet"]) == 0
    assert (env / "tools" / "greet").exists()


def test_install_grammar():
    args = build_parser().parse_args(
        ["tools", "install", "acme/repo", "--ref", "v1", "--only", "a",
         "--only", "b", "--force", "-y", "--install-deps"]
    )
    assert (args.command, args.tool_cmd) == ("tools", "install")
    assert args.spec == "acme/repo" and args.ref == "v1"
    assert args.only == ["a", "b"] and args.force and args.yes and args.install_deps


def test_install_rejects_non_github_input(env, capsys):
    assert _run(["tools", "install", "gpu-temp"]) == 1
    assert "GitHub" in capsys.readouterr().out


def test_install_dispatches_to_installer(env, monkeypatch):
    import sysbot.install.manager as manager_mod
    from sysbot.install.spec import ToolSource

    calls = {}

    class FakeInstaller:
        def __init__(self, tools_dir, lock_path, *a, **kw):
            calls["paths"] = (tools_dir, lock_path)

        def install(self, src, **kw):
            calls["src"], calls["kw"] = src, kw
            return ["x"]

    monkeypatch.setattr(manager_mod, "ToolInstaller", FakeInstaller)
    assert _run(["tools", "install", "acme/repo@v2", "--yes"]) == 0
    assert calls["src"] == ToolSource("acme", "repo", ref="v2")
    assert calls["kw"]["yes"] is True
    assert calls["paths"] == (env / "tools", env / "tools.lock.json")


def test_list_shows_install_origin(env, capsys):
    from sysbot.install.lockfile import LOCK_KEY, JsonState

    JsonState(env / "tools.lock.json", LOCK_KEY).save(
        {"greet": {"repo": "acme/greet", "commit": "a" * 40}}
    )
    assert _run(["tools", "list", "--json"]) == 0
    out = capsys.readouterr().out
    assert "acme/greet@aaaaaaa" in out
