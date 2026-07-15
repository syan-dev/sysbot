from __future__ import annotations

from sysbot.core.agent import _EMPTY_REPLY_FALLBACK, Agent, _parse_args, _usage
from sysbot.core.config import Settings
from sysbot.core.types import ConversationHistory, Message, Role


def test_parse_args_positional() -> None:
    assert _parse_args(["a", "b"], ["x", "y"]) == {"x": "a", "y": "b"}


def test_parse_args_named() -> None:
    assert _parse_args(["x=a", "y=b"], ["x", "y"]) == {"x": "a", "y": "b"}


def test_parse_args_named_with_equals_in_value() -> None:
    # only the first `=` splits key/value
    assert _parse_args(["url=http://x?a=1"], ["url"]) == {"url": "http://x?a=1"}


def test_usage_lists_missing_params() -> None:
    info = {
        "name": "disk_usage",
        "description": "Check disk space",
        "param_names": ["path"],
        "required": ["path"],
    }
    text = _usage(info, ["path"])
    assert "Missing required parameter(s): path" in text
    assert "/disk_usage <path>" in text


def test_history_trims_but_keeps_system() -> None:
    history = ConversationHistory(max_size=3)
    history.add(Message(role=Role.SYSTEM, content="sys"))
    for i in range(5):
        history.add(Message(role=Role.USER, content=f"msg{i}"))

    roles = [m.role for m in history.messages]
    # system always retained
    assert roles[0] == Role.SYSTEM
    # total respects max_size
    assert len(history.messages) <= 3
    # oldest user messages trimmed, newest kept
    assert history.messages[-1].content == "msg4"


async def test_empty_llm_reply_falls_back(monkeypatch) -> None:
    # A reasoning model can finish a turn with no tool call and empty content
    # (everything went to its thinking channel). handle() must not return "",
    # which adapters like Telegram silently drop — it returns a fallback instead.
    settings = Settings()
    settings.logging.trace_file = None  # no file writes during the test
    agent = Agent(settings)

    async def fake_chat(messages, tools=None, on_token=None, on_reasoning=None):
        return Message(role=Role.ASSISTANT, content="   \n")

    monkeypatch.setattr(agent._llm, "chat", fake_chat)

    reply = await agent.handle("u1", "current speed internet")
    assert reply == _EMPTY_REPLY_FALLBACK


async def test_nonempty_llm_reply_passes_through(monkeypatch) -> None:
    settings = Settings()
    settings.logging.trace_file = None
    agent = Agent(settings)

    async def fake_chat(messages, tools=None, on_token=None, on_reasoning=None):
        return Message(role=Role.ASSISTANT, content="Download: 61 Mbps")

    monkeypatch.setattr(agent._llm, "chat", fake_chat)

    reply = await agent.handle("u1", "current speed internet")
    assert reply == "Download: 61 Mbps"
