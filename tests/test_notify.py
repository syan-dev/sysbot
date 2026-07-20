"""Out-of-band push messages (`core/notify.py`) — the side channel tools use
to message the user after their reply (e.g. the power tool's "powering off
now" heads-up)."""
from __future__ import annotations

import asyncio

import pytest

from lesysbot.core import notify
from lesysbot.core.agent import Agent
from lesysbot.core.config import Settings
from lesysbot.mcp import tool


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, user_id: str, text: str) -> None:
        self.sent.append((user_id, text))


@pytest.fixture
def sender():
    rec = Recorder()
    notify.set_sender(rec)
    yield rec
    notify.set_sender(None)


async def test_notify_later_sends_to_current_user(sender) -> None:
    notify.set_current_user("u1")
    task = notify.notify_later("bye", 0.0)
    assert task is not None
    await task
    assert sender.sent == [("u1", "bye")]


async def test_notify_later_noop_without_sender() -> None:
    notify.set_current_user("u1")
    assert notify.notify_later("bye", 0.0) is None


async def test_notify_later_noop_without_user(sender) -> None:
    # Fresh task context — set_current_user was never called here.
    assert notify.notify_later("bye", 0.0) is None
    assert sender.sent == []


async def test_cancelled_task_never_sends(sender) -> None:
    notify.set_current_user("u1")
    task = notify.notify_later("bye", 0.05)
    assert task is not None
    task.cancel()
    await asyncio.sleep(0.1)
    assert sender.sent == []


async def test_agent_stamps_requesting_user(sender) -> None:
    # A tool that schedules a push must reach the user whose message triggered
    # it — Agent.handle stamps the requester before dispatch (slash path here).
    settings = Settings()
    settings.logging.trace_file = None
    agent = Agent(settings)

    @tool(description="schedule a delayed push")
    async def announce() -> str:
        notify.notify_later("done", 0.0)
        return "scheduled"

    agent.registry.register_callable(announce)

    reply = await agent.handle("u42", "/announce")
    assert reply == "scheduled"
    await asyncio.sleep(0.05)
    assert sender.sent == [("u42", "done")]
