from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel

from api.llm.client import LLMClientError
from api.llm.gemini import GeminiLLMClient


class _JudgmentResult(BaseModel):
    triggered: bool
    ending_id: str | None


def _make_client(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> GeminiLLMClient:
    client = GeminiLLMClient(api_key="test-key")
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(**overrides)))
    monkeypatch.setattr(client, "_client", fake_client)
    return client


async def _chunks(*texts: str) -> AsyncIterator[SimpleNamespace]:
    for text in texts:
        yield SimpleNamespace(text=text)


def _api_error() -> genai_errors.APIError:
    return genai_errors.APIError(code=503, response_json={"error": {"message": "unavailable"}})


async def test_generate_relays_stream_chunks_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        return _chunks("Hello", ", ", "world")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    tokens = [token async for token in client.generate("hi")]

    assert tokens == ["Hello", ", ", "world"]


async def test_generate_skips_empty_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        return _chunks("a", "", "b")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    tokens = [token async for token in client.generate("hi")]

    assert tokens == ["a", "b"]


async def test_generate_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise _api_error()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMClientError):
        async for _ in client.generate("hi"):
            pass


async def test_generate_structured_returns_deserialized_model(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _JudgmentResult(triggered=True, ending_id="ending-1")

    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=generate_content)

    result = await client.generate_structured("judge this", _JudgmentResult)

    assert result == expected


async def test_generate_structured_raises_when_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(parsed=None)

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_structured("judge this", _JudgmentResult)


async def test_generate_structured_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        raise _api_error()

    client = _make_client(monkeypatch, generate_content=generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_structured("judge this", _JudgmentResult)
