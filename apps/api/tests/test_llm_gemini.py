from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from api.core.config import settings
from api.llm.client import LLMClientError, LLMPolicyViolationError
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


async def test_generate_wraps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        raise httpx.ConnectTimeout("timed out")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMClientError):
        async for _ in client.generate("hi"):
            pass


async def test_generate_raises_policy_violation_on_blocked_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def _iter() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                text=None,
                prompt_feedback=genai_types.GenerateContentResponsePromptFeedback(
                    block_reason=genai_types.BlockedReason.SAFETY
                ),
                candidates=None,
            )

        return _iter()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    with pytest.raises(LLMPolicyViolationError):
        async for _ in client.generate("hi"):
            pass


async def test_generate_raises_policy_violation_on_blocked_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def _iter() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(text="some ", prompt_feedback=None, candidates=None)
            yield SimpleNamespace(
                text=None,
                prompt_feedback=None,
                candidates=[genai_types.Candidate(finish_reason=genai_types.FinishReason.SAFETY)],
            )

        return _iter()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    tokens: list[str] = []
    with pytest.raises(LLMPolicyViolationError):
        async for token in client.generate("hi"):
            tokens.append(token)

    assert tokens == ["some "]


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


async def test_generate_structured_without_images_sends_plain_string_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _JudgmentResult(triggered=True, ending_id=None)
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=generate_content)

    await client.generate_structured("judge this", _JudgmentResult)

    assert received["contents"] == "judge this"


async def test_generate_structured_with_images_sends_multimodal_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _JudgmentResult(triggered=True, ending_id=None)
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return SimpleNamespace(parsed=expected)

    client = _make_client(monkeypatch, generate_content=generate_content)

    await client.generate_structured(
        "judge this",
        _JudgmentResult,
        images=[(b"fake-png-bytes", "image/png"), (b"fake-jpeg-bytes", "image/jpeg")],
    )

    contents = received["contents"]
    assert contents[0] == "judge this"
    assert len(contents) == 3
    assert contents[1].inline_data.data == b"fake-png-bytes"
    assert contents[1].inline_data.mime_type == "image/png"
    assert contents[2].inline_data.data == b"fake-jpeg-bytes"
    assert contents[2].inline_data.mime_type == "image/jpeg"


async def test_generate_sends_a_runaway_backstop_and_forwards_the_stop_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """대화 생성에는 오랫동안 `GenerateContentConfig` 가 전혀 붙지 않아 출력 상한이 없었다 —
    폭주 응답에 천장이 없는 구조였다. `stop_sequences`는 이제 호출부가 화자 라벨에서
    파생시켜 넘긴다(prompt-db-goal-prompt.md §4-5) — 이 계층은 그 값을 그대로
    `GenerateContentConfig`에 전달하는지만 본다(넘기지 않으면 `None`)."""
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    assert [token async for token in client.generate("hi", stop_sequences=["\n사용자:"])] == ["네"]

    config = captured["config"]
    assert config.max_output_tokens == settings.gemini_max_output_tokens
    assert config.stop_sequences == ["\n사용자:"]
    # 상한이 설정에서 온다는 것까지 봐야 한다 — 리터럴을 그대로 두면 값을 올린 커밋이
    # 테스트만 깨고 배선이 끊긴 것은 못 잡는다(사고형 모델에서는 이 값이 절단을 가른다).
    monkeypatch.setattr(settings, "gemini_max_output_tokens", 4242)
    assert [token async for token in client.generate("hi", stop_sequences=["\n사용자:"])] == ["네"]

    assert [token async for token in client.generate("hi")] == ["네"]
    assert captured["config"].stop_sequences is None
    assert captured["config"].max_output_tokens == 4242


async def test_generate_forwards_the_system_instruction_to_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """바닥 지시문은 프롬프트 본문이 아니라 `system_instruction` 으로 가야 한다 — 본문에 이어
    붙이면 작품 설정과 같은 층에 놓여 우선순위(수위 항목이 작품 설정을 이긴다)가 사라진다.
    넘기지 않으면 None 이 그대로 실려 예전 호출 페이로드와 같아야 한다."""
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)

    assert [token async for token in client.generate("hi", "너는 화자다")] == ["네"]
    assert captured["config"].system_instruction == "너는 화자다"
    assert captured["contents"] == "hi", "지시문이 프롬프트 본문에 섞이면 안 된다"

    assert [token async for token in client.generate("hi")] == ["네"]
    assert captured["config"].system_instruction is None


async def test_generate_omits_seed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gemini_seed` 기본값 None 이면 config.seed 가 아예 안 실려야 한다(호출 페이로드가
    지금과 동일해야 하는 것이 이 필드의 성공 기준, chat-techspec.md §3-1)."""
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)
    monkeypatch.setattr(settings, "gemini_seed", None)

    assert [token async for token in client.generate("hi")] == ["네"]
    assert captured["config"].seed is None


async def test_generate_sets_seed_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def generate_content_stream(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured.update(kwargs)
        return _chunks("네")

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)
    monkeypatch.setattr(settings, "gemini_seed", 42)

    assert [token async for token in client.generate("hi")] == ["네"]
    assert captured["config"].seed == 42


async def test_generate_logs_when_the_response_is_cut_off_at_the_token_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """상한에 걸리면 문장 중간에서 잘린 응답이 그대로 사용자에게 간다 — 화면상으로는 그냥
    "말을 하다 말았다"로만 보이므로, 상한이 너무 낮은지 판단할 근거를 로그에 남겨야 한다."""

    async def generate_content_stream(**_: Any) -> AsyncIterator[SimpleNamespace]:
        async def stream() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                text="말을 하다",
                candidates=[SimpleNamespace(finish_reason=genai_types.FinishReason.MAX_TOKENS)],
            )

        return stream()

    client = _make_client(monkeypatch, generate_content_stream=generate_content_stream)
    warnings: list[str] = []
    monkeypatch.setattr(
        "api.llm.gemini.logger",
        SimpleNamespace(warning=lambda message, *args: warnings.append(message % args)),
    )

    tokens = [token async for token in client.generate("hi")]

    assert tokens == ["말을 하다"]
    assert warnings == [
        f"Gemini 응답이 max_output_tokens({settings.gemini_max_output_tokens})에서 잘렸다"
    ]
