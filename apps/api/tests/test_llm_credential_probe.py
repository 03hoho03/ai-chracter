"""Claude 자격 저장·확인 호출 — 토큰 세기 응답의 조직 헤더와 모델 축 확인 요청을 실제 SDK 로 보내고 전송 계층만 바꿔 낀다.

생성자 인자가 env 보다 앞서는지, 요청 본문이 운영 요청과 같은 꼴인지는 SDK 가 실제로 만든 요청으로만 볼 수 있어, 가짜 SDK 가
아니라 SDK 의 전송 계층(MockTransport)을 바꾼다. 조직 불일치 판정은 라우터에 있어 어드민 API 테스트가 본다."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from api.core.config import settings
from api.llm import credential_probe
from api.llm.claude_messages import to_usage
from api.llm.credential_probe import (
    AnthropicCredentialProbe,
    CheckCallResult,
    CredentialProbeError,
)
from api.llm.credentials import CheckGroup
from factories import FAKE_API_KEY

_ORG_HEADER = "anthropic-organization-id"
_CREDENTIAL_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def _model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청에 실리는 설정값을 고정한다 — 로컬 env 파일의 값에 따라 본문이 달라지지 않게."""
    monkeypatch.setattr(settings, "anthropic_haiku_model_id", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "anthropic_chat_effort", "low")
    monkeypatch.setattr(settings, "anthropic_structured_effort", "medium")
    monkeypatch.setattr(settings, "anthropic_chat_timeout_ms", 45_000)


def _sdk_backed(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx2.Request], httpx2.Response]
) -> list[httpx2.Request]:
    """조사가 SDK 를 스스로 만들게 두고 전송 계층만 바꿔 낀다."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return respond(request)

    real = anthropic.AsyncAnthropic

    def build(**kwargs: Any) -> anthropic.AsyncAnthropic:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(credential_probe, "AsyncAnthropic", build)
    return seen


def _tokens(headers: dict[str, str] | None = None) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(200, json={"input_tokens": 3}, headers=headers or {})


def _message(headers: dict[str, str] | None = None) -> Callable[[httpx2.Request], httpx2.Response]:
    body = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": [{"type": "text", "text": "네"}],
        "stop_reason": "max_tokens",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 12,
            "output_tokens": 16,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    return lambda _: httpx2.Response(200, json=body, headers=headers or {})


def _error(status: int, error_type: str, message: str = "m", details: dict[str, str] | None = None) -> Any:
    error: dict[str, object] = {"type": error_type, "message": message}
    if details is not None:
        error["details"] = details
    return lambda _: httpx2.Response(status, json={"type": "error", "error": error})


# ── 조직 조회(토큰 세기) ────────────────────────────────────────────────────────────
async def test_organization_header_is_read_from_the_token_count_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """저장 때 토큰 세기(무료)를 판정 모델 id 로 불러 응답의 조직 헤더를 읽는다. 허용 목록과 같은 정규화(공백 제거·소문자)로
    돌려준다."""
    seen = _sdk_backed(monkeypatch, _tokens({_ORG_HEADER: " ORG-Test-0001 "}))

    organization = await AnthropicCredentialProbe().organization_of(FAKE_API_KEY)

    assert organization == "org-test-0001"
    (request,) = seen
    assert request.url.path == "/v1/messages/count_tokens"
    assert json.loads(request.content) == {
        "model": "claude-haiku-5-5",
        "messages": [{"role": "user", "content": "확인"}],
    }


@pytest.mark.parametrize("headers", [pytest.param({}, id="absent"), pytest.param({_ORG_HEADER: " "}, id="blank")])
async def test_missing_organization_header_reads_as_unverified(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    """헤더가 없거나 비면 조직 미확인(None)이다 — 빈 문자열을 조직으로 저장하면 미확인 항목이 확인된 것처럼 보인다."""
    _sdk_backed(monkeypatch, _tokens(headers))

    assert await AnthropicCredentialProbe().organization_of(FAKE_API_KEY) is None


async def test_probe_uses_the_given_key_and_host_whatever_the_env_says(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 는 명시 인자가 없으면 env 의 `ANTHROPIC_API_KEY`·`ANTHROPIC_BASE_URL` 을 읽는다. 다른 값을 심어 두어도 저장·확인
    요청은 붙여넣은 키로 Anthropic 기본 호스트에 가야 한다 — 아니면 다른 계정의 키를 확인하고 이 키를 저장한다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.example")
    seen = _sdk_backed(
        monkeypatch, lambda request: (_tokens() if request.url.path.endswith("count_tokens") else _message())(request)
    )
    probe = AnthropicCredentialProbe()

    await probe.organization_of(FAKE_API_KEY)
    await probe.check(
        FAKE_API_KEY, CheckGroup("claude-opus-5-5", ("opus",), "generation"), credential_id=_CREDENTIAL_ID
    )

    assert [(r.url.host, r.headers["x-api-key"]) for r in seen] == [("api.anthropic.com", FAKE_API_KEY)] * 2


async def test_probe_does_not_retry_a_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """재시도하지 않는다(SDK 기본은 2회) — 다시 시도는 운영자가 누른다. 조직 조회와 확인 둘 다 요청은 한 번이다."""
    seen = _sdk_backed(monkeypatch, _error(500, "api_error"))
    probe = AnthropicCredentialProbe()

    with pytest.raises(CredentialProbeError) as caught:
        await probe.organization_of(FAKE_API_KEY)
    result = await probe.check(
        FAKE_API_KEY, CheckGroup("claude-opus-5-5", ("opus",), "generation"), credential_id=_CREDENTIAL_ID
    )

    assert caught.value.kind == "unavailable"
    assert result == CheckCallResult(error_kind="unavailable", organization=None)
    assert len(seen) == 2


def _raise_read_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("read timed out", request=request)


@pytest.mark.parametrize(
    ("respond", "expected"),
    [
        pytest.param(_error(401, "authentication_error"), "auth", id="401"),
        pytest.param(_error(402, "billing_error"), "credit", id="402"),
        pytest.param(
            _error(400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API."),
            "credit",
            id="400-low-credit",
        ),
        pytest.param(_error(403, "permission_error"), "permission", id="403"),
        pytest.param(_error(404, "not_found_error"), "model-not-found", id="404"),
        pytest.param(
            _error(429, "rate_limit_error", "cap", {"error_code": "enforced_spend_limit_reached"}),
            "limit",
            id="429-spend-cap",
        ),
        pytest.param(_error(429, "rate_limit_error"), "unavailable", id="429"),
        pytest.param(_error(529, "overloaded_error"), "unavailable", id="529"),
        pytest.param(_error(500, "api_error"), "unavailable", id="500"),
        pytest.param(_raise_read_timeout, "unavailable", id="read-timeout"),
    ],
)
async def test_probe_status_errors_map_to_failure_kinds(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx2.Request], httpx2.Response], expected: str
) -> None:
    """SDK 가 상태 오류에서 만든 예외를 실패 종류 하나로 바꿔 올린다 — 저장 라우트가 이 종류로 422 사유와 503 을 가른다."""
    _sdk_backed(monkeypatch, respond)

    with pytest.raises(CredentialProbeError) as caught:
        await AnthropicCredentialProbe().organization_of(FAKE_API_KEY)

    assert caught.value.kind == expected


async def test_probe_errors_carry_only_the_failure_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """하위 계층 오류 문장이 키를 실어도(헤더 값을 문장에 싣는 계층이 있다) 조사 예외의 문장과 원인 사슬에는 실패 종류만
    남는다. 사슬은 오류 추적이 걷는 규칙대로 — 원인, 원인이 없고 감추지 않았으면 맥락 — 따라간다."""

    def leaking(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"cannot send header value {FAKE_API_KEY!r}", request=request)

    _sdk_backed(monkeypatch, leaking)

    with pytest.raises(CredentialProbeError) as caught:
        await AnthropicCredentialProbe().organization_of(FAKE_API_KEY)

    texts: list[str] = []
    current: BaseException | None = caught.value
    while current is not None:
        texts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    assert texts == ["CredentialProbeError: unavailable"]


# ── 확인 호출 ────────────────────────────────────────────────────────────────────
async def test_generation_shape_request_matches_production_generation_with_a_small_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """생성 꼴은 운영 채팅 생성과 같은 인자에 출력 상한만 작다: 사고 설정을 싣지 않고(글쓰기 모델은 끌 수 없다) 깊이를
    채팅 생성 깊이로 보낸다. 지시문·멈춤 문자열·계정 단서는 싣지 않고, 헤더·사용량이 응답 하나에 오게 비스트림이다. 받아들여진
    호출의 사용량은 결과에 실려 그 항목의 추정 사용액에 쌓인다."""
    seen = _sdk_backed(monkeypatch, _message())

    result = await AnthropicCredentialProbe().check(
        FAKE_API_KEY, CheckGroup("claude-opus-5-5", ("opus",), "generation"), credential_id=_CREDENTIAL_ID
    )

    assert result == CheckCallResult(error_kind=None, organization=None, usage=to_usage(12, 0, 0, 16))
    (request,) = seen
    assert request.url.path == "/v1/messages"
    assert json.loads(request.content) == {
        "model": "claude-opus-5-5",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "확인"}],
        "output_config": {"effort": "low"},
    }


@pytest.mark.parametrize(
    ("model_id", "extra"),
    [
        pytest.param(
            "claude-haiku-5-5",
            {"thinking": {"type": "disabled"}, "output_config": {"effort": "medium"}},
            id="haiku-5-turns-thinking-off-and-sends-the-judgment-effort",
        ),
        pytest.param("claude-haiku-4-5", {}, id="haiku-4-5-sends-neither"),
    ],
)
async def test_judgment_shape_request_follows_structured_reasoning(
    monkeypatch: pytest.MonkeyPatch, model_id: str, extra: dict[str, object]
) -> None:
    """판정 꼴은 운영 판정 요청의 사고·깊이 규칙을 그대로 따른다(응답 형식 스키마는 싣지 않는다) — 판정 전용 id 가 그 규칙을
    받아들이는지가 확인할 성질이다."""
    seen = _sdk_backed(monkeypatch, _message())

    await AnthropicCredentialProbe().check(
        FAKE_API_KEY, CheckGroup(model_id, ("haiku",), "judgment"), credential_id=_CREDENTIAL_ID
    )

    (request,) = seen
    assert json.loads(request.content) == {
        "model": model_id,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "확인"}],
        **extra,
    }


async def test_check_reads_the_organization_header_of_each_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """확인은 응답마다 조직 헤더를 정규화해 돌려준다(대조는 라우터가 한다). 거절된 호출은 종류만 있고 헤더·사용량은 없다."""
    responses = iter(
        [
            _message({_ORG_HEADER: "Org-Test-0001"}),
            _message(),
            _error(402, "billing_error"),
        ]
    )
    _sdk_backed(monkeypatch, lambda request: next(responses)(request))
    probe = AnthropicCredentialProbe()
    group = CheckGroup("claude-opus-5-5", ("opus",), "generation")

    results = [await probe.check(FAKE_API_KEY, group, credential_id=_CREDENTIAL_ID) for _ in range(3)]

    assert results == [
        CheckCallResult(error_kind=None, organization="org-test-0001", usage=to_usage(12, 0, 0, 16)),
        CheckCallResult(error_kind=None, organization=None, usage=to_usage(12, 0, 0, 16)),
        CheckCallResult(error_kind="credit", organization=None),
    ]
