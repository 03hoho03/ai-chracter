"""Claude 자격 목록 경로의 Anthropic 직결 호출 — 라우팅 클라이언트 공개 경로로 부르고 SDK 경계만 키별 가짜로 둔다.

- 첫 이벤트 전(HTTP 상태로 온) 거절 가운데 소진으로 볼 것만 그 항목을 소진으로 표시하고 다음 항목으로 **같은 요청**을 보낸다.
  그 밖의 오류(권한·모델 없음·과부하·서버 오류·시간 초과·연결)는 지금 env 키 경로와 같은 예외로 올리고 항목을 건드리지 않는다.
- 스트림이 열린 뒤의 오류는 다시 보내지 않는다 — 글이 이미 나갔을 수 있다. 결제 오류 종류면 표시만 해 다음 요청이 다음 항목으로
  간다.
- 항목이 하나도 남지 않으면 전용 예외(환불 경로)이고 env 키로 떨어지지 않는다. 알림은 쏘고 잊는다.
- 소진 표시는 방패 너머 태스크라 상한(테스트에서 줄인다)을 넘겨도 다음 항목이 기다리지 않고, 표시·무효화·알림은 끝까지 돈다.

풀의 세션은 테스트 커넥션 위의 SAVEPOINT 로 열어 셋업과 같은 트랜잭션을 본다. 가짜 SDK 는 `anthropic_api._new_sdk` 자리에 끼워
env 키·목록 항목 모두 여기서 만들어진다 — 어느 키로 몇 번 보냈는지가 그대로 보인다."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
import sqlalchemy as sa
from anthropic.types import Message
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.core.field_crypto import FieldKeyring
from api.core.redis import redis_client
from api.db.models.llm_credential import ClaudeModelAxis, LlmCredential
from api.llm import anthropic_api as anthropic_module
from api.llm import credential_notify, credential_pool
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.client import (
    CallUsage,
    LLMCallContext,
    LLMClientError,
    LLMCredentialPoolEmptyError,
    LLMRateLimitError,
)
from api.llm.credential_pool import GENERATION_KEY, CredentialPool, invalidate_pool_snapshot
from api.llm.credential_usage import CredentialSpend, SpendTarget, read_credential_spend
from api.llm.credentials import replace_secret
from api.llm.routing import RoutingLLMClient
from factories import (
    FAKE_ANTHROPIC_ORG,
    FAKE_API_KEY,
    FAKE_CREDENTIAL_KEYRING,
    FAKE_OTHER_API_KEY,
    _add_llm_credential,
    _add_llm_credential_check,
    _cancel_credential_tasks,
    _capture_credential_alerts,
    _NeverCalledLLMClient,
    _set_llm_credential_pool,
    _settle_credential_tasks,
)

_ORG = FAKE_ANTHROPIC_ORG
_OTHER_ORG = "org-test-0002"
_ENV_KEY = "sk-ant-test-routing-env-key-000000000000"
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
_EXHAUSTION_ALERT = "[Claude 자격] 소진 — "
_NO_CANDIDATE_ALERT = "[Claude 자격] opus 모델을 보낼 항목이 없다"


@pytest.fixture(autouse=True)
def pool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """스위치를 켜고 상위 모델 생성·판정을 이 구현에 배정한다. 요청 인자에 닿는 모델 id 는 env 파일과 무관하게 고정한다."""
    for name, value in {
        "llm_credential_pool_enabled": True,
        "llm_credential_encryption_keys": FAKE_CREDENTIAL_KEYRING,
        "llm_credential_allowed_accounts": f"anthropic:{_ORG},anthropic:{_OTHER_ORG}",
        "anthropic_direct_api_key": _ENV_KEY,
        "anthropic_opus_model_id": "claude-opus-5-5",
        "anthropic_sonnet_model_id": "claude-sonnet-5-5",
        "anthropic_haiku_writer_model_id": "claude-haiku-5-5",
        "anthropic_haiku_model_id": "claude-haiku-5-5",
        "stat_judgment_model": "haiku",
        "llm_call_site_backends": {"chat_generate": "anthropic", "chat_stat_judgment": "anthropic"},
    }.items():
        monkeypatch.setattr(settings, name, value)


@pytest.fixture(autouse=True)
async def _no_leftover_tasks() -> AsyncIterator[None]:
    """일부러 멈춰 둔 표시·알림 태스크가 다음 테스트로 넘어가지 않게 끝에서 취소한다(이벤트 루프를 모든 테스트가 함께 쓴다)."""
    yield
    await _cancel_credential_tasks()


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return _capture_credential_alerts(monkeypatch)


# ── 가짜 SDK ──────────────────────────────────────────────────────────────────────
def _start() -> Any:
    usage = SimpleNamespace(input_tokens=700, cache_read_input_tokens=200, cache_creation_input_tokens=100, output_tokens=1)
    return SimpleNamespace(type="message_start", message=SimpleNamespace(usage=usage))


def _thinking() -> Any:
    return SimpleNamespace(
        type="content_block_start", index=0, content_block=SimpleNamespace(type="thinking", thinking="")
    )


def _text(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _end() -> Any:
    usage = SimpleNamespace(
        output_tokens=70,
        input_tokens=None,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
        output_tokens_details=SimpleNamespace(thinking_tokens=20),
    )
    return SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"), usage=usage)


_REPLY = [_start(), _text("안녕"), _text("하세요"), _end()]


def _message() -> Message:
    return Message.model_validate(
        {
            "id": "msg_routing",
            "type": "message",
            "role": "assistant",
            "model": "m",
            "content": [{"type": "text", "text": '{"rule_ids": ["r1"]}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 300, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 0, "output_tokens": 9},
        }
    )


_STATUS_CLASSES: dict[int, type[anthropic.APIStatusError]] = {
    400: anthropic.BadRequestError,
    401: anthropic.AuthenticationError,
    403: anthropic.PermissionDeniedError,
    404: anthropic.NotFoundError,
    413: anthropic.RequestTooLargeError,
    429: anthropic.RateLimitError,
    500: anthropic.InternalServerError,
    529: anthropic.OverloadedError,
}


def _status_error(status: int, error_type: str, message: str, **extra: object) -> anthropic.APIStatusError:
    """SDK 가 그 상태로 올리는 클래스 그대로(HTTP 오류 응답). 상태 200 은 스트림 도중의 SSE 오류 이벤트다."""
    body = {"type": "error", "error": {"type": error_type, "message": message, **extra}}
    cls = _STATUS_CLASSES.get(status, anthropic.APIStatusError)
    return cls(str(body), response=httpx2.Response(status, request=_REQUEST), body=body)


def _no_real_sdk(**kwargs: Any) -> Any:
    raise AssertionError("가짜 SDK 를 지나지 않고 진짜 SDK 클라이언트를 만들려 했다")


@dataclass
class _Reply:
    """키 하나의 응답 — create 에서 낼 예외, 스트림 이벤트(뒤에 낼 예외 포함), 또는 비스트림 메시지."""

    error: BaseException | None = None
    events: list[Any] = field(default_factory=lambda: list(_REPLY))
    stream_error: BaseException | None = None
    message: Message | None = None


class _FakeSdks:
    """키별 가짜 SDK. `replies` 에 없는 키는 정상 응답이다. 받은 요청은 키마다 모은다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.replies: dict[str, _Reply] = {}
        self.requests: dict[str, list[dict[str, Any]]] = {}
        self.built: list[str] = []
        monkeypatch.setattr(anthropic_module, "_new_sdk", self._build)
        # 이 가짜를 지나지 않고 진짜 SDK 를 만드는 길이 생기면 네트워크로 나가기 전에 멈춘다.
        monkeypatch.setattr(anthropic_module, "AsyncAnthropic", _no_real_sdk)

    def _build(self, api_key: str) -> Any:
        self.built.append(api_key)
        return SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: self._create(api_key, kwargs)))

    async def _create(self, api_key: str, kwargs: dict[str, Any]) -> Any:
        self.requests.setdefault(api_key, []).append(kwargs)
        reply = self.replies.get(api_key, _Reply())
        if reply.error is not None:
            raise reply.error
        if not kwargs.get("stream"):
            return reply.message or _message()

        async def stream() -> AsyncIterator[Any]:
            for event in reply.events:
                yield event
            if reply.stream_error is not None:
                raise reply.stream_error

        return stream()

    def sent(self, api_key: str) -> int:
        return len(self.requests.get(api_key, []))


@pytest.fixture(autouse=True)
def sdks(monkeypatch: pytest.MonkeyPatch) -> _FakeSdks:
    return _FakeSdks(monkeypatch)


# ── 풀·세션 ─────────────────────────────────────────────────────────────────────────
class _Sessions:
    """풀이 여는 짧은 세션을 테스트 커넥션 위 SAVEPOINT 로 연다. 세션은 연 순서(1부터)로 센다. `hold` 의 회차 세션은 닫힌 뒤(커밋이
    끝난 뒤) 그 함수가 끝날 때까지 돌려주지 않는다. `broken` 이 서면 그 뒤로 여는 세션이 그 예외를 내고, `hang` 이면 답하지
    않는다. 세션이 테스트 커넥션 하나를 함께 쓰므로 테스트는 풀이 세션을 쥔 동안 그 커넥션으로 조회하지 않는다 — 기다릴 일은
    `hold` 함수로 알린다."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._inner = async_sessionmaker(
            bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        self.opened = 0
        self.hold: dict[int, Callable[[], Awaitable[object]]] = {}
        self.broken: BaseException | None = None
        self.hang = False

    def __call__(self) -> Any:
        self.opened += 1
        return self._session(self.opened)

    @asynccontextmanager
    async def _session(self, number: int) -> AsyncIterator[AsyncSession]:
        if self.hang:
            await asyncio.Event().wait()
        if self.broken is not None:
            raise self.broken
        async with self._inner() as session:
            yield session
        hold = self.hold.get(number)
        if hold is not None:
            await hold()


@dataclass
class _Setup:
    router: RoutingLLMClient
    pool: CredentialPool
    sessions: _Sessions
    built: list[AnthropicLLMClient]

    @property
    def anthropic(self) -> AnthropicLLMClient:
        (client,) = self.built
        return client


def _route(db_session: AsyncSession) -> _Setup:
    """공개 경로: 배정이 상위 모델을 이 구현으로 보내는 라우팅 클라이언트. 구현은 처음 쓸 때 테스트 풀로 만든다."""
    sessions = _Sessions(db_session)
    pool = CredentialPool(session_factory=sessions, redis=redis_client)
    built: list[AnthropicLLMClient] = []

    def build() -> AnthropicLLMClient:
        client = AnthropicLLMClient(pool=pool)
        built.append(client)
        return client

    return _Setup(RoutingLLMClient(_NeverCalledLLMClient(), factories={"anthropic": build}), pool, sessions, built)


async def _two_items(db_session: AsyncSession) -> tuple[LlmCredential, LlmCredential]:
    """목록 사용을 켜고 모든 축이 통과한 켜진 항목 둘(위치 순)."""
    await _set_llm_credential_pool(db_session, True)
    first = await _add_llm_credential(db_session, "첫째 계정")
    await _add_llm_credential_check(db_session, first)
    second = await _add_llm_credential(db_session, "둘째 계정", secret=FAKE_OTHER_API_KEY, account_ref=_OTHER_ORG)
    await _add_llm_credential_check(db_session, second)
    return first, second


async def _state(db_session: AsyncSession, credential: LlmCredential) -> tuple[str, str | None, int]:
    row = (
        await db_session.execute(
            sa.select(LlmCredential.state, LlmCredential.state_reason, LlmCredential.state_version).where(
                LlmCredential.id == credential.id
            )
        )
    ).one()
    return row.state, row.state_reason, row.state_version


async def _generation() -> int:
    return int(await redis_client.get(GENERATION_KEY) or 0)


def _chat(sink: list[CallUsage] | None = None) -> LLMCallContext:
    return LLMCallContext("chat_generate", None, None, model="opus", usage_sink=sink)


async def _generate(router: RoutingLLMClient, sink: list[CallUsage] | None = None) -> str:
    return "".join([token async for token in router.generate("대본", "지시문", ["나:"], usage=_chat(sink))])


class _Verdict(BaseModel):
    rule_ids: list[str]


async def _judge(router: RoutingLLMClient, sink: list[CallUsage] | None = None) -> _Verdict:
    """방의 모델은 opus 지만 판정 모델은 haiku 인 스탯 판정."""
    context = LLMCallContext("chat_stat_judgment", None, None, model="opus", usage_sink=sink)
    return await router.generate_structured("판정 프롬프트", _Verdict, usage=context)


# ── SDK 클라이언트 캐시 ───────────────────────────────────────────────────────────────
async def test_sdk_client_is_reused_for_the_same_item_and_secret(db_session: AsyncSession, sdks: _FakeSdks) -> None:
    await _two_items(db_session)
    setup = _route(db_session)

    await _generate(setup.router)
    await _generate(setup.router)

    assert sdks.built == [FAKE_API_KEY]
    assert sdks.sent(FAKE_API_KEY) == 2


async def test_replacing_the_secret_builds_a_new_client_and_drops_the_old(
    db_session: AsyncSession, sdks: _FakeSdks
) -> None:
    """키를 바꾸면 (항목, 지문)이 달라져 새 클라이언트를 만들고, 옛 키의 클라이언트는 다음 호출에서 버린다."""
    first, _ = await _two_items(db_session)
    setup = _route(db_session)
    await _generate(setup.router)

    third_key = "sk-ant-test-" + "thirdkey0123456789thirdkey0123456789abcdef"
    replace_secret(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING), first, third_key)
    await db_session.flush()
    await _add_llm_credential_check(db_session, first)
    await invalidate_pool_snapshot()
    await _generate(setup.router)

    assert sdks.built == [FAKE_API_KEY, third_key]
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(third_key)) == (1, 1)
    assert set(setup.anthropic._pool_clients) == {(first.id, first.secret_fingerprint)}


async def test_unreadable_secret_skips_the_item_and_alerts_once(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    """키링에 없는 키 id 로 만든 항목은 건너뛰고 다음 항목으로 간다 — 복호화 실패가 호출 밖으로 나가지 않는다. 같은 항목·키는
    두 번 불러도 한 번만 알린다."""
    await _set_llm_credential_pool(db_session, True)
    unreadable = await _add_llm_credential(db_session, "첫째 계정", key_id="k9")
    await _add_llm_credential_check(db_session, unreadable)
    readable = await _add_llm_credential(db_session, "둘째 계정", secret=FAKE_OTHER_API_KEY, account_ref=_OTHER_ORG)
    await _add_llm_credential_check(db_session, readable)
    setup = _route(db_session)

    assert await _generate(setup.router) == "안녕하세요"
    assert await _generate(setup.router) == "안녕하세요"
    await _settle_credential_tasks()

    assert sdks.built == [FAKE_OTHER_API_KEY]
    assert alerts == [
        "[Claude 자격] 저장한 키를 읽을 수 없어 건너뛴다 — anthropic · 첫째 계정 · 지문 "
        f"{unreadable.secret_fingerprint} · 암호화 키 목록을 확인하거나 키를 다시 붙여넣는다"
    ]
    assert await _state(db_session, unreadable) == ("active", None, unreadable.state_version)


# ── 전환 ──────────────────────────────────────────────────────────────────────────
_REJECTIONS = [
    pytest.param(_status_error(402, "invalid_request_error", "payment required"), "credit", id="402"),
    pytest.param(
        _status_error(400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API."),
        "credit",
        id="400-credit-balance",
    ),
    pytest.param(_status_error(400, "billing_error", "billing problem"), "credit", id="400-billing-error-type"),
    pytest.param(_status_error(401, "authentication_error", "invalid x-api-key"), "auth", id="401"),
    pytest.param(
        _status_error(400, "invalid_request_error", "This organization has been disabled."),
        "auth",
        id="400-organization-disabled",
    ),
    pytest.param(
        _status_error(
            429, "rate_limit_error", "monthly limit", details={"error_code": "enforced_spend_limit_reached"}
        ),
        "limit",
        id="429-monthly-spend-limit",
    ),
    pytest.param(
        _status_error(400, "invalid_request_error", "You have reached your specified workspace API usage limits."),
        "limit",
        id="400-workspace-limit",
    ),
]


@pytest.mark.parametrize(("rejection", "kind"), _REJECTIONS)
async def test_rejection_sends_the_same_request_to_the_next_item(
    db_session: AsyncSession,
    sdks: _FakeSdks,
    alerts: list[str],
    rejection: anthropic.APIStatusError,
    kind: str,
) -> None:
    """소진으로 볼 거절이면 그 항목을 그 사유로 소진 표시(판 +1)하고 다음 항목으로 같은 인자의 요청을 한 번 보낸다. 글과 기록은
    다음 항목 것이다."""
    first, second = await _two_items(db_session)
    sdks.replies[FAKE_API_KEY] = _Reply(error=rejection)
    setup = _route(db_session)
    sink: list[CallUsage] = []

    text = await _generate(setup.router, sink)
    await _settle_credential_tasks()

    assert text == "안녕하세요"
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 1)
    assert sdks.requests[FAKE_API_KEY][0] == sdks.requests[FAKE_OTHER_API_KEY][0]
    assert await _state(db_session, first) == ("exhausted", kind, first.state_version + 1)
    assert await _state(db_session, second) == ("active", None, second.state_version)
    assert [record.as_record().get("credentialId") for record in sink] == [str(second.id)]
    assert [alert.split(" · ")[1] for alert in alerts] == ["첫째 계정"]
    assert alerts[0].startswith(_EXHAUSTION_ALERT)


_NOT_REJECTIONS = [
    pytest.param(_Reply(error=_status_error(403, "permission_error", "no access")), LLMClientError, None, id="403"),
    pytest.param(_Reply(error=_status_error(404, "not_found_error", "model")), LLMClientError, None, id="404"),
    pytest.param(_Reply(error=_status_error(413, "request_too_large", "big")), LLMClientError, None, id="413"),
    pytest.param(
        _Reply(error=_status_error(400, "invalid_request_error", "max_tokens: too large")),
        LLMClientError,
        None,
        id="other-400",
    ),
    pytest.param(_Reply(error=_status_error(429, "rate_limit_error", "slow down")), LLMRateLimitError, None, id="other-429"),
    pytest.param(_Reply(error=_status_error(529, "overloaded_error", "Overloaded")), LLMClientError, None, id="529"),
    pytest.param(_Reply(error=_status_error(500, "api_error", "internal")), LLMClientError, None, id="500"),
    pytest.param(_Reply(error=anthropic.APITimeoutError(_REQUEST)), LLMClientError, anthropic.APITimeoutError, id="create-timeout"),
    pytest.param(
        _Reply(error=anthropic.APIConnectionError(request=_REQUEST)),
        LLMClientError,
        anthropic.APIConnectionError,
        id="connection-error",
    ),
    pytest.param(
        _Reply(events=[_start(), _text("안녕")], stream_error=httpx2.ReadTimeout("slow", request=_REQUEST)),
        LLMClientError,
        httpx2.ReadTimeout,
        id="read-timeout-mid-stream",
    ),
]


@pytest.mark.parametrize(("reply", "raised", "cause"), _NOT_REJECTIONS)
async def test_errors_that_are_not_rejections_are_not_retried(
    db_session: AsyncSession,
    sdks: _FakeSdks,
    alerts: list[str],
    reply: _Reply,
    raised: type[LLMClientError],
    cause: type[BaseException] | None,
) -> None:
    """그 요청만의 실패는 다음 항목으로 보내지 않고 지금 env 키 경로와 같은 예외로 올린다. 항목은 켜진 채이고 알림도 없다."""
    first, _ = await _two_items(db_session)
    sdks.replies[FAKE_API_KEY] = reply
    setup = _route(db_session)
    before = await _generation()

    with pytest.raises(LLMClientError) as caught:
        await _generate(setup.router)
    await _settle_credential_tasks()

    assert type(caught.value) is raised
    if cause is not None:
        assert isinstance(caught.value.__cause__, cause)
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 0)
    assert await _state(db_session, first) == ("active", None, first.state_version)
    assert await _generation() == before
    assert alerts == []


async def test_structured_call_moves_to_the_next_item_on_rejection(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    first, second = await _two_items(db_session)
    sdks.replies[FAKE_API_KEY] = _Reply(error=_status_error(402, "billing_error", "Your credit balance is too low"))
    setup = _route(db_session)
    sink: list[CallUsage] = []

    verdict = await _judge(setup.router, sink)
    await _settle_credential_tasks()

    assert verdict == _Verdict(rule_ids=["r1"])
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 1)
    assert sdks.requests[FAKE_API_KEY][0] == sdks.requests[FAKE_OTHER_API_KEY][0]
    assert await _state(db_session, first) == ("exhausted", "credit", first.state_version + 1)
    assert [record.as_record().get("credentialId") for record in sink] == [str(second.id)]


@pytest.mark.parametrize(
    ("axes", "reaches"),
    [
        pytest.param(("haiku",), True, id="item-checked-only-on-the-judgment-axis"),
        pytest.param(("opus",), False, id="item-checked-only-on-the-room-axis"),
    ],
)
async def test_structured_call_picks_items_by_the_judgment_model_axis_not_the_room_model(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str], axes: tuple[ClaudeModelAxis, ...], reaches: bool
) -> None:
    """opus 방의 스탯 판정은 판정 모델(haiku)로 나간다 — 후보도 그 축으로 고른다."""
    await _set_llm_credential_pool(db_session, True)
    credential = await _add_llm_credential(db_session, "첫째 계정")
    await _add_llm_credential_check(db_session, credential, axes)
    setup = _route(db_session)

    if reaches:
        assert await _judge(setup.router) == _Verdict(rule_ids=["r1"])
        assert [request["model"] for request in sdks.requests[FAKE_API_KEY]] == ["claude-haiku-5-5"]
    else:
        with pytest.raises(LLMCredentialPoolEmptyError):
            await _judge(setup.router)
        assert sdks.built == []


@pytest.mark.parametrize(
    ("events", "before_error"),
    [
        pytest.param([_start(), _text("안녕")], ["안녕"], id="after-a-text-chunk"),
        pytest.param([_start(), _thinking()], [], id="after-a-thinking-block-only"),
    ],
)
async def test_error_after_the_stream_started_is_not_retried(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str], events: list[Any], before_error: list[str]
) -> None:
    """스트림이 열린 뒤의 오류는 다음 항목으로 보내지 않는다 — 글이 이미 나갔을 수 있다. 과부하는 소진이 아니라 항목도 그대로다."""
    first, _ = await _two_items(db_session)
    overloaded = _status_error(200, "overloaded_error", "Overloaded")
    sdks.replies[FAKE_API_KEY] = _Reply(events=events, stream_error=overloaded)
    setup = _route(db_session)
    received: list[str] = []

    with pytest.raises(LLMClientError) as caught:
        async for token in setup.router.generate("대본", "지시문", ["나:"], usage=_chat()):
            received.append(token)
    await _settle_credential_tasks()

    assert type(caught.value) is LLMClientError
    assert received == before_error
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 0)
    assert await _state(db_session, first) == ("active", None, first.state_version)
    assert alerts == []


async def test_billing_error_inside_the_stream_marks_the_item_without_retrying(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    """스트림 도중 결제 오류는 그 요청을 다시 보내지 않고 오류 그대로 올리되, 항목을 소진으로 표시해 다음 요청은 다음 항목으로
    간다."""
    first, _ = await _two_items(db_session)
    billing = _status_error(200, "billing_error", "Your credit balance is too low")
    sdks.replies[FAKE_API_KEY] = _Reply(events=[_start(), _text("안녕")], stream_error=billing)
    setup = _route(db_session)

    with pytest.raises(LLMClientError) as caught:
        await _generate(setup.router)
    await _settle_credential_tasks()

    assert type(caught.value) is LLMClientError
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 0)
    assert await _state(db_session, first) == ("exhausted", "credit", first.state_version + 1)

    assert await _generate(setup.router) == "안녕하세요"
    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 1)


async def test_all_items_rejected_raises_the_pool_empty_error_and_alerts_once(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    """모두 거절되면 전용 예외(원인 = 마지막 거절)다. 알림은 항목마다 소진 한 번과 후보 없음 한 번 — 같은 축으로 다시 불러도 SDK 를
    부르지 않고 더 알리지 않는다(첫 호출의 표시가 세대를 두 번 올렸어도 후보 없음 표지는 표시 뒤의 세대다)."""
    first, second = await _two_items(db_session)
    last = _status_error(402, "billing_error", "Your credit balance is too low")
    sdks.replies[FAKE_API_KEY] = _Reply(error=_status_error(402, "billing_error", "Your credit balance is too low"))
    sdks.replies[FAKE_OTHER_API_KEY] = _Reply(error=last)
    setup = _route(db_session)

    with pytest.raises(LLMCredentialPoolEmptyError) as caught:
        await _generate(setup.router)
    await _settle_credential_tasks()

    assert caught.value.__cause__ is last
    assert caught.value.provider == "anthropic"
    assert await _state(db_session, first) == ("exhausted", "credit", first.state_version + 1)
    assert await _state(db_session, second) == ("exhausted", "credit", second.state_version + 1)
    assert sorted(alert.split(" · ")[1] for alert in alerts if alert.startswith(_EXHAUSTION_ALERT)) == [
        "둘째 계정",
        "첫째 계정",
    ]
    assert [alert for alert in alerts if alert.startswith(_NO_CANDIDATE_ALERT)] == [
        "[Claude 자격] opus 모델을 보낼 항목이 없다 — 그 모델 호출이 실패·환불된다. 항목을 충전·확인·켜거나, 목록 사용을 끄면 env "
        "키 경로로 돈다"
    ]

    with pytest.raises(LLMCredentialPoolEmptyError):
        await _generate(setup.router)
    await _settle_credential_tasks()

    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 1)
    assert len(alerts) == 3


async def test_no_candidate_from_the_start_never_calls_the_sdk_or_the_env_key(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    """목록에 행이 있는데 보낼 항목이 없으면(모두 꺼짐) 원인 없는 전용 예외다 — env 키로 떨어지지 않는다."""
    await _set_llm_credential_pool(db_session, True)
    credential = await _add_llm_credential(db_session, "첫째 계정", state="disabled", state_reason="admin")
    await _add_llm_credential_check(db_session, credential)
    setup = _route(db_session)

    with pytest.raises(LLMCredentialPoolEmptyError) as caught:
        await _generate(setup.router)
    await _settle_credential_tasks()

    assert caught.value.__cause__ is None
    assert sdks.built == []
    assert len(alerts) == 1 and alerts[0].startswith(_NO_CANDIDATE_ALERT)


async def test_pool_with_only_bedrock_rows_raises_no_candidate_instead_of_using_the_env_key(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    """행이 있으면 오늘 경로가 아니다 — Bedrock 행만 있으면 Anthropic 후보가 없어 실패하고 env 키를 쓰지 않는다."""
    await _set_llm_credential_pool(db_session, True)
    bedrock = await _add_llm_credential(
        db_session, "Bedrock 계정", account_ref="123456789012", provider="bedrock", region="us-east-1"
    )
    await _add_llm_credential_check(db_session, bedrock)
    setup = _route(db_session)

    with pytest.raises(LLMCredentialPoolEmptyError):
        await _generate(setup.router)

    assert sdks.built == []


async def test_alerts_do_not_hold_up_the_call(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """알림 전송이 영원히 답하지 않아도 호출은 끝난다 — 소진·후보 없음 알림은 쏘고 잊는다. 표시 상한을 길게 두어 표시가 알림을
    기다리면 그만큼 멈추게 한다."""
    await _two_items(db_session)
    for key in (FAKE_API_KEY, FAKE_OTHER_API_KEY):
        sdks.replies[key] = _Reply(error=_status_error(402, "billing_error", "Your credit balance is too low"))
    never = asyncio.Event()

    async def hang(message: str) -> None:
        await never.wait()

    monkeypatch.setattr(credential_notify, "send_credential_notification", hang)
    monkeypatch.setattr(credential_pool, "MARK_TIMEOUT_SECONDS", 30.0)
    setup = _route(db_session)

    async with asyncio.timeout(2):
        with pytest.raises(LLMCredentialPoolEmptyError):
            await _generate(setup.router)


# ── 소진 표시가 실패하거나 느릴 때 ───────────────────────────────────────────────────────
_CANARY = "c4n4ry-ciphertext-hex"


@pytest.mark.parametrize("failure", [pytest.param("db-error", id="db-error"), pytest.param("timeout", id="timeout")])
async def test_marking_failure_still_moves_to_the_next_item(
    db_session: AsyncSession,
    sdks: _FakeSdks,
    alerts: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    """표시가 DB 오류로 실패하거나 상한 안에 끝나지 않아도 거절은 사실이라 다음 항목으로 간다. 밖으로 새는 예외가 없고, 경고에는
    오류 클래스 이름만 있다 — DB 오류는 문장 파라미터와 위반한 행(암호문)을 싣는다."""
    first, _ = await _two_items(db_session)
    sdks.replies[FAKE_API_KEY] = _Reply(error=_status_error(402, "billing_error", "Your credit balance is too low"))
    monkeypatch.setattr(credential_pool, "MARK_TIMEOUT_SECONDS", 0.2)
    setup = _route(db_session)
    await setup.pool.plan("opus")
    if failure == "db-error":
        setup.sessions.broken = OperationalError(
            "UPDATE llm_credentials SET state=%(state)s", {"secret_ciphertext": _CANARY}, Exception(_CANARY)
        )
    else:
        setup.sessions.hang = True

    with caplog.at_level(logging.WARNING):
        assert await _generate(setup.router) == "안녕하세요"

    assert (sdks.sent(FAKE_API_KEY), sdks.sent(FAKE_OTHER_API_KEY)) == (1, 1)
    assert _CANARY not in caplog.text
    assert any("자격 소진 표시" in record.getMessage() for record in caplog.records)
    assert await _state(db_session, first) == ("active", None, first.state_version)


async def test_slow_mark_does_not_hold_the_next_item_and_still_completes(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """표시가 커밋 뒤 상한보다 오래 걸려도 다음 항목은 상한만큼만 기다린다. 표시는 그 뒤에도 끝까지 돌아 세대를 올리고 알린다."""
    first, _ = await _two_items(db_session)
    sdks.replies[FAKE_API_KEY] = _Reply(error=_status_error(402, "billing_error", "Your credit balance is too low"))
    monkeypatch.setattr(credential_pool, "MARK_TIMEOUT_SECONDS", 0.2)
    setup = _route(db_session)
    await setup.pool.plan("opus")
    release = asyncio.Event()
    setup.sessions.hold[setup.sessions.opened + 1] = release.wait
    before = await _generation()

    async with asyncio.timeout(1.5):
        assert await _generate(setup.router) == "안녕하세요"
    assert await _generation() == before
    assert alerts == []

    release.set()
    await _settle_credential_tasks()

    assert await _state(db_session, first) == ("exhausted", "credit", first.state_version + 1)
    assert await _generation() == before + 1
    assert [alert.split(" · ")[1] for alert in alerts] == ["첫째 계정"]


async def test_no_candidate_alert_reads_the_generation_after_the_marks_of_its_request(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """둘째 표시가 상한을 넘겨도 후보 없음 알림은 그 요청의 표시가 끝난 뒤의 세대로 표지를 세운다 — 표시가 끝난 뒤 같은 축으로 다시
    불러도 후보 없음을 다시 알리지 않는다."""
    await _two_items(db_session)
    for key in (FAKE_API_KEY, FAKE_OTHER_API_KEY):
        sdks.replies[key] = _Reply(error=_status_error(402, "billing_error", "Your credit balance is too low"))
    monkeypatch.setattr(credential_pool, "MARK_TIMEOUT_SECONDS", 0.2)
    setup = _route(db_session)
    await setup.pool.plan("opus")
    release = asyncio.Event()
    setup.sessions.hold[setup.sessions.opened + 2] = release.wait

    async with asyncio.timeout(1.5):
        with pytest.raises(LLMCredentialPoolEmptyError):
            await _generate(setup.router)
    await asyncio.sleep(0.05)
    release.set()
    await _settle_credential_tasks()

    with pytest.raises(LLMCredentialPoolEmptyError):
        await _generate(setup.router)
    await _settle_credential_tasks()

    assert len([alert for alert in alerts if alert.startswith(_NO_CANDIDATE_ALERT)]) == 1


async def test_mark_finishes_invalidation_and_alert_when_the_caller_is_cancelled_after_commit(
    db_session: AsyncSession, sdks: _FakeSdks, alerts: list[str]
) -> None:
    """표시를 부른 쪽이 커밋이 서버에 닿은 직후 취소돼도(클라이언트 끊김) 표시 태스크는 무효화·알림까지 끝낸다 — 뒤 요청은 0행이라
    아무도 다시 알리지 않는다."""
    first, _ = await _two_items(db_session)
    setup = _route(db_session)
    plan = await setup.pool.plan("opus")
    assert plan is not None
    committed, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        committed.set()
        await release.wait()

    setup.sessions.hold[setup.sessions.opened + 1] = hold
    before = await _generation()
    caller = asyncio.create_task(setup.pool.mark_exhausted(plan.candidates[0], "credit"))
    async with asyncio.timeout(5):
        await committed.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert await _state(db_session, first) == ("exhausted", "credit", first.state_version + 1)
    release.set()
    await _settle_credential_tasks()

    assert await _state(db_session, first) == ("exhausted", "credit", first.state_version + 1)
    assert await _generation() == before + 1
    assert [alert.split(" · ")[1] for alert in alerts] == ["첫째 계정"]


# ── 기록 ──────────────────────────────────────────────────────────────────────────
async def test_usage_log_line_names_the_item_only_for_pool_calls(
    db_session: AsyncSession, sdks: _FakeSdks, caplog: pytest.LogCaptureFixture
) -> None:
    """목록 경로 호출의 사용량 로그 줄 끝에만 처리한 항목 id 가 붙는다(목록을 쓰지 않는 줄은 지금 그대로)."""
    first, _ = await _two_items(db_session)
    setup = _route(db_session)

    with caplog.at_level(logging.WARNING, logger=anthropic_module.__name__):
        await _generate(setup.router)
        await _set_llm_credential_pool(db_session, False)
        await invalidate_pool_snapshot()
        await _generate(setup.router)

    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("anthropic_usage")]
    assert len(lines) == 2
    assert lines[0].endswith(f" credential_id={first.id}")
    assert "credential_id" not in lines[1] and lines[1].endswith("room_id=None")
    assert sdks.sent(_ENV_KEY) == 1


async def test_pool_call_adds_its_cost_to_the_item_spend(db_session: AsyncSession, sdks: _FakeSdks) -> None:
    """목록 경로로 성공한 호출은 처리한 항목의 추정 사용액에 원가를 쌓는다 — Opus 입력 700·캐시 읽기 200·캐시 쓰기 100·출력 70 =
    4740 마이크로달러."""
    await _set_llm_credential_pool(db_session, True)
    credential = await _add_llm_credential(
        db_session, "첫째 계정", credit_micro_usd=50_000_000, credit_since=datetime(2026, 11, 1, tzinfo=UTC)
    )
    await _add_llm_credential_check(db_session, credential)
    setup = _route(db_session)

    await _generate(setup.router)

    assert await read_credential_spend([SpendTarget.of_row(credential)]) == {
        credential.id: CredentialSpend(spent_micro_usd=4740, calls=1, unpriced_calls=0, unpriced_model=None)
    }
