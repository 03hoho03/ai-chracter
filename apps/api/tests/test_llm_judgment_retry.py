"""판정 실패를 곧바로 한 번 다시 부를 만한 것인지 가르는 분류(`is_retryable_judgment_failure`).

다시 부르는 것: 일시적인 서버·연결 오류(5xx — 504 제외 — 와 타임아웃이 아닌 연결 끊김)와 파싱 실패. 파싱 실패는 구조화 호출에
시드가 붙지 않아 다시 뽑으면 다른 표본이다. 다시 부르지 않는 것: 타임아웃(이미 판정 타임아웃만큼 기다렸고 한 번 더 기다리면 턴 락
TTL 을 넘길 수 있다 — 504 도 기다린 뒤에 오므로 같다), 429(곧바로 다시 불러도 같은 쿼터), 안전 차단(같은 입력이면 같은 판단),
그 밖의 4xx.

Gemini 정규화가 5xx·연결 끊김·타임아웃을 같은 `LLMClientError` 로 올리므로 분류는 예외의 원인(`__cause__`)을 본다. 그래서 예외를
손으로 만들지 않고, SDK 경계만 가짜로 둔 실제 `GeminiLLMClient.generate_structured` 가 올린 예외로 본다 — 정규화가 원인을
잃거나 다른 타입으로 올리면 여기서 드러난다."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import botocore.eventstream
import botocore.exceptions
import httpx
import httpx2
import pytest
from google.genai import errors as genai_errors

from api.chat.prompt_builder import StatRuleJudgmentResult
from api.llm import gemini as gemini_module
from api.llm.client import (
    LLMCallContext,
    LLMClientError,
    LLMEmptyResponseError,
    LLMTruncatedError,
    is_retryable_judgment_failure,
)
from api.llm.gemini import GeminiLLMClient


def _response(**fields: Any) -> SimpleNamespace:
    """구조화 응답 하나. 기본은 스키마로 읽히지 않은 응답(차단 표시 없음)이다."""
    values: dict[str, Any] = {
        "parsed": None,
        "prompt_feedback": None,
        "candidates": [],
        "text": "{",
        "usage_metadata": None,
    }
    values.update(fields)
    return SimpleNamespace(**values)


def _raising(cause: BaseException) -> Callable[..., Any]:
    async def generate_content(**_: Any) -> Any:
        raise cause

    return generate_content


def _returning(response: SimpleNamespace) -> Callable[..., Any]:
    async def generate_content(**_: Any) -> Any:
        return response

    return generate_content


_REQUEST = httpx.Request("POST", "https://example.invalid")

_CASES: dict[str, tuple[Callable[..., Any], bool]] = {
    "server-error-503": (_raising(genai_errors.ServerError(503, {"error": {"message": "unavailable"}})), True),
    "server-error-500": (_raising(genai_errors.ServerError(500, {"error": {"message": "internal"}})), True),
    "gateway-timeout-504": (_raising(genai_errors.ServerError(504, {"error": {"message": "deadline"}})), False),
    "bad-request-400": (_raising(genai_errors.ClientError(400, {"error": {"message": "bad"}})), False),
    "quota-429": (_raising(genai_errors.ClientError(429, {"error": {"message": "quota"}})), False),
    "connect-error": (_raising(httpx.ConnectError("refused", request=_REQUEST)), True),
    "remote-protocol-error": (_raising(httpx.RemoteProtocolError("closed", request=_REQUEST)), True),
    # 전송 오류가 아닌 httpx 실패(상태 오류)는 원인이 있으므로 파싱 실패로 보지 않는다.
    "http-status-error": (
        _raising(httpx.HTTPStatusError("bad", request=_REQUEST, response=httpx.Response(400, request=_REQUEST))),
        False,
    ),
    "read-timeout": (_raising(httpx.ReadTimeout("slow", request=_REQUEST)), False),
    "connect-timeout": (_raising(httpx.ConnectTimeout("slow", request=_REQUEST)), False),
    "timeout-error": (_raising(TimeoutError()), False),
    "unparsable-response": (_returning(_response()), True),
    "blocked-prompt": (_returning(_response(prompt_feedback=SimpleNamespace(block_reason="SAFETY"))), False),
    "blocked-output": (_returning(_response(candidates=[SimpleNamespace(finish_reason="SAFETY")])), False),
}


@pytest.mark.parametrize("case", list(_CASES))
async def test_judgment_failure_is_retried_only_for_transient_server_or_connection_failures_and_parse_failures(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    generate_content, expected = _CASES[case]

    async def _no_record(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(gemini_module, "record_usage", _no_record)
    client = GeminiLLMClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))),
    )

    with pytest.raises(LLMClientError) as raised:
        await client.generate_structured(
            "프롬프트",
            StatRuleJudgmentResult,
            usage=LLMCallContext(call_site="chat_stat_judgment", user_id=None, room_id=None),
        )

    assert is_retryable_judgment_failure(raised.value) is expected


@pytest.mark.parametrize("error_type", [LLMTruncatedError, LLMEmptyResponseError])
def test_a_causeless_subclass_is_not_taken_for_a_parse_failure(error_type: type[LLMClientError]) -> None:
    """원인 없는 실패 가운데 파싱 실패로 보는 것은 정확히 `LLMClientError` 인 것뿐이다 — 잘림·빈 응답은 소설화 호출에서만
    올라오는 구분된 실패라, 하위 클래스까지 받으면 판정이 아닌 실패가 파싱 실패로 섞인다."""
    assert is_retryable_judgment_failure(error_type("잘렸다")) is False


def _caused_by(cause: BaseException) -> LLMClientError:
    try:
        raise LLMClientError("Bedrock generate_structured() call failed") from cause
    except LLMClientError as exc:
        return exc


_BEDROCK_REQUEST = httpx2.Request("POST", "https://bedrock-runtime.invalid")


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        # SDK 가 감싸지 않고 그대로 올리는 전송 예외 — 응답을 읽다 연결이 끊긴 것은 한 번 다시, 시간 초과는 다시 기다리지 않는다.
        pytest.param(httpx2.ReadTimeout("slow", request=_BEDROCK_REQUEST), False, id="httpx2-read-timeout"),
        pytest.param(httpx2.RemoteProtocolError("closed", request=_BEDROCK_REQUEST), True, id="httpx2-disconnect"),
        # botocore 는 Bedrock 요청 서명과 응답 프레임 해석에서 그대로 올린다. 전송 실패(연결·프레임 깨짐)만 일시 오류다.
        pytest.param(botocore.exceptions.ReadTimeoutError(endpoint_url="u"), False, id="botocore-read-timeout"),
        pytest.param(botocore.exceptions.ConnectTimeoutError(endpoint_url="u"), False, id="botocore-connect-timeout"),
        pytest.param(botocore.exceptions.EndpointConnectionError(endpoint_url="u"), True, id="botocore-endpoint"),
        pytest.param(botocore.exceptions.ConnectionClosedError(endpoint_url="u"), True, id="botocore-closed"),
        pytest.param(botocore.eventstream.ChecksumMismatch(1, 2), True, id="botocore-frame"),
        # 자격·프로필 문제는 다시 불러도 같다 — 기동 검증이 빈 자격을 막고, 남는 것은 설정 사고다.
        pytest.param(botocore.exceptions.NoCredentialsError(), False, id="botocore-no-credentials"),
        pytest.param(botocore.exceptions.ProfileNotFound(profile="p"), False, id="botocore-profile"),
    ],
)
def test_claude_transport_causes_outside_the_sdk_are_sorted_by_kind(cause: BaseException, expected: bool) -> None:
    assert is_retryable_judgment_failure(_caused_by(cause)) is expected
