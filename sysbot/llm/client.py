from __future__ import annotations

import json
import logging
from typing import Any, Callable

from openai import AsyncOpenAI

from sysbot.core.config import LLMConfig
from sysbot.core.types import Message, Role, ToolCall

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI-compatible client — works with Ollama, vLLM, LlamaCpp, OpenAI."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ) -> Message:
        """Send a chat request, streaming answer text via on_token and (for
        reasoning models that expose it) chain-of-thought via on_reasoning."""
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug("LLM request: model=%s, messages=%d", self._config.model, len(messages))

        content_parts: list[str] = []
        tool_call_acc: dict[int, dict[str, str]] = {}

        response = await self._client.chat.completions.create(**kwargs)
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Some OpenAI-compatible reasoning models stream chain-of-thought in a
            # separate `reasoning_content` field (not part of the final message).
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning and on_reasoning:
                on_reasoning(reasoning)

            if delta.content:
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    i = tc.index
                    if i not in tool_call_acc:
                        tool_call_acc[i] = {"id": "", "name": "", "args": ""}
                    if tc.id:
                        tool_call_acc[i]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_call_acc[i]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_call_acc[i]["args"] += tc.function.arguments

        tool_calls = None
        if tool_call_acc:
            tool_calls = [
                ToolCall(
                    id=v["id"],
                    name=v["name"],
                    arguments=json.loads(v["args"] or "{}"),
                )
                for _, v in sorted(tool_call_acc.items())
            ]

        return Message(
            role=Role.ASSISTANT,
            content="".join(content_parts),
            tool_calls=tool_calls,
        )
