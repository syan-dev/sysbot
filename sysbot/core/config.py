from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramConfig(BaseModel):
    token: str = ""
    allowed_user_ids: list[int] = Field(default_factory=list)


class SlackConfig(BaseModel):
    bot_token: str = ""
    app_token: str = ""


class MessagingConfig(BaseModel):
    provider: str = "cli"  # cli | telegram | slack
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3.2"
    api_key: str = "ollama"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0


class MCPConfig(BaseModel):
    tools_dir: str = "./tools"
    hot_reload: bool = True
    # Lock file recording where installed tool packages came from
    # (`sysbot tools install`): repo, pinned commit, version. Relative paths
    # anchor to the config dir (so ~/.sysbot/tools.lock.json when installed).
    lock_file: str = "tools.lock.json"


class AgentConfig(BaseModel):
    system_prompt: str = (
        "You are a helpful assistant with access to tools. "
        "Use tools when they help answer the user's question. "
        "Be concise and clear."
    )
    max_history: int = 50
    max_tool_calls: int = 10


class DashboardConfig(BaseModel):
    # Off by default — opt in with `--dashboard` or `enabled: true`. Binds to
    # localhost with no auth (single-user local tool); change `host` deliberately.
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    # Persisted set of disabled tools. Relative paths anchor to the config dir
    # (so ~/.sysbot/tool_state.json for an installed setup), like tools_dir/logs.
    state_file: str | None = "tool_state.json"


class LogConfig(BaseModel):
    level: str = "INFO"
    file: str | None = "logs/sysbot.log"
    trace_file: str | None = "logs/traces.jsonl"
    # Time-based rotation for both the log and the trace file (applied via
    # TimedRotatingFileHandler). `when` is the rollover interval ("midnight",
    # "H", "D", "W0".."W6", …); `backup_count` is how many rotated files to keep.
    when: str = "midnight"
    backup_count: int = 7


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYSBOT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    messaging: MessagingConfig = Field(default_factory=MessagingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    logging: LogConfig = Field(default_factory=LogConfig)

    # Absolute path of the config.yaml this instance was loaded from (None when
    # running on built-in defaults). Relative `tools/`/`logs/` paths are anchored
    # to its directory so they live next to the config the user edits.
    _config_path: Path | None = PrivateAttr(default=None)

    @property
    def config_dir(self) -> Path | None:
        """Directory the active config.yaml was loaded from, or None for defaults."""
        return self._config_path.parent if self._config_path else None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        data: dict[str, Any] = {}
        p = Path(path)
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
        settings = cls.model_validate(data)
        if p.exists():
            settings._config_path = p.resolve()
        return settings

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Settings":
        from sysbot.core.paths import app_dir, user_dir

        base = app_dir()
        candidates = [
            config_path,
            Path("config.yaml"),
            user_dir() / "config.yaml",      # ~/.sysbot/config.yaml — installed default
            base / "config.yaml",            # next to the .exe in a frozen build
            Path("config/default.yaml"),
            base / "config" / "default.yaml",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return cls.from_yaml(candidate)
        return cls()


def resolve_paths(settings: Settings) -> None:
    """Anchor relative paths to the directory the active config.yaml was loaded
    from, so `tools/`, `logs/` and the state files live next to the config the
    user edits — e.g. ~/.sysbot for an installed setup. When no config file was
    found (built-in defaults), `config_dir` is None and `anchor()` falls back to
    the app directory: the CWD for a normal run, or the folder containing the
    frozen .exe. Shared by the bot startup and the `sysbot tools` CLI so both
    resolve the exact same tools dir.
    """
    from sysbot.core.paths import anchor

    base = settings.config_dir
    settings.mcp.tools_dir = anchor(settings.mcp.tools_dir, base)
    settings.mcp.lock_file = anchor(settings.mcp.lock_file, base)
    if settings.logging.file:
        settings.logging.file = anchor(settings.logging.file, base)
    if settings.logging.trace_file:
        settings.logging.trace_file = anchor(settings.logging.trace_file, base)
    if settings.dashboard.state_file:
        settings.dashboard.state_file = anchor(settings.dashboard.state_file, base)
