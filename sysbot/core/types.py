from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


# Signature: (user_id, tool_name, prompt, arguments) → approved
ConfirmCallback = Callable[[str, str, str, dict[str, Any]], Awaitable[bool]]


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


@dataclass
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return d


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        import json
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


@dataclass
class ConversationHistory:
    messages: list[Message] = field(default_factory=list)
    max_size: int = 50

    def add(self, message: Message) -> None:
        self.messages.append(message)
        if len(self.messages) > self.max_size:
            # Keep system message if present, trim oldest non-system
            system = [m for m in self.messages if m.role == Role.SYSTEM]
            rest = [m for m in self.messages if m.role != Role.SYSTEM]
            rest = rest[-(self.max_size - len(system)):]
            self.messages = system + rest

    def to_list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.messages]

    def clear(self) -> None:
        self.messages = []
