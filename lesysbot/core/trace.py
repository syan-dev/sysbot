from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolEvent:
    name: str
    args: dict[str, Any]
    result: str
    duration_ms: float


@dataclass
class LLMTurn:
    index: int
    model: str
    message_count: int
    duration_ms: float = 0.0
    response_type: str = "text"
    tool_calls: list[ToolEvent] = field(default_factory=list)


@dataclass
class Trace:
    trace_id: str
    user_id: str
    user_input: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    turns: list[LLMTurn] = field(default_factory=list)
    reply: str = ""
    total_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "input": self.user_input,
            "turns": [
                {
                    "index": t.index,
                    "model": t.model,
                    "messages": t.message_count,
                    "response_type": t.response_type,
                    "ms": round(t.duration_ms, 1),
                    "tools": [
                        {
                            "name": tc.name,
                            "args": tc.args,
                            "result": tc.result[:2000],
                            "ms": round(tc.duration_ms, 1),
                        }
                        for tc in t.tool_calls
                    ],
                }
                for t in self.turns
            ],
            "reply": self.reply[:2000],
            "total_ms": round(self.total_ms, 1),
            **({"error": self.error} if self.error else {}),
        }


class TraceWriter:
    """Appends one JSON line per completed request to a JSONL file, with
    time-based rotation (keeps `backup_count` dated files, e.g.
    traces.jsonl.2026-06-21) so it can't grow without bound."""

    def __init__(
        self, path: str | Path, when: str = "midnight", backup_count: int = 7
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Reuse logging's TimedRotatingFileHandler for rollover. A dedicated,
        # non-propagating logger keeps these JSON lines out of the app log/console.
        self._logger = logging.getLogger("lesysbot.traces")
        self._logger.handlers.clear()
        self._logger.propagate = False
        self._logger.setLevel(logging.INFO)
        handler = TimedRotatingFileHandler(
            self._path, when=when, backupCount=backup_count, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)

    def write(self, trace: Trace) -> None:
        try:
            self._logger.info(json.dumps(trace.to_dict(), ensure_ascii=False))
        except OSError:
            logger.exception("Failed to write trace to %s", self._path)

    def start(self, user_id: str, user_input: str, model: str) -> ActiveTrace:
        return ActiveTrace(self, user_id, user_input, model)


class ActiveTrace:
    """Accumulates events for a single Agent.handle() call, then flushes on finish()."""

    def __init__(self, writer: TraceWriter, user_id: str, user_input: str, model: str) -> None:
        self._writer = writer
        self._model = model
        self._trace = Trace(
            trace_id=uuid.uuid4().hex[:12],
            user_id=user_id,
            user_input=user_input,
        )
        self._t0 = time.perf_counter()
        self._turn_t0: float = 0.0

    def begin_llm(self, message_count: int) -> None:
        index = len(self._trace.turns) + 1
        self._trace.turns.append(
            LLMTurn(index=index, model=self._model, message_count=message_count)
        )
        self._turn_t0 = time.perf_counter()

    def end_llm(self, response_type: str) -> None:
        if self._trace.turns:
            turn = self._trace.turns[-1]
            turn.response_type = response_type
            turn.duration_ms = (time.perf_counter() - self._turn_t0) * 1000

    def add_tool(
        self,
        name: str,
        args: dict[str, Any],
        result: str,
        duration_ms: float,
    ) -> None:
        if self._trace.turns:
            self._trace.turns[-1].tool_calls.append(
                ToolEvent(name=name, args=args, result=result, duration_ms=duration_ms)
            )

    def finish(self, reply: str, error: str | None = None) -> None:
        self._trace.reply = reply
        self._trace.error = error
        self._trace.total_ms = (time.perf_counter() - self._t0) * 1000
        logger.debug(
            "trace=%s turns=%d total_ms=%.0f error=%s",
            self._trace.trace_id,
            len(self._trace.turns),
            self._trace.total_ms,
            error,
        )
        self._writer.write(self._trace)
