from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import Any, Callable

from watchfiles import awatch

from sysbot.core.config import Settings
from sysbot.core.trace import TraceWriter
from sysbot.core.types import ConfirmCallback, ConversationHistory, Message, Role
from sysbot.llm.client import LLMClient
from sysbot.mcp.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """Orchestrates the message → LLM → tools → reply loop."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = LLMClient(settings.llm)
        self._registry = ToolRegistry()
        self._histories: dict[str, ConversationHistory] = {}
        self._reload_lock = asyncio.Lock()
        self._confirm_fn: ConfirmCallback | None = None
        self._tracer: TraceWriter | None = (
            TraceWriter(
                settings.logging.trace_file,
                when=settings.logging.when,
                backup_count=settings.logging.backup_count,
            )
            if settings.logging.trace_file
            else None
        )

    def set_confirm_fn(self, fn: ConfirmCallback) -> None:
        self._confirm_fn = fn

    async def setup(self) -> None:
        self._registry.load_directory(self._settings.mcp.tools_dir)
        logger.info("Tools loaded: %s", self._registry.names)

        if self._settings.mcp.hot_reload:
            asyncio.create_task(self._watch_tools())

    async def _watch_tools(self) -> None:
        tools_path = Path(self._settings.mcp.tools_dir)
        if not tools_path.exists():
            return
        logger.info("Watching %s for tool changes...", tools_path)
        async for _ in awatch(tools_path, watch_filter=_py_files_only):
            async with self._reload_lock:
                logger.info("Tool files changed — reloading...")
                self._registry.reload(tools_path)

    def _get_history(self, user_id: str) -> ConversationHistory:
        if user_id not in self._histories:
            h = ConversationHistory(max_size=self._settings.agent.max_history)
            h.add(Message(role=Role.SYSTEM, content=self._settings.agent.system_prompt))
            self._histories[user_id] = h
        return self._histories[user_id]

    async def handle(
        self,
        user_id: str,
        text: str,
        on_token: Callable[[str], None] | None = None,
        *,
        on_reasoning: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> str:
        if text.startswith("/"):
            return await self._handle_slash(text, user_id)

        history = self._get_history(user_id)
        history.add(Message(role=Role.USER, content=text))

        tools = self._registry.get_openai_schemas()
        max_tool_calls = self._settings.agent.max_tool_calls

        trace = (
            self._tracer.start(user_id, text, self._settings.llm.model)
            if self._tracer
            else None
        )

        try:
            for _ in range(max_tool_calls + 1):
                messages = history.to_list()
                if trace:
                    trace.begin_llm(len(messages))

                if on_status:
                    on_status("Thinking…")

                # Pass on_token only for potential final text response;
                # tool-call iterations produce no text so it won't fire there.
                response = await self._llm.chat(
                    messages,
                    tools=tools or None,
                    on_token=on_token,
                    on_reasoning=on_reasoning,
                )
                history.add(response)

                if not response.tool_calls:
                    if trace:
                        trace.end_llm("text")
                        trace.finish(response.content)
                    return response.content

                if trace:
                    trace.end_llm("tool_calls")

                if on_status:
                    names = ", ".join(tc.name for tc in response.tool_calls)
                    on_status(f"Running {names}…")

                # Execute tool calls — sequential when any needs confirmation,
                # parallel otherwise.
                any_needs_confirm = self._confirm_fn and any(
                    (self._registry.get_tool_meta(tc.name) or {}).get("confirm")
                    for tc in response.tool_calls
                )

                if any_needs_confirm:
                    outcomes: list[tuple[str, float]] = []
                    for tc in response.tool_calls:
                        meta = self._registry.get_tool_meta(tc.name) or {}
                        confirm_val = meta.get("confirm")
                        if confirm_val and self._confirm_fn:
                            prompt = (
                                confirm_val
                                if isinstance(confirm_val, str)
                                else f"Run `{tc.name}`?"
                            )
                            approved = await self._confirm_fn(
                                user_id, tc.name, prompt, tc.arguments
                            )
                            if not approved:
                                outcomes.append(("Cancelled by user.", 0.0))
                                continue
                        outcomes.append(await _timed_tool(self._registry, tc.name, tc.arguments))
                else:
                    outcomes = list(
                        await asyncio.gather(
                            *[
                                _timed_tool(self._registry, tc.name, tc.arguments)
                                for tc in response.tool_calls
                            ]
                        )
                    )

                for tc, (result, duration_ms) in zip(response.tool_calls, outcomes):
                    if trace:
                        trace.add_tool(tc.name, tc.arguments, result, duration_ms)
                    history.add(Message(role=Role.TOOL, content=result, tool_call_id=tc.id))

        except Exception as e:
            # Handled, user-facing condition (e.g. backend unreachable) — keep the
            # console clean with a one-line error; full traceback only under -v/DEBUG.
            logger.error("LLM error: %s", e)
            logger.debug("LLM error detail", exc_info=True)
            if trace:
                trace.finish("", error=str(e))
            return (
                f"LLM unavailable: {e}\n\n"
                "You can still use tools directly — type /help to see available commands."
            )

        reply = "I reached the maximum number of tool calls. Please try rephrasing."
        if trace:
            trace.finish(reply)
        return reply

    async def _handle_slash(self, text: str, user_id: str) -> str:
        """Dispatch a /command directly to a tool or built-in — no LLM needed."""
        try:
            parts = shlex.split(text[1:])
        except ValueError:
            parts = text[1:].split()

        if not parts:
            return self._registry.list_tools_text()

        cmd = parts[0].lower()
        raw_args = parts[1:]

        # Built-in meta-commands
        if cmd in ("help", "tools"):
            return self._registry.list_tools_text()

        if cmd == "clear":
            self.clear_history(user_id)
            return "Conversation history cleared."

        if cmd == "history":
            return self._format_history(user_id)

        # Tool dispatch
        info = self._registry.get_tool_info(cmd)
        if info is None:
            return (
                f"Unknown command: /{cmd}\n\n"
                + self._registry.list_tools_text()
            )

        kwargs = _parse_args(raw_args, info["param_names"])

        missing = [p for p in info["required"] if p not in kwargs]
        if missing:
            return _usage(info, missing)

        return await self._registry.call(cmd, kwargs)

    def _format_history(self, user_id: str) -> str:
        history = self._histories.get(user_id)
        if not history or not history.messages:
            return "No conversation history."
        lines = []
        for msg in history.messages:
            if msg.role == Role.SYSTEM:
                continue
            label = msg.role.value.upper()
            body = msg.content
            if len(body) > 300:
                body = body[:300] + "…"
            lines.append(f"{label}: {body}")
        return "\n\n".join(lines) if lines else "No messages yet."

    def clear_history(self, user_id: str) -> None:
        self._histories.pop(user_id, None)


def _py_files_only(change: object, path: str) -> bool:
    return path.endswith(".py")


async def _timed_tool(
    registry: ToolRegistry, name: str, arguments: dict[str, Any]
) -> tuple[str, float]:
    t0 = time.perf_counter()
    result = await registry.call(name, arguments)
    return result, (time.perf_counter() - t0) * 1000


def _parse_args(raw: list[str], param_names: list[str]) -> dict[str, Any]:
    """Map raw string tokens to tool parameter names.

    Supports two styles:
      named:      key=value  or  key="value with spaces"
      positional: values are assigned to params in declaration order
    """
    if raw and "=" in raw[0]:
        kwargs: dict[str, Any] = {}
        for token in raw:
            k, _, v = token.partition("=")
            kwargs[k.strip()] = v.strip()
        return kwargs
    # positional
    return {name: val for name, val in zip(param_names, raw)}


def _usage(info: dict[str, Any], missing: list[str]) -> str:
    params = info["param_names"]
    required = info["required"]
    parts = [f"<{p}>" if p in required else f"[{p}]" for p in params]
    sig = " ".join(parts)
    lines = [
        f"Missing required parameter(s): {', '.join(missing)}",
        "",
        f"Usage: /{info['name']} {sig}".rstrip(),
        f"  {info['description']}",
    ]
    if len(params) > 1:
        lines += ["", "You can also use named parameters:  key=value"]
    return "\n".join(lines)
