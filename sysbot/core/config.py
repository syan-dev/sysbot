from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
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


class AgentConfig(BaseModel):
    system_prompt: str = (
        "You are a helpful assistant with access to tools. "
        "Use tools when they help answer the user's question. "
        "Be concise and clear."
    )
    max_history: int = 50
    max_tool_calls: int = 10


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
    logging: LogConfig = Field(default_factory=LogConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        data: dict[str, Any] = {}
        p = Path(path)
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
        return cls.model_validate(data)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Settings":
        from sysbot.core.paths import app_dir

        base = app_dir()
        candidates = [
            config_path,
            Path("config.yaml"),
            base / "config.yaml",            # next to the .exe in a frozen build
            Path("config/default.yaml"),
            base / "config" / "default.yaml",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return cls.from_yaml(candidate)
        return cls()
