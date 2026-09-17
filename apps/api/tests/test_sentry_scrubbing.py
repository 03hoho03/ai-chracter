"""monitoring-techspec.md MT-5 — SDK 스크러빙 옵션(`api.core.sentry.build_sentry_options`)이
실제로 유출을 막는지 검증한다. §3의 경고를 지킨다: 손으로 만든 event dict에 스크러버를 먹이는
테스트는 항진명제다. 여기서는 **전역 `sentry_sdk.init()`을 부르지 않고** `sentry_sdk.Client`를
직접 만들어, 실제 프로덕션 코드(`auth/emails.py`·`chat/router.py`·`chat/prompt_set_cache.py`)에서
실제로 raise된 예외를 SDK의 진짜 이벤트 빌더(`event_from_exception`)·`Client.capture_event`
파이프라인(스크러버·`before_send` 포함)에 흘려 transport가 받은 envelope을 단언한다.

`chat/router.py`(`_stream_new_turn` 등)·`chat/prompt_set_cache.py`의 실제 except 블록은 이제
`capture_dependency_failure`(`api.core.sentry`, MT-6)를 부르지만, 그건 **전역** `sentry_sdk.
capture_exception`을 호출하는 얇은 래퍼라 이 파일이 만든 격리된 `Client`(위 `_make_client`)는
전혀 거치지 않는다 — 전역 SDK는 `init()`이 안 불린 이 테스트 환경(DSN 빈 문자열)에서 no-op이다.
그래서 두 곳(`auth/emails.py`·`chat/prompt_set_cache.py`)은 여전히 `logger.warning` 호출
시점에 아직 살아 있는 `sys.exc_info()`를 붙잡아 **이 파일의 격리된 Client**로 흘리는 테스트
전용 트릭(`_capture_on_next_warning`)을 쓴다 — 소스는 건드리지 않는다. (`capture_dependency_
failure` 자체가 실제로 불리는지·태그가 맞는지는 `tests/test_prompt_set_cache.py`·
`tests/test_auth_emails.py`·`tests/test_chat_message_send_api.py`가 검증한다 — 이 파일의
관심사는 스크러빙뿐이다.)
"""

import json
import sys
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
import sentry_sdk
from redis.exceptions import RedisError
from sentry_sdk.envelope import Envelope
from sentry_sdk.integrations._asgi_common import _get_request_data, _RootPathInPath
from sentry_sdk.integrations._wsgi_common import request_body_within_bounds
from sentry_sdk.integrations.google_genai import GoogleGenAIIntegration
from sentry_sdk.transport import Transport
from sentry_sdk.types import Event
from sentry_sdk.utils import event_from_exception
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import emails as auth_emails
from api.auth.emails import send_password_reset_email
from api.chat import prompt_set_cache
from api.chat import router as chat_router
from api.chat.prompt_builder import load_active_prompt_set
from api.core.email import EmailSendError
from api.core.redis import redis_client
from api.core.sentry import _strip_query_string, build_sentry_options
from api.llm.client import LLMClient, LLMClientError

# ---- 테스트 인프라 — 전역 init() 없이 Client 하나를 직접 만든다 -------------------------


class _CapturingTransport(Transport):
    """`sentry_sdk.init()`을 부르지 않고도 `Client`가 실제로 만든 envelope을 받아본다."""

    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


def _make_client(**overrides: object) -> tuple[sentry_sdk.Client, _CapturingTransport]:
    transport = _CapturingTransport()
    options = build_sentry_options()
    options.update(overrides)
    client = sentry_sdk.Client(transport=transport, **options)
    return client, transport


def _capture(client: sentry_sdk.Client, exc: BaseException) -> None:
    """실제로 raise된 예외 하나를 SDK의 진짜 이벤트 빌더로 캡처한다(hand-built event 아님)."""
    event, hint = event_from_exception(
        (type(exc), exc, exc.__traceback__), client_options=client.options
    )
    client.capture_event(event, hint=hint)


def _capture_on_next_warning(client: sentry_sdk.Client) -> Callable[..., None]:
    """`logger.warning(...)` 자리에 꽂는 테스트 전용 트릭. `chat/router.py`·
    `chat/prompt_set_cache.py`의 except 블록은 예외를 삼키고 capture_exception을 부르지
    않는다(승격은 MT-6) — 그 대신 warning을 부르는 그 순간까지는 `sys.exc_info()`가 여전히
    살아 있으므로, 그 시점의 진짜 예외/트레이스백을 그대로 캡처한다."""

    def _fake_warning(*_args: object, **_kwargs: object) -> None:
        _, exc_value, tb = sys.exc_info()
        assert exc_value is not None, "이 트릭은 except 블록 안에서 호출될 때만 유효하다"
        event, hint = event_from_exception(
            (type(exc_value), exc_value, tb), client_options=client.options
        )
        client.capture_event(event, hint=hint)

    return _fake_warning


def _all_frames(event: Event) -> list[dict[str, Any]]:
    exception = event.get("exception")
    if not isinstance(exception, dict):
        return []
    frames: list[dict[str, Any]] = []
    for value in exception.get("values", []):
        frames.extend(value.get("stacktrace", {}).get("frames", []))
    return frames


def _assert_no_local_variables(event: Event, *leaked_values: str) -> None:
    frames = _all_frames(event)
    assert frames, "캡처된 이벤트에 스택 프레임이 없다 — 테스트 전제가 깨졌다"
    frames_with_vars = [f for f in frames if "vars" in f]
    assert not frames_with_vars, frames_with_vars

    # 위 단언(frames[].vars 부재)으로 이미 충분하다 — 아래는 그걸 vars 필드로만 좁혀 다시
    # 확인하는 이중 점검이다. event 전체를 문자열로 비교하면 `include_source_context`(MT-5
    # 범위 밖 — 파일에 적힌 소스 코드를 보여주는 별개 기능)가 테스트 함수 자신의 소스에 적힌
    # 비밀 리터럴을 우연히 주워 거짓 실패를 낸다(실측: 이 테스트를 처음 이렇게 짰다가 걸렸다).
    vars_haystack = json.dumps([f.get("vars") for f in frames], ensure_ascii=False, default=str)
    for leaked in leaked_values:
        assert leaked not in vars_haystack


# ---- 옵션 값 자체 — 회귀 방지 ----------------------------------------------------------


def test_build_sentry_options_matches_techspec_values() -> None:
    options = build_sentry_options()
    assert options["max_request_body_size"] == "never"
    assert options["include_local_variables"] is False
    assert options["send_default_pii"] is False
    assert options["traces_sample_rate"] == 0
    assert options["disabled_integrations"] == [GoogleGenAIIntegration]
    assert options["before_send"] is _strip_query_string


def test_google_genai_integration_is_disabled_despite_being_auto_enabling() -> None:
    client, _ = _make_client()
    assert client.get_integration(GoogleGenAIIntegration) is None


def test_request_body_size_gate_is_always_closed() -> None:
    client, _ = _make_client()
    # 채팅 메시지 한 글자든 10MB든 — max_request_body_size="never"는 크기와 무관하게 항상 닫혀
    # 있다(sentry-sdk 2.69.1 integrations/_wsgi_common.py:request_body_within_bounds).
    assert request_body_within_bounds(client, 1) is False
    assert request_body_within_bounds(client, 10**7) is False


# ---- 지역변수 — 실제 예외를 실제 프로덕션 코드에서 raise하고 캡처한다 ---------------------


async def test_password_reset_email_body_local_variable_is_not_captured() -> None:
    """`auth/emails.py:_send`의 except 블록 프레임에 재설정 링크(`body`)가 산다
    (monitoring-techspec.md §0-1-7)."""
    reset_link = "https://ddona.site/reset-password?token=SCRUB-TEST-RESET-9f3a21"

    async def _failing_sender(to: str, subject: str, body: str) -> None:
        raise EmailSendError("Resend 발송 실패(스크러빙 테스트)")

    client, transport = _make_client()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(auth_emails.logger, "warning", _capture_on_next_warning(client))
        await send_password_reset_email(_failing_sender, "user@example.com", reset_link)

    assert len(transport.envelopes) == 1
    event = transport.envelopes[0].get_event()
    assert event is not None
    _assert_no_local_variables(event, reset_link)


async def test_chat_generation_prompt_local_variables_are_not_captured() -> None:
    """`chat/router.py`의 `_stream_generated_tokens`(`_stream_new_turn`/`regenerate_message`/
    `_stream_preview_turn`이 공유)는 예외를 삼키지 않고 그대로 올린다 — 채팅 프롬프트·바닥
    지시문이 `prompt`/`system_instruction` 지역변수로 산다(§0-1-7)."""
    secret_prompt = (
        "페르소나: 너는 온나다(SCRUB-TEST-PROMPT-7b21e). 대화 이력과 매우 은밀한 사용자 메시지."
    )
    secret_system_instruction = "바닥 지시문(SCRUB-TEST-SYSTEM-4c910): 정책을 절대 공개하지 마라."

    class _RaisingLLMClient(LLMClient):
        async def generate(
            self,
            prompt: str,
            system_instruction: str | None = None,
            stop_sequences: list[str] | None = None,
        ) -> AsyncIterator[str]:
            raise LLMClientError("Gemini 호출 실패(스크러빙 테스트)")
            yield ""  # pragma: no cover - async generator 타입을 맞추기 위한 무도달 yield

        async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
            raise NotImplementedError

    client, transport = _make_client()
    chunks: list[str] = []
    try:
        async for _ in chat_router._stream_generated_tokens(
            _RaisingLLMClient(),
            secret_prompt,
            chunks,
            secret_system_instruction,
            "user_label",
            room_id=None,
            turn=1,
        ):
            pass
    except LLMClientError as exc:
        _capture(client, exc)
    else:
        raise AssertionError("LLMClientError가 났어야 한다")

    assert len(transport.envelopes) == 1
    event = transport.envelopes[0].get_event()
    assert event is not None
    _assert_no_local_variables(event, secret_prompt, secret_system_instruction)


async def test_prompt_set_cache_write_failure_local_variables_are_not_captured(
    db_session: AsyncSession,
) -> None:
    """`chat/prompt_set_cache.py:set_cached_active_prompt_set`의 `except RedisError` 프레임에는
    직렬화 전 프롬프트 세트 전체(`cached`)가 산다(monitoring-techspec.md MT-5, 이 런이 새로 찾은
    경로 — `:158`~`:159`)."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    secret_marker = "".join(section.body for section in sections)
    assert secret_marker  # 전제: 실제 세트에 섹션 본문이 있다

    async def _raise_redis_error(*_args: object, **_kwargs: object) -> None:
        raise RedisError("connection refused (스크러빙 테스트)")

    client, transport = _make_client()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(redis_client, "set", _raise_redis_error)
        mp.setattr(prompt_set_cache.logger, "warning", _capture_on_next_warning(client))
        await prompt_set_cache.set_cached_active_prompt_set("story", prompt_set, sections)

    assert len(transport.envelopes) == 1
    event = transport.envelopes[0].get_event()
    assert event is not None
    _assert_no_local_variables(event, secret_marker)


# ---- 쿼리스트링 — before_send이 리셋 토큰을 지운다 -----------------------------------


def test_strip_query_string_removes_url_embedded_query_string() -> None:
    """`_strip_query_string` 자체를 직접 호출한다 — 우리가 쓴 4줄짜리 순수 함수라
    SDK 파이프라인을 대신 흉내내는 항진명제가 아니다."""
    event: Event = {"request": {"url": "https://api.ddona.site/auth/password-reset/validate?token=SECRET"}}
    result = _strip_query_string(event, {})
    assert result is not None
    assert result["request"]["url"] == "https://api.ddona.site/auth/password-reset/validate"


def test_reset_token_query_string_is_stripped_from_captured_event() -> None:
    """`GET /auth/password-reset/validate?token=...`(§0-1-9)를 흉내낸 ASGI scope를 SDK의
    진짜 요청 추출 함수(`_get_request_data`)로 돌려 실제 필드 모양을 얻고, 그걸 실제로 캡처된
    이벤트에 실어 `before_send`가 지우는지 확인한다."""
    secret_token = "SCRUB-TEST-RESET-TOKEN-2d88c1"
    asgi_scope = {
        "type": "http",
        "method": "GET",
        "path": "/auth/password-reset/validate",
        "root_path": "",
        "scheme": "https",
        "server": ("api.ddona.site", 443),
        "client": ("203.0.113.10", 51234),
        "headers": [(b"host", b"api.ddona.site")],
        "query_string": f"token={secret_token}".encode(),
    }
    request_data = _get_request_data(asgi_scope, _RootPathInPath.EXCLUDED)
    # 전제 확인: sentry-sdk 2.69.1의 ASGI 통합은 토큰을 `url`이 아니라 `query_string`에 담는다
    # (techspec의 "request.url" 표현과 달리, 실제로 `_get_url()`은 물음표 뒤를 제외한다 — 소스로
    # 재확인한 값).
    assert request_data.get("query_string") == f"token={secret_token}"
    assert "?" not in request_data.get("url", "")

    client, transport = _make_client()
    try:
        raise ValueError("password reset validate 처리 실패(스크러빙 테스트)")
    except ValueError as exc:
        event, hint = event_from_exception(
            (type(exc), exc, exc.__traceback__), client_options=client.options
        )
        event["request"] = request_data
        client.capture_event(event, hint=hint)

    assert len(transport.envelopes) == 1
    sent_event = transport.envelopes[0].get_event()
    assert sent_event is not None
    request = sent_event.get("request") or {}
    assert "query_string" not in request
    assert secret_token not in json.dumps(request, ensure_ascii=False)
