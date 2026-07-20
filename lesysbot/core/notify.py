"""Out-of-band push messages to the requesting user.

Replies normally travel back as `Agent.handle`'s return value, so a tool has no
way to say anything *after* it has returned — e.g. the power tool's "powering
off now" heads-up just before a scheduled shutdown fires. This module is that
side channel:

- `__main__._run` wires the active adapter's `send()` in via `set_sender()`.
- `Agent.handle` stamps the requesting user on a `ContextVar` before dispatch.
  `asyncio.create_task` copies the current context, so a task spawned inside a
  tool still sees the right user even after `handle()` has returned.
- Tools call `notify_later(text, delay)` (re-exported from `lesysbot.mcp`) to
  schedule a one-off message to that user. It returns the `asyncio.Task` so the
  caller can cancel the announcement (e.g. when the shutdown itself is
  cancelled).

Everything is best-effort: with no sender wired (tests, library use) or no
known user, scheduling is a no-op returning ``None``, and a failed send is
logged, never raised.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

Sender = Callable[[str, str], Awaitable[None]]

_sender: Sender | None = None
_current_user: ContextVar[str | None] = ContextVar("lesysbot_notify_user", default=None)


def set_sender(sender: Sender | None) -> None:
    """Wire the active messaging adapter's `send` (pass None to unwire)."""
    global _sender
    _sender = sender


def set_current_user(user_id: str) -> None:
    """Record who the agent is currently handling — called by `Agent.handle`."""
    _current_user.set(user_id)


def notify_later(text: str, delay: float) -> asyncio.Task | None:
    """Send `text` to the requesting user `delay` seconds from now.

    Returns the scheduled task (cancel it to drop the announcement), or None
    when no adapter is wired or no user is known.
    """
    user_id = _current_user.get()
    if user_id is None or _sender is None:
        logger.debug(
            "notify_later dropped (user=%r, sender wired=%s)", user_id, _sender is not None
        )
        return None
    return asyncio.create_task(_deliver(user_id, text, delay))


async def _deliver(user_id: str, text: str, delay: float) -> None:
    await asyncio.sleep(delay)
    sender = _sender
    if sender is None:
        return
    try:
        await sender(user_id, text)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Delayed notify to %s failed: %s", user_id, exc)
