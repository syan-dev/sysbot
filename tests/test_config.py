from __future__ import annotations

from pathlib import Path

from sysbot.core.config import Settings, resolve_paths


def test_defaults() -> None:
    s = Settings()
    assert s.messaging.provider == "cli"
    assert s.llm.base_url == "http://localhost:11434/v1"
    assert s.llm.model == "llama3.2"


def test_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "llm:\n"
        "  model: qwen3.5\n"
        "  base_url: http://localhost:8000/v1\n"
        "messaging:\n"
        "  provider: telegram\n"
    )
    s = Settings.from_yaml(cfg)
    assert s.llm.model == "qwen3.5"
    assert s.llm.base_url == "http://localhost:8000/v1"
    assert s.messaging.provider == "telegram"
    # unset fields fall back to defaults
    assert s.llm.temperature == 0.7


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SYSBOT_LLM__MODEL", "from-env")
    monkeypatch.setenv("SYSBOT_AGENT__MAX_HISTORY", "123")
    s = Settings()
    assert s.llm.model == "from-env"
    assert s.agent.max_history == 123


def test_missing_yaml_uses_defaults(tmp_path: Path) -> None:
    s = Settings.from_yaml(tmp_path / "does-not-exist.yaml")
    assert s.llm.model == "llama3.2"


def test_config_dir_tracks_source(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  model: qwen3.5\n")
    s = Settings.from_yaml(cfg)
    assert s.config_dir == tmp_path.resolve()
    # Built-in defaults have no source file.
    assert Settings().config_dir is None


def test_resolve_paths_anchors_to_config_dir(tmp_path: Path) -> None:
    # Relative tools/log/state paths anchor next to the loaded config — the
    # `sysbot tools` CLI and the bot must resolve the exact same locations.
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm:\n  model: qwen3.5\n")
    s = Settings.from_yaml(cfg)
    resolve_paths(s)
    assert s.mcp.tools_dir == str(tmp_path / "tools")
    assert s.mcp.lock_file == str(tmp_path / "tools.lock.json")
    assert s.dashboard.state_file == str(tmp_path / "tool_state.json")


def test_load_picks_up_user_dir(tmp_path: Path, monkeypatch) -> None:
    # SYSBOT_HOME points user_dir() at a temp dir holding config.yaml; with no
    # cwd config.yaml and no explicit -c, load() should resolve it from there.
    home = tmp_path / ".sysbot"
    home.mkdir()
    (home / "config.yaml").write_text("llm:\n  model: from-user-dir\n")
    monkeypatch.setenv("SYSBOT_HOME", str(home))
    monkeypatch.chdir(tmp_path)  # tmp_path has no config.yaml of its own

    s = Settings.load()
    assert s.llm.model == "from-user-dir"
    assert s.config_dir == home.resolve()
