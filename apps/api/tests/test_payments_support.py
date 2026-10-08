"""결제 판정 함수·포트원 게이트웨이의 실패 감싸기·디스코드 알림. 네트워크를 타지 않는다."""

import asyncio
import logging

import httpx
import pytest
from portone_server_sdk._generated.common.unauthorized_error import (
    UnauthorizedError as UnauthorizedErrorBody,
)
from portone_server_sdk._generated.payment.payment_already_cancelled_error import (
    PaymentAlreadyCancelledError as PaymentAlreadyCancelledErrorBody,
)
from portone_server_sdk.errors import PaymentAlreadyCancelledError, UnauthorizedError
from portone_server_sdk.identity_verification import IdentityVerificationClient
from portone_server_sdk.payment import Payment, PaymentClient

from api.core.config import settings
from api.payments import portone
from api.payments.config import identity_configured, identity_gate_active, payments_active
from api.payments.errors import PortOneCancelRejectedError, PortOneUnavailableError
from api.payments.notify import get_payment_notifier, send_payment_notification
from api.payments.portone import SdkPortOneGateway
from factories import _patch_httpx

_IDENTITY_FIELDS = ("portone_store_id", "portone_identity_channel_key", "portone_api_secret", "identity_ci_hmac_key")
_PAYMENT_FIELDS = ("portone_store_id", "portone_payment_channel_key", "portone_api_secret", "portone_webhook_secret")
# 응답 원문에 섞여 오는 개인정보를 흉내 낸 문자열 — 감싼 예외 어디에도 이 조각이 남으면 안 된다.
_PII = "홍길동 010-1234-5678 hong@example.com"


@pytest.fixture(autouse=True)
def _all_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 `.env` 에 실제 포트원 키가 있다 — 값을 환경이 아니라 테스트가 정한다."""
    for field in {*_IDENTITY_FIELDS, *_PAYMENT_FIELDS}:
        monkeypatch.setattr(settings, field, f"test-{field}")
    monkeypatch.setattr(settings, "payments_enabled", True)
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    monkeypatch.setattr(settings, "payment_discord_webhook_url", "")


# ── 판정 함수 ─────────────────────────────────────────────────────────────
def test_everything_configured_opens_payments_identity_and_gate() -> None:
    assert (payments_active(), identity_configured(), identity_gate_active()) == (True, True, True)


@pytest.mark.parametrize("field", _PAYMENT_FIELDS)
def test_payments_close_when_a_payment_setting_is_empty(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setattr(settings, field, "")
    assert payments_active() is False


@pytest.mark.parametrize("field", ["portone_identity_channel_key", "identity_ci_hmac_key"])
def test_payments_close_when_identity_is_not_configured(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    """결제는 늘 본인인증을 거친다. 깨지는 시나리오: 인증 설정이 비었는데 결제가 열려 구매 화면은 보이고 아무도 결제하지
    못한다."""
    monkeypatch.setattr(settings, field, "")
    assert (identity_configured(), payments_active(), identity_gate_active()) == (False, False, False)


def test_switches_close_their_own_feature_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "payments_enabled", False)
    assert (payments_active(), identity_gate_active()) == (False, True)
    monkeypatch.setattr(settings, "payments_enabled", True)
    monkeypatch.setattr(settings, "identity_gate_enabled", False)
    assert (payments_active(), identity_gate_active()) == (True, False)


# ── 게이트웨이: 응답 원문이 우리 예외로 새지 않는다 ──────────────────────────
class _FailingPayments(PaymentClient):
    def __init__(self, error: BaseException | None = None, *, hang: bool = False) -> None:
        super().__init__(secret="test")
        self.error = error
        self.hang = hang

    async def get_payment_async(self, *, payment_id: str) -> Payment:
        if self.hang:
            await asyncio.Event().wait()
        assert self.error is not None
        raise self.error


def _gateway(payments: PaymentClient) -> SdkPortOneGateway:
    return SdkPortOneGateway(payments, IdentityVerificationClient(secret="test"))


def _assert_no_pii_anywhere(error: BaseException) -> None:
    assert _PII not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


async def test_deserialization_failure_is_wrapped_without_the_response_text() -> None:
    """SDK 역직렬화 실패 메시지는 응답 전체를 담는다. 깨지는 시나리오: 원 예외가 메시지나 체인에 남아 Bugsink·로그로
    고객 이름·전화가 나간다."""
    with pytest.raises(PortOneUnavailableError) as caught:
        await _gateway(_FailingPayments(ValueError(f"{{'customer': '{_PII}'}} is not Payment"))).get_payment("p1")

    assert caught.value.reason == "ValueError"
    _assert_no_pii_anywhere(caught.value)


async def test_sdk_error_is_wrapped_without_the_response_text() -> None:
    with pytest.raises(PortOneUnavailableError) as caught:
        await _gateway(_FailingPayments(UnauthorizedError(UnauthorizedErrorBody(message=_PII)))).get_payment("p1")

    assert caught.value.reason == "UnauthorizedError"
    _assert_no_pii_anywhere(caught.value)


async def test_slow_portone_becomes_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 기본 타임아웃(60초) 대신 우리 상한에서 끊고, 그 시간 초과도 재시도할 수 있는 실패로 바뀐다. 깨지는 시나리오:
    내장 `TimeoutError` 가 감싸지지 않고 새어 웹훅이 503 대신 500 이 되고 complete 가 처리되지 않은 예외가 된다."""
    monkeypatch.setattr(portone, "PORTONE_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(PortOneUnavailableError) as caught:
        await _gateway(_FailingPayments(hang=True)).get_payment("p1")

    assert caught.value.reason == "TimeoutError"


class _RejectingPayments(PaymentClient):
    def __init__(self) -> None:
        super().__init__(secret="test")

    async def cancel_payment_async(self, **kwargs: object) -> object:  # type: ignore[override]
        raise PaymentAlreadyCancelledError(PaymentAlreadyCancelledErrorBody(message=_PII))


async def test_definite_cancel_rejection_is_told_apart_from_unknown_outcome() -> None:
    with pytest.raises(PortOneCancelRejectedError) as caught:
        await _gateway(_RejectingPayments()).cancel_payment(
            "p1", amount=1000, current_cancellable_amount=1000, reason="환불"
        )

    assert caught.value.reason == "PaymentAlreadyCancelledError"
    _assert_no_pii_anywhere(caught.value)


# ── 디스코드 알림 ─────────────────────────────────────────────────────────
async def test_notifier_is_skipped_without_a_webhook_url() -> None:
    notifier = get_payment_notifier()
    assert notifier is not send_payment_notification
    await notifier("클로버 베이직 9,900원 결제 완료")


async def test_notifier_posts_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "payment_discord_webhook_url", "https://discord.test/webhook")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    _patch_httpx(monkeypatch, handler, module="api.payments.notify")

    await get_payment_notifier()("결제 완료")

    assert [(str(r.url), r.read()) for r in seen] == [
        ("https://discord.test/webhook", b'{"content":"\xea\xb2\xb0\xec\xa0\x9c \xec\x99\x84\xeb\xa3\x8c"}')
    ]


@pytest.mark.parametrize(
    "response",
    [pytest.param(httpx.Response(500), id="error-status"), pytest.param(None, id="connection-error")],
)
async def test_notification_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, response: httpx.Response | None
) -> None:
    """알림은 결제 흐름 밖의 일이다. 깨지는 시나리오: 디스코드 장애가 백그라운드 태스크 예외로 새어 로그만 어지럽히거나,
    앞으로 동기 경로에서 부르면 결제 응답을 실패로 만든다."""
    monkeypatch.setattr(settings, "payment_discord_webhook_url", "https://discord.test/webhook")

    def handler(request: httpx.Request) -> httpx.Response:
        if response is None:
            raise httpx.ConnectError("down", request=request)
        return response

    _patch_httpx(monkeypatch, handler, module="api.payments.notify")

    with caplog.at_level(logging.WARNING, logger="api.payments.notify"):
        await send_payment_notification("결제 완료")

    assert [record.getMessage().split(": ")[0] for record in caplog.records] == ["payment notification failed"]
