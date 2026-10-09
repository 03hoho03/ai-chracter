"""Anthropic API 로 바로 보내는 Claude 구현.

배정(`LLM_CALL_SITE_BACKENDS`)이 상위 모델 호출을 이 구현으로 옮길 때만 닿는다. 이 경로의 모델은 사고를 끌 수 없어
(`thinking` 을 보내면 거부된다) 요청에 `thinking` 을 싣지 않고 사고 깊이만 `output_config.effort` 로 고른다. 실패·사용량
규칙은 Bedrock 구현과 같고, 사고가 출력 상한을 다 써 본문이 하나도 나오지 않은 경우만 따로 실패로 올린다.
"""

import json
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel

from api.chat.turn_judgments import _llm_dependency_tag
from api.core.config import settings
from api.llm import anthropic_api as anthropic_module
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.client import (
    LLMCallContext,
    LLMClientError,
    LLMEmptyResponseError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
    SegmentedPrompt,
)
from api.llm.pricing import MODEL_PRICES, ModelPrice

_CHAT = LLMCallContext("chat_generate", None, None, model="opus")
_REPLAY = LLMCallContext("replay_generate", None, None, model="sonnet")
_CHAPTER = LLMCallContext("novelize_chapter", None, None, model="opus")
_KEY = "sk-ant-test"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_direct_api_key", _KEY)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    calls: list[tuple[str, str, Any]] = []

    async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
        calls.append((call_site, model, usage_metadata))

    monkeypatch.setattr(anthropic_module, "record_usage", record_usage)
    return calls


def _usage(input_tokens: int = 0, read: int | None = None, write: int | None = None, output: int = 0) -> Any:
    return SimpleNamespace(
        input_tokens=input_tokens,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
        output_tokens=output,
    )


def _start(**usage: Any) -> Any:
    return SimpleNamespace(type="message_start", message=SimpleNamespace(usage=_usage(**usage)))


def _text(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


# 사고 블록. 기본 표시가 생략이라 사고 글은 비어 오고, 서명이 따라온다.
_THINKING = (
    SimpleNamespace(type="content_block_start", index=0, content_block=SimpleNamespace(type="thinking", thinking="")),
    SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking="")),
    SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="signature_delta", signature="sig")),
    SimpleNamespace(type="content_block_stop", index=0),
)


def _end(stop_reason: str = "end_turn", output: int = 5, thinking: int | None = None) -> Any:
    details = None if thinking is None else SimpleNamespace(thinking_tokens=thinking)
    return SimpleNamespace(
        type="message_delta",
        delta=SimpleNamespace(stop_reason=stop_reason),
        usage=SimpleNamespace(
            output_tokens=output,
            input_tokens=None,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
            output_tokens_details=details,
        ),
    )


def _client_streaming(
    monkeypatch: pytest.MonkeyPatch, *events: Any, raise_at: BaseException | None = None
) -> tuple[AnthropicLLMClient, list[dict[str, Any]]]:
    """SDK 경계(`messages.create(stream=True)`)만 가짜로 둔다. `raise_at` 은 이벤트를 다 보낸 뒤 스트림 도중에 낸다."""
    seen: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> AsyncIterator[Any]:
        seen.append(kwargs)

        async def stream() -> AsyncIterator[Any]:
            for event in events:
                yield event
            if raise_at is not None:
                raise raise_at

        return stream()

    client = AnthropicLLMClient()
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, seen


def _client_failing_on_create(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> AnthropicLLMClient:
    async def create(**_: Any) -> Any:
        raise exc

    client = AnthropicLLMClient()
    monkeypatch.setattr(client, "_client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client


async def _collect(client: AnthropicLLMClient, usage: LLMCallContext = _CHAT, **kwargs: Any) -> list[str]:
    return [token async for token in client.generate("대본", usage=usage, **kwargs)]


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[anthropic.APIStatusError], status: int, error_type: str | None) -> anthropic.APIStatusError:
    body = None if error_type is None else {"type": "error", "error": {"type": error_type, "message": "m"}}
    return cls(f"Error code: {status}", response=httpx2.Response(status, request=_REQUEST), body=body)


# ---- 스트림과 요청 ---------------------------------------------------------------------------


async def test_only_text_deltas_are_relayed_even_with_thinking_blocks_in_the_stream(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """이 경로의 모델은 사고를 끌 수 없어 사고 블록이 본문보다 먼저 온다 — 화면에는 본문만 나가야 한다."""
    client, _ = _client_streaming(
        monkeypatch, _start(input_tokens=10), *_THINKING, _text("안"), _text(""), _text("녕"), _end(thinking=3)
    )

    assert await _collect(client) == ["안", "녕"]


async def test_thinking_text_never_reaches_the_user_even_when_the_stream_carries_it(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """사고 표시를 요약으로 바꾸면 `thinking_delta` 에 사고 글이 실려 온다. 그 글은 모델의 속생각이라 화면에 나가면
    안 된다 — 본문(`text_delta`)만 내보낸다."""
    thinking_with_text = (
        SimpleNamespace(
            type="content_block_start", index=0, content_block=SimpleNamespace(type="thinking", thinking="")
        ),
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="thinking_delta", thinking="속생각")),
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="signature_delta", signature="sig")),
        SimpleNamespace(type="content_block_stop", index=0),
    )
    client, _ = _client_streaming(
        monkeypatch, _start(input_tokens=10), *thinking_with_text, _text("안녕"), _end(thinking=3)
    )

    assert await _collect(client) == ["안녕"]


@pytest.mark.parametrize(
    ("usage", "model_setting", "max_tokens", "timeout_seconds", "effort"),
    [
        pytest.param(_CHAT, "anthropic_opus_model_id", 16_000, 45.0, "low", id="chat-opus"),
        pytest.param(_REPLAY, "anthropic_sonnet_model_id", 16_000, 45.0, "low", id="replay-sonnet"),
        pytest.param(_CHAPTER, "anthropic_opus_model_id", 64_000, 300.0, "medium", id="chapter-opus"),
    ],
)
async def test_generate_maps_the_request(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[Any],
    usage: LLMCallContext,
    model_setting: str,
    max_tokens: int,
    timeout_seconds: float,
    effort: str,
) -> None:
    """사고는 끌 수 없으니 `thinking` 을 아예 싣지 않고(끄라고 보내면 거부된다) 깊이만 effort 로 고른다. 강제 도구 선택·
    계정을 가리키는 값은 싣지 않는다."""
    monkeypatch.setattr(settings, model_setting, "actual-model")
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    await _collect(client, usage, system_instruction="지시", stop_sequences=["\n나:"])

    (kwargs,) = seen
    assert kwargs["model"] == "actual-model"
    assert kwargs["system"] == "지시"
    assert kwargs["messages"] == [{"role": "user", "content": "대본"}]
    assert kwargs["stop_sequences"] == ["\n나:"]
    assert kwargs["max_tokens"] == max_tokens
    assert kwargs["output_config"] == {"effort": effort}
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == timeout_seconds
    assert "thinking" not in kwargs
    assert "tool_choice" not in kwargs
    assert "tools" not in kwargs
    assert "metadata" not in kwargs


async def test_the_effort_profile_is_read_from_the_settings_on_each_call(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    monkeypatch.setattr(settings, "anthropic_chat_effort", "high")
    monkeypatch.setattr(settings, "anthropic_chapter_effort", "xhigh")
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    await _collect(client, _CHAT)
    await _collect(client, _CHAPTER)

    assert [kwargs["output_config"] for kwargs in seen] == [{"effort": "high"}, {"effort": "xhigh"}]


async def test_generate_without_system_or_stop_sequences_sends_neither(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    await _collect(client)

    assert seen[0]["system"] is anthropic.omit
    assert seen[0]["stop_sequences"] is anthropic.omit


_SEGMENTED = SegmentedPrompt(("앞부분", "\n나: 직전\n너: 응답", "\n\n나: 지금\n너:"))


@pytest.mark.parametrize("usage", [_CHAT, _REPLAY], ids=["chat", "replay"])
async def test_a_segmented_chat_prompt_goes_as_three_blocks_with_one_checkpoint_on_the_second(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], usage: LLMCallContext
) -> None:
    """캐시 블록과 체크포인트는 Messages API 의 것이라 직접 API 에서도 Bedrock 과 같은 자리에 단다."""
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    [_ async for _ in client.generate(_SEGMENTED, usage=usage)]

    assert seen[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "앞부분"},
                {"type": "text", "text": "\n나: 직전\n너: 응답", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "\n\n나: 지금\n너:"},
            ],
        }
    ]


async def test_a_chapter_never_carries_a_cache_checkpoint(monkeypatch: pytest.MonkeyPatch, recorded: list[Any]) -> None:
    client, seen = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    [_ async for _ in client.generate(_SEGMENTED, usage=_CHAPTER)]

    content = seen[0]["messages"][0]["content"]
    assert type(content) is str and content == _SEGMENTED


# ---- 응답이 쓸 수 없는 경우 ------------------------------------------------------------------


async def test_a_refusal_is_a_policy_violation_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end("refusal"))

    with pytest.raises(LLMPolicyViolationError) as exc_info:
        await _collect(client)
    assert exc_info.value.provider == "anthropic"
    assert recorded == []


async def test_a_chat_cut_off_at_the_cap_after_some_text_is_logged_and_returned(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _client_streaming(
        monkeypatch, _start(input_tokens=1), *_THINKING, _text("말을 하다"), _end("max_tokens", thinking=10)
    )

    with caplog.at_level(logging.WARNING, logger="api.llm.anthropic_api"):
        assert await _collect(client) == ["말을 하다"]

    assert any(r.name == "api.llm.anthropic_api" and "max_tokens(16000)" in r.getMessage() for r in caplog.records)
    assert len(recorded) == 1


async def test_a_chapter_cut_off_at_the_cap_after_some_text_fails_after_recording_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("장"), _end("max_tokens"))

    with pytest.raises(LLMTruncatedError) as exc_info:
        await _collect(client, _CHAPTER)
    assert exc_info.value.provider == "anthropic"
    assert len(recorded) == 1


@pytest.mark.parametrize("usage", [_CHAT, _CHAPTER], ids=["chat", "chapter"])
async def test_thinking_that_used_up_the_cap_before_any_text_fails_after_recording_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], usage: LLMCallContext
) -> None:
    """사고가 출력 상한을 다 써 본문이 하나도 없으면, 채팅이라도 빈 턴을 저장·과금하지 않고 실패로 올린다(환불 경로).
    원가는 이미 나갔으므로 사용량은 기록한다."""
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), *_THINKING, _end("max_tokens", 16_000, 16_000))

    with pytest.raises(LLMEmptyResponseError) as exc_info:
        await _collect(client, usage)
    assert exc_info.value.provider == "anthropic"
    assert len(recorded) == 1


@pytest.mark.parametrize("texts", [pytest.param([], id="no-text"), pytest.param([" \n"], id="whitespace")])
async def test_an_empty_chapter_fails_after_recording_usage_but_an_empty_chat_that_ended_normally_does_not(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], texts: list[str]
) -> None:
    events = [_start(input_tokens=1), *(_text(t) for t in texts), _end()]

    chapter, _ = _client_streaming(monkeypatch, *events)
    with pytest.raises(LLMEmptyResponseError):
        await _collect(chapter, _CHAPTER)
    assert len(recorded) == 1

    chat, _ = _client_streaming(monkeypatch, *events)
    assert "".join(await _collect(chat)).strip() == ""
    assert len(recorded) == 2


# ---- 사용량 ----------------------------------------------------------------------------------


async def test_usage_maps_cache_and_thinking_onto_the_gemini_metrics(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    """입력은 캐시 읽기·쓰기를 더한 입력 전체로 올린다(Bedrock 과 같다). 출력 토큰은 사고를 포함한 과금 총량이라, 그
    내역의 사고 몫을 `thoughts` 로 떼어 낸다 — 단가 계산(출력 + 사고 × 출력 단가)은 같은 값이고 사고 몫이 보인다."""
    monkeypatch.setattr(settings, "anthropic_opus_model_id", "opus-actual")
    client, _ = _client_streaming(
        monkeypatch,
        _start(input_tokens=100, read=1000, write=200, output=1),
        *_THINKING,
        _text("x"),
        _end(output=50, thinking=30),
    )

    with caplog.at_level(logging.WARNING, logger="api.llm.anthropic_api"):
        await _collect(client)

    ((call_site, model, meta),) = recorded
    assert (call_site, model) == ("chat_generate", "opus-actual")
    assert (
        meta.prompt_token_count,
        meta.cached_content_token_count,
        meta.cache_write_token_count,
        meta.candidates_token_count,
        meta.thoughts_token_count,
        meta.total_token_count,
    ) == (1300, 1000, 200, 20, 30, 1350)
    assert (
        "anthropic_usage call_site=chat_generate model=opus-actual prompt_tokens=1300 cached_content_tokens=1000 "
        "cache_write_tokens=200 candidates_tokens=20 thoughts_tokens=30 total_tokens=1350"
    ) in caplog.text
    assert "bedrock_usage" not in caplog.text
    assert "gemini_usage" not in caplog.text


async def test_usage_without_a_thinking_breakdown_counts_all_output_as_candidates(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=7), _text("x"), _end(output=3))

    await _collect(client)

    meta = recorded[0][2]
    assert (meta.prompt_token_count, meta.cached_content_token_count, meta.cache_write_token_count) == (7, 0, 0)
    assert (meta.candidates_token_count, meta.thoughts_token_count, meta.total_token_count) == (3, 0, 10)


async def test_a_stream_without_message_start_records_missing_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _client_streaming(monkeypatch, _text("x"), _end())

    with caplog.at_level(logging.WARNING, logger="api.llm.anthropic_api"):
        await _collect(client)

    assert recorded[0][2] is None
    assert "anthropic_usage" in caplog.text and "usage=missing" in caplog.text


async def test_usage_is_not_recorded_when_the_stream_fails_or_is_abandoned(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    failing, _ = _client_streaming(
        monkeypatch, _start(input_tokens=1), _text("x"), raise_at=httpx2.ReadTimeout("read timed out")
    )
    with pytest.raises(LLMClientError):
        await _collect(failing)

    abandoned, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("a"), _text("b"), _end())
    stream = abandoned.generate("대본", usage=_CHAT)
    assert await anext(stream) == "a"
    await stream.aclose()  # type: ignore[attr-defined]

    assert recorded == []


async def test_a_usage_logging_failure_does_not_break_the_stream(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    def explode(*_: Any, **__: Any) -> None:
        raise RuntimeError("logging broke")

    monkeypatch.setattr(anthropic_module.logger, "warning", explode)
    client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), _end())

    assert await _collect(client) == ["x"]
    assert len(recorded) == 1


def test_the_direct_api_ids_are_priced_at_the_published_list_price() -> None:
    """Anthropic 가격 문서(2026-10-10 조회)의 표 값. 두 모델은 캐시 읽기가 입력의 0.05 배라 관례(0.1 배)로 짐작하면
    틀린다."""
    assert MODEL_PRICES["claude-opus-5-5"] == ModelPrice(4.00, 0.20, 20.00, cache_write_usd_per_million=5.00)
    assert MODEL_PRICES["claude-sonnet-5-5"] == ModelPrice(2.00, 0.10, 10.00, cache_write_usd_per_million=2.50)


# ---- 실패 매핑 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_status_error(anthropic.RateLimitError, 429, "rate_limit_error"), id="http-429"),
        # 스트림 도중의 오류는 응답 상태가 이미 200 이라 SDK 가 상태 코드 갈래의 클래스로 만들지 못한다 — 본문의 종류로만
        # 쿼터 소진이 드러난다.
        pytest.param(_status_error(anthropic.APIStatusError, 200, "rate_limit_error"), id="rate-limit-error-body"),
    ],
)
@pytest.mark.parametrize("where", ["create", "mid-stream"])
async def test_quota_exhaustion_is_a_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], exc: BaseException, where: str
) -> None:
    if where == "create":
        client = _client_failing_on_create(monkeypatch, exc)
    else:
        client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), raise_at=exc)

    with pytest.raises(LLMRateLimitError) as exc_info:
        await _collect(client)
    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.__cause__ is exc
    assert _llm_dependency_tag(exc_info.value) == "anthropic_rate_limit"
    assert recorded == []


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_status_error(anthropic.BadRequestError, 400, "invalid_request_error"), id="http-400"),
        pytest.param(_status_error(anthropic.AuthenticationError, 401, "authentication_error"), id="http-401"),
        pytest.param(_status_error(anthropic.PermissionDeniedError, 403, "permission_error"), id="http-403"),
        pytest.param(_status_error(anthropic.InternalServerError, 500, "api_error"), id="http-500"),
        pytest.param(_status_error(anthropic.InternalServerError, 504, None), id="http-504"),
        # 과부하는 우리 쿼터가 아니라 공급자 쪽 혼잡이라 쿼터 소진과 묶지 않는다.
        pytest.param(_status_error(anthropic.OverloadedError, 529, "overloaded_error"), id="http-529"),
        pytest.param(_status_error(anthropic.APIStatusError, 200, "overloaded_error"), id="overloaded-error-body"),
        pytest.param(_status_error(anthropic.APIStatusError, 200, "api_error"), id="api-error-body"),
        pytest.param(anthropic.APIConnectionError(request=_REQUEST), id="connection"),
        pytest.param(anthropic.APITimeoutError(request=_REQUEST), id="sdk-timeout"),
        pytest.param(httpx2.ReadTimeout("read timed out"), id="httpx2-read-timeout"),
        pytest.param(httpx.ReadTimeout("read timed out"), id="httpx-read-timeout"),
        pytest.param(TimeoutError(), id="bare-timeout"),
    ],
)
@pytest.mark.parametrize("where", ["create", "mid-stream"])
async def test_other_failures_are_plain_client_errors(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], exc: BaseException, where: str
) -> None:
    """SDK·네트워크 예외가 그대로 새면 SSE 제너레이터를 뚫어 요청 스코프 DB 세션이 강제 종료된다 — 전부
    `LLMClientError` 로 바꾸고 원래 예외를 원인으로 남긴다."""
    if where == "create":
        client = _client_failing_on_create(monkeypatch, exc)
    else:
        client, _ = _client_streaming(monkeypatch, _start(input_tokens=1), _text("x"), raise_at=exc)

    with pytest.raises(LLMClientError) as exc_info:
        await _collect(client)

    assert not isinstance(exc_info.value, LLMRateLimitError)
    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.__cause__ is exc
    assert _llm_dependency_tag(exc_info.value) == "anthropic"
    assert recorded == []


async def test_generate_structured_is_not_supported() -> None:
    class _Schema(BaseModel):
        ok: bool

    with pytest.raises(LLMClientError) as exc_info:
        await AnthropicLLMClient().generate_structured("p", _Schema, usage=_CHAT)
    assert exc_info.value.provider == "anthropic"


# ---- SDK 클라이언트 생성 ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "  "])
async def test_an_empty_key_fails_before_building_the_sdk_client(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """빈 키를 명시로 넘기면 SDK 는 env 의 `ANTHROPIC_API_KEY` 도 찾지 않고 그대로 보내 인증 실패를 받는다. 키를 넘기지
    않으면 SDK 가 env·로그인 프로필에서 다른 자격을 찾는다 — 어느 쪽도 원하는 동작이 아니라 만들기 전에 막는다."""
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", lambda **kwargs: built.append(kwargs))
    monkeypatch.setattr(settings, "anthropic_direct_api_key", value)

    with pytest.raises(LLMClientError) as exc_info:
        await _collect(AnthropicLLMClient())

    assert exc_info.value.provider == "anthropic"
    assert built == []


async def test_the_sdk_client_gets_an_explicit_key_and_host_and_no_retries(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    built: list[dict[str, Any]] = []

    async def create(**_: Any) -> AsyncIterator[Any]:
        async def stream() -> AsyncIterator[Any]:
            yield _end()

        return stream()

    def fake_sdk(**kwargs: Any) -> Any:
        built.append(kwargs)
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", fake_sdk)
    monkeypatch.setattr(settings, "anthropic_direct_api_key", f" {_KEY} ")
    client = AnthropicLLMClient()

    await _collect(client)
    await _collect(client)

    assert built == [
        {
            "api_key": _KEY,
            "base_url": "https://api.anthropic.com",
            "max_retries": 0,
            "timeout": settings.anthropic_chat_timeout_ms / 1000,
        }
    ]


# ---- 실제 SDK 를 거친 요청 -------------------------------------------------------------------


def _sdk_backed(monkeypatch: pytest.MonkeyPatch, respond: Any) -> tuple[AnthropicLLMClient, list[httpx2.Request]]:
    """구현이 SDK 를 스스로 만들게 두고 전송 계층만 바꿔 끼운다 — 생성자 인자가 env 보다 앞서는지까지 실제 SDK 로 본다."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        response: httpx2.Response = respond(request)
        return response

    real = anthropic.AsyncAnthropic

    def build(**kwargs: Any) -> anthropic.AsyncAnthropic:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", build)
    return AnthropicLLMClient(), seen


async def test_the_request_reaches_the_wire_with_the_settings_key_and_host_whatever_the_env_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK 는 명시 인자가 없으면 env 의 `ANTHROPIC_API_KEY`·`ANTHROPIC_BASE_URL` 을 읽는다. 다른 값을 심어 두어도 요청은
    설정의 키로 Anthropic 기본 호스트에 가야 한다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.example")
    client, seen = _sdk_backed(
        monkeypatch,
        lambda _: httpx2.Response(
            400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "m"}}
        ),
    )

    with pytest.raises(LLMClientError):
        [_ async for _ in client.generate(_SEGMENTED, "지시", ["\n나:"], usage=_CHAT)]

    (request,) = seen
    assert request.url.host == "api.anthropic.com"
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == _KEY
    body = json.loads(request.content)
    assert body["model"] == settings.anthropic_opus_model_id
    assert body["system"] == "지시"
    assert body["stop_sequences"] == ["\n나:"]
    assert body["max_tokens"] == 16_000
    assert body["stream"] is True
    assert body["output_config"] == {"effort": "low"}
    assert "thinking" not in body
    assert "tool_choice" not in body
    assert "metadata" not in body
    blocks = body["messages"][0]["content"]
    assert [b["text"] for b in blocks] == list(_SEGMENTED.segments)
    assert [b.get("cache_control") for b in blocks] == [None, {"type": "ephemeral"}, None]


async def test_a_429_through_the_real_sdk_is_a_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client, seen = _sdk_backed(
        monkeypatch,
        lambda _: httpx2.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "m"}}),
    )

    with pytest.raises(LLMRateLimitError):
        await _collect(client)
    assert len(seen) == 1  # 재시도하지 않는다


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


_MESSAGE_START = {
    "type": "message_start",
    "message": {
        "id": "msg",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 5,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 2,
            "output_tokens": 1,
        },
    },
}
_STREAM_HEADERS = {"content-type": "text/event-stream"}


async def test_a_successful_stream_through_the_real_sdk_relays_only_text_and_splits_thinking_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """사용량의 사고 내역(`output_tokens_details`)을 SDK 가 실제로 어떤 모양으로 옮기는지 본다. 사고 글이 실린
    `thinking_delta`(사고 표시가 요약일 때의 모양)도 넣어, SDK 가 옮긴 그 이벤트가 화면에 나가지 않는지 함께 본다."""
    body = _sse(
        _MESSAGE_START,
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "속생각"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "안녕"}},
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 30, "output_tokens_details": {"thinking_tokens": 25}},
        },
        {"type": "message_stop"},
    )
    client, _ = _sdk_backed(monkeypatch, lambda _: httpx2.Response(200, headers=_STREAM_HEADERS, content=body))

    assert await _collect(client) == ["안녕"]

    ((_, model, meta),) = recorded
    assert model == settings.anthropic_opus_model_id
    assert (meta.prompt_token_count, meta.candidates_token_count, meta.thoughts_token_count) == (47, 5, 25)


@pytest.mark.parametrize(
    ("error_type", "rate_limited"),
    [pytest.param("rate_limit_error", True, id="rate-limit"), pytest.param("overloaded_error", False, id="overloaded")],
)
async def test_an_error_event_mid_stream_through_the_real_sdk_is_classified_by_its_type(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], error_type: str, rate_limited: bool
) -> None:
    """스트림 도중 오류는 SSE `error` 이벤트로 오고, 응답 상태가 200 이라 SDK 가 상태 코드 클래스가 아닌 일반
    `APIStatusError` 로 올린다. 진짜 SDK 가 그 이벤트를 옮긴 모양에서 종류를 읽는지 본다."""
    body = _sse(
        _MESSAGE_START,
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "말을"}},
        {"type": "error", "error": {"type": error_type, "message": "m"}},
    )
    client, _ = _sdk_backed(monkeypatch, lambda _: httpx2.Response(200, headers=_STREAM_HEADERS, content=body))
    received: list[str] = []

    with pytest.raises(LLMClientError) as exc_info:
        async for token in client.generate("대본", usage=_CHAT):
            received.append(token)

    assert received == ["말을"]
    assert isinstance(exc_info.value, LLMRateLimitError) is rate_limited
    assert exc_info.value.provider == "anthropic"
    assert recorded == []
