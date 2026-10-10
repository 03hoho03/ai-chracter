"""Claude 구조화 출력 — Bedrock 구현과 Anthropic API 직접 구현이 같은 공용 조각(`llm/claude_messages.py`)으로 판정·요약을
받는다.

요청은 `output_config.format`(JSON 스키마)으로 보내고, 응답은 종료 사유를 먼저 본 뒤(정책 거절은 안전 차단, 출력 상한은
원인 없는 실패) 텍스트 블록만 이어 스키마로 읽는다. 읽지 못하면 원인 없는 `LLMClientError` 다 — 판정 재시도 분류가 그 꼴을
파싱 실패로 보고 한 번 다시 부른다. 사용량은 파싱 검사 앞에서 구현 모듈의 이름으로 기록한다(과금된 호출이 집계에서 빠지지
않고, 리플레이가 그 이름을 바꿔 끼워 원가를 잰다).

SDK 를 가짜로 바꾸지 않고 실제 SDK 를 쓰되 전송 계층만 바꿔 끼운다 — 요청 본문이 실제로 어떻게 실리는지와, 같은 HTTP 상태가
두 SDK 클라이언트에서 서로 다른 예외 클래스로 오는 것(직접 504 = `InternalServerError`, 529 = `OverloadedError`, Bedrock 503 =
`ServiceUnavailableError`)을 그대로 거친다."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx2
import pytest

from api.chat.prompt_builder import StatRuleJudgmentResult
from api.core.config import settings
from api.llm import anthropic_api as anthropic_module
from api.llm import bedrock as bedrock_module
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.bedrock import BedrockLLMClient
from api.llm.client import (
    CallUsage,
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    is_retryable_judgment_failure,
)

Handler = Callable[[httpx2.Request], httpx2.Response]


@dataclass(frozen=True)
class _Backend:
    name: str
    module: Any
    log_token: str
    build: Callable[[pytest.MonkeyPatch, Handler], LLMClient]


def _build_bedrock(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> LLMClient:
    monkeypatch.setattr(settings, "bedrock_access_key_id", "AKIATEST")
    monkeypatch.setattr(settings, "bedrock_secret_access_key", "secret-test")
    monkeypatch.setattr(settings, "bedrock_region", "ap-northeast-2")
    real = anthropic.AsyncAnthropicBedrock

    def build(**kwargs: Any) -> anthropic.AsyncAnthropicBedrock:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(bedrock_module, "AsyncAnthropicBedrock", build)
    return BedrockLLMClient()


def _build_anthropic(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> LLMClient:
    monkeypatch.setattr(settings, "anthropic_direct_api_key", "sk-ant-test")
    real = anthropic.AsyncAnthropic

    def build(**kwargs: Any) -> anthropic.AsyncAnthropic:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", build)
    return AnthropicLLMClient()


_BEDROCK = _Backend("bedrock", bedrock_module, "bedrock_usage", _build_bedrock)
_ANTHROPIC = _Backend("anthropic", anthropic_module, "anthropic_usage", _build_anthropic)
_BOTH = [pytest.param(_BEDROCK, id="bedrock"), pytest.param(_ANTHROPIC, id="anthropic")]

_STAT = LLMCallContext("chat_stat_judgment", None, None)


@pytest.fixture(autouse=True)
def _haiku_judges_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stat_judgment_model", "haiku")


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    """두 구현 모듈의 사용량 기록을 함께 잡는다 — 리플레이가 원가를 잴 때 바꿔 끼우는 그 이름이다."""
    calls: list[tuple[str, str, Any]] = []

    async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
        calls.append((call_site, model, usage_metadata))

    monkeypatch.setattr(bedrock_module, "record_usage", record_usage)
    monkeypatch.setattr(anthropic_module, "record_usage", record_usage)
    return calls


def _message(
    *blocks: dict[str, Any], stop_reason: str = "end_turn", output_tokens: int = 7, **usage: Any
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": list(blocks),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": output_tokens, **usage},
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _replying(body: dict[str, Any], seen: list[httpx2.Request] | None = None) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return httpx2.Response(200, json=body)

    return handler


_VALID = _text('{"fired_rule_ids": ["r1"]}')


async def _judge(client: LLMClient, usage: LLMCallContext = _STAT) -> StatRuleJudgmentResult:
    return await client.generate_structured("판정 프롬프트", StatRuleJudgmentResult, usage=usage)


# ── 요청과 성공 ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("backend", _BOTH)
async def test_a_judgment_is_parsed_from_the_text_and_its_usage_recorded_before_returning(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend, caplog: pytest.LogCaptureFixture
) -> None:
    sink: list[CallUsage] = []
    client = backend.build(monkeypatch, _replying(_message(_VALID, cache_read_input_tokens=30)))

    with caplog.at_level(logging.WARNING, logger=backend.module.__name__):
        result = await _judge(client, LLMCallContext("chat_stat_judgment", None, None, usage_sink=sink))

    assert result == StatRuleJudgmentResult(fired_rule_ids=["r1"])
    sent = getattr(settings, f"{backend.name}_haiku_model_id")
    ((call_site, model, usage),) = recorded
    assert (call_site, model) == ("chat_stat_judgment", sent)
    assert (usage.prompt_token_count, usage.cached_content_token_count, usage.candidates_token_count) == (150, 30, 7)
    assert [(u.call_site, u.model, u.prompt_tokens, u.output_tokens) for u in sink] == [
        ("chat_stat_judgment", sent, 150, 7)
    ]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith(backend.log_token)]
    assert len(lines) == 1 and "call_site=chat_stat_judgment" in lines[0] and f"model={sent}" in lines[0]


async def test_the_bedrock_request_carries_the_schema_with_thinking_off_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    seen: list[httpx2.Request] = []
    client = _build_bedrock(monkeypatch, _replying(_message(_VALID), seen))

    await _judge(client)

    (request,) = seen
    assert request.url.path == f"/model/{settings.bedrock_haiku_model_id}/invoke"
    body = json.loads(request.content)
    assert body["messages"] == [{"role": "user", "content": "판정 프롬프트"}]
    assert body["max_tokens"] == settings.bedrock_chat_max_tokens
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": anthropic.transform_schema(StatRuleJudgmentResult)}
    }
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    for absent in ("stream", "system", "tool_choice", "tools", "metadata", "stop_sequences"):
        assert absent not in body, absent


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        # Haiku 4.5 는 `effort` 를 받으면 요청을 400 으로 거부한다.
        pytest.param("haiku", None, id="haiku"),
        pytest.param("opus", "low", id="opus"),
        pytest.param("sonnet", "low", id="sonnet"),
    ],
)
async def test_the_direct_request_carries_the_schema_without_thinking_and_effort_only_where_the_model_takes_it(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], model: str, effort: str | None
) -> None:
    monkeypatch.setattr(settings, "stat_judgment_model", model)
    seen: list[httpx2.Request] = []
    client = _build_anthropic(monkeypatch, _replying(_message(_VALID), seen))

    await _judge(client)

    (request,) = seen
    assert request.url.path == "/v1/messages"
    body = json.loads(request.content)
    assert body["model"] == getattr(settings, f"anthropic_{model}_model_id")
    assert body["messages"] == [{"role": "user", "content": "판정 프롬프트"}]
    assert body["max_tokens"] == settings.anthropic_chat_max_tokens
    expected: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": anthropic.transform_schema(StatRuleJudgmentResult)}
    }
    if effort is not None:
        expected["effort"] = effort
    assert body["output_config"] == expected
    for absent in ("thinking", "stream", "system", "tool_choice", "tools", "metadata"):
        assert absent not in body, absent


@pytest.mark.parametrize(
    ("call_site", "timeout_setting"),
    [
        ("chat_stat_judgment", "gemini_judgment_timeout_ms"),
        ("chat_memory_summary", "gemini_memory_summary_timeout_ms"),
    ],
)
@pytest.mark.parametrize("backend", _BOTH)
async def test_the_timeout_is_the_one_the_call_site_already_uses(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend, call_site: str, timeout_setting: str
) -> None:
    """Claude 판정·요약도 Gemini 와 같은 호출 위치 값으로 끊는다(판정 20초·요약 60초) — 판정 하나가 턴을 붙잡는 시간이
    공급자에 따라 늘지 않게."""
    monkeypatch.setattr(settings, "memory_summary_model", "haiku")
    monkeypatch.setattr(settings, timeout_setting, 12_345)
    seen: list[httpx2.Request] = []
    client = backend.build(monkeypatch, _replying(_message(_VALID), seen))

    await client.generate_structured("p", StatRuleJudgmentResult, usage=LLMCallContext(call_site, None, None))  # type: ignore[arg-type]

    timeouts = seen[0].extensions["timeout"]
    assert timeouts["read"] == pytest.approx(12.345)


async def test_thinking_blocks_are_skipped_and_only_the_text_is_parsed(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    """직접 API 의 5.5 모델은 사고를 끌 수 없어 응답 앞에 사고 블록이 붙는다 — 본문은 텍스트 블록뿐이다."""
    monkeypatch.setattr(settings, "stat_judgment_model", "opus")
    thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
    client = _build_anthropic(
        monkeypatch,
        _replying(_message(thinking, _VALID, output_tokens=40, output_tokens_details={"thinking_tokens": 33})),
    )

    assert await _judge(client) == StatRuleJudgmentResult(fired_rule_ids=["r1"])
    ((_, _, usage),) = recorded
    assert (usage.candidates_token_count, usage.thoughts_token_count) == (7, 33)


# ── 실패 정규화 ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(_message(_text("{\"fired_rule_ids\": ")), id="cut-json"),
        pytest.param(_message(_text('{"unexpected": 1}')), id="wrong-shape"),
        pytest.param(_message(), id="no-text-block"),
        pytest.param(_message({"type": "thinking", "thinking": "", "signature": "s"}), id="thinking-only"),
    ],
)
@pytest.mark.parametrize("backend", _BOTH)
async def test_an_unreadable_reply_is_a_causeless_client_error_that_is_retried_once_after_recording_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend, reply: dict[str, Any]
) -> None:
    client = backend.build(monkeypatch, _replying(reply))

    with pytest.raises(LLMClientError) as raised:
        await _judge(client)

    assert type(raised.value) is LLMClientError
    assert raised.value.__cause__ is None
    assert raised.value.provider == backend.name
    assert is_retryable_judgment_failure(raised.value) is True
    assert len(recorded) == 1


@pytest.mark.parametrize("backend", _BOTH)
async def test_a_refusal_is_a_policy_violation_that_is_not_retried_and_is_still_recorded(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend
) -> None:
    """거절도 과금된다(응답은 200). 스키마와 맞지 않을 수 있어 파싱부터 하면 파싱 실패로 둔갑해 같은 입력을 또 보낸다."""
    client = backend.build(monkeypatch, _replying(_message(_VALID, stop_reason="refusal")))

    with pytest.raises(LLMPolicyViolationError) as raised:
        await _judge(client)

    assert raised.value.provider == backend.name
    assert is_retryable_judgment_failure(raised.value) is False
    assert len(recorded) == 1


@pytest.mark.parametrize("backend", _BOTH)
async def test_a_reply_cut_at_the_output_cap_is_a_causeless_client_error_that_is_retried_once(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend
) -> None:
    """출력 상한에서 끝난 응답은 읽혀도 믿지 않는다 — Gemini 에서 잘림이 파싱 실패로 보이는 것과 같은 결과(한 번 다시)."""
    client = backend.build(monkeypatch, _replying(_message(_VALID, stop_reason="max_tokens")))

    with pytest.raises(LLMClientError) as raised:
        await _judge(client)

    assert type(raised.value) is LLMClientError
    assert raised.value.__cause__ is None
    assert is_retryable_judgment_failure(raised.value) is True
    assert len(recorded) == 1


def _status(status: int, error_type: str) -> Handler:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"type": "error", "error": {"type": error_type, "message": "m"}})

    return handler


def _raising(exc: Exception) -> Handler:
    def handler(_: httpx2.Request) -> httpx2.Response:
        raise exc

    return handler


_WIRE = httpx2.Request("POST", "https://wire.invalid")


@pytest.mark.parametrize(
    ("backend", "handler", "cause_class", "retried"),
    [
        # 직접 클라이언트: 504 는 따로 갈래가 없어 `InternalServerError`, 529 는 `OverloadedError`.
        pytest.param(_ANTHROPIC, _status(500, "api_error"), anthropic.InternalServerError, True, id="direct-500"),
        pytest.param(_ANTHROPIC, _status(504, "timeout_error"), anthropic.InternalServerError, False, id="direct-504"),
        pytest.param(_ANTHROPIC, _status(529, "overloaded_error"), anthropic.OverloadedError, True, id="direct-529"),
        pytest.param(_ANTHROPIC, _status(503, "api_error"), anthropic.InternalServerError, True, id="direct-503"),
        pytest.param(_ANTHROPIC, _status(400, "invalid_request_error"), anthropic.BadRequestError, False, id="direct-400"),
        # Bedrock 클라이언트: 503 은 `ServiceUnavailableError`, 529 갈래가 없다.
        pytest.param(_BEDROCK, _status(503, "x"), anthropic.ServiceUnavailableError, True, id="bedrock-503"),
        pytest.param(_BEDROCK, _status(500, "x"), anthropic.InternalServerError, True, id="bedrock-500"),
        pytest.param(_BEDROCK, _status(504, "x"), anthropic.InternalServerError, False, id="bedrock-504"),
        pytest.param(_BEDROCK, _status(400, "x"), anthropic.BadRequestError, False, id="bedrock-400"),
        # 시간 초과는 연결 오류의 하위 클래스다 — 연결 오류(한 번 다시)보다 먼저 가려야 한다.
        pytest.param(_ANTHROPIC, _raising(httpx2.ReadTimeout("slow", request=_WIRE)), anthropic.APITimeoutError, False, id="direct-timeout"),
        pytest.param(_BEDROCK, _raising(httpx2.ReadTimeout("slow", request=_WIRE)), anthropic.APITimeoutError, False, id="bedrock-timeout"),
        pytest.param(_ANTHROPIC, _raising(httpx2.ConnectError("refused", request=_WIRE)), anthropic.APIConnectionError, True, id="direct-connect"),
        pytest.param(_BEDROCK, _raising(httpx2.ConnectError("refused", request=_WIRE)), anthropic.APIConnectionError, True, id="bedrock-connect"),
    ],
)
async def test_claude_failures_are_retried_by_status_and_kind_not_by_exception_class(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[Any],
    backend: _Backend,
    handler: Handler,
    cause_class: type[BaseException],
    retried: bool,
) -> None:
    client = backend.build(monkeypatch, handler)

    with pytest.raises(LLMClientError) as raised:
        await _judge(client)

    assert type(raised.value) is LLMClientError
    assert type(raised.value.__cause__) is cause_class
    assert raised.value.provider == backend.name
    assert is_retryable_judgment_failure(raised.value) is retried
    assert recorded == []


@pytest.mark.parametrize("backend", _BOTH)
async def test_quota_exhaustion_is_a_rate_limit_error_that_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend
) -> None:
    client = backend.build(monkeypatch, _status(429, "rate_limit_error"))

    with pytest.raises(LLMRateLimitError) as raised:
        await _judge(client)

    assert isinstance(raised.value.__cause__, anthropic.RateLimitError)
    assert is_retryable_judgment_failure(raised.value) is False


# ── 기동 검증이 막는 원인 없는 실패 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("backend", _BOTH)
async def test_a_structured_call_with_images_is_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any], backend: _Backend
) -> None:
    """그림을 싣는 구조화(발행 심사)는 등록부가 이 구현을 받지 못하는 곳으로 적어 기동 검증이 그 배정을 막는다 — 닿으면
    원인 없는 실패라 판정이었다면 파싱 실패로 읽히겠지만, 그림을 싣는 호출은 판정이 아니다."""
    seen: list[httpx2.Request] = []
    client = backend.build(monkeypatch, _replying(_message(_VALID), seen))

    with pytest.raises(LLMClientError) as raised:
        await client.generate_structured("p", StatRuleJudgmentResult, [(b"png", "image/png")], usage=_STAT)

    assert raised.value.provider == backend.name
    assert seen == []
