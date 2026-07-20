from __future__ import annotations

import pytest

from lesysbot.core.config import LLMConfig
from lesysbot.llm.client import LLMClient


class _Model:
    def __init__(self, id: str) -> None:
        self.id = id


class _Models:
    def __init__(self, ids, error=None) -> None:
        self._ids = ids
        self._error = error

    async def list(self):
        if self._error:
            raise self._error
        return type("R", (), {"data": [_Model(i) for i in self._ids]})()


class _FakeClient:
    """Stands in for AsyncOpenAI: supports with_options(...).models.list()."""

    def __init__(self, ids, error=None) -> None:
        self.models = _Models(ids, error)

    def with_options(self, **_kwargs):
        return self


def _client(ids, error=None) -> LLMClient:
    c = LLMClient(LLMConfig(model="llama3.2"))
    c._client = _FakeClient(ids, error)  # type: ignore[assignment]
    return c


@pytest.mark.asyncio
async def test_health_ok_model_available() -> None:
    health = await _client(["llama3.2", "qwen3"]).health()
    assert health["ok"] is True
    assert health["model_available"] is True
    assert "latency_ms" in health
    assert health["model"] == "llama3.2"


@pytest.mark.asyncio
async def test_health_ok_model_missing() -> None:
    health = await _client(["other-model"]).health()
    assert health["ok"] is True
    assert health["model_available"] is False


@pytest.mark.asyncio
async def test_health_unreachable() -> None:
    health = await _client([], error=ConnectionError("refused")).health()
    assert health["ok"] is False
    assert "refused" in health["error"]
    assert health["base_url"]
