"""포트원 API 호출의 유일한 자리. 라우트는 `Depends(get_portone_gateway)` 로 받고 테스트는 가짜로 갈아끼운다
(네트워크를 타지 않는다).

**응답 원문이 우리 예외에 실리지 않게 한다.** SDK 예외와 역직렬화 실패(`ValueError`·`KeyError`·`TypeError`)의 메시지는
포트원 응답 전체 — 고객 이름·전화·이메일 — 를 담는다. 그래서 실패는 전부 클래스 이름만 든 `PortOneUnavailableError`
(결과 모름)나 `PortOneCancelRejectedError`(취소 거절 확정)로 바꾸고, 원 예외는 체인(`__cause__`·`__context__`)에도
남기지 않는다. 원 예외를 `except` 블록 **밖에서** 다시 던지는 이유가 그것이다 — 블록 안에서 던지면 `from None` 이어도
`__context__` 에 원 예외가 붙고, 그 원문이 로그·트레이스백 출력으로 나갈 길이 남는다. 같은 이유로 그 `except` 안에서
`exc_info` 로그를 남기지 않는다.

SDK 클라이언트는 프로세스에 하나씩만 만든다. 인스턴스마다 httpx 클라이언트를 열고 닫는 경로가 없어서, 요청마다 만들면
커넥션 풀이 샌다. SDK 의 요청 타임아웃(60초)은 바꿀 인자가 없어 호출마다 `anyio.fail_after` 로 더 짧게 끊는다 —
private 속성을 바꿔 끼우면 SDK 판올림에서 조용히 깨진다.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

import anyio
import httpx
from portone_server_sdk.errors import (
    CancelAmountExceedsCancellableAmountError,
    CancellableAmountConsistencyBrokenError,
    PaymentAlreadyCancelledError,
    PaymentNotPaidError,
    PgProviderError,
    PortOneError,
)
from portone_server_sdk.identity_verification import IdentityVerification, IdentityVerificationClient
from portone_server_sdk.payment import Payment, PaymentCancellation, PaymentClient

from api.core.config import settings
from api.payments.errors import PortOneCancelRejectedError, PortOneUnavailableError

# 포트원 호출 하나를 기다리는 상한(초). 결제 확인은 사용자가 화면 앞에서 기다리는 요청이라 SDK 기본 60초는 길다. 호출
# 때마다 이 이름을 모듈 전역으로 읽는다(테스트가 `monkeypatch.setattr` 로 줄인다).
PORTONE_TIMEOUT_SECONDS = 10.0

# 결과를 모르는 실패. `TimeoutError` 는 `anyio.fail_after` 가 내는 내장 예외다 — httpx 의 시간 초과(`httpx.HTTPError`
# 계열)와 다른 예외라 따로 적어야 한다.
_UNAVAILABLE = (PortOneError, httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError)
# 취소가 일어나지 않았음이 확정인 거절. 모두 `PortOneError` 계열이라 위 목록보다 먼저 본다.
_CANCEL_REJECTED = (
    CancellableAmountConsistencyBrokenError,
    CancelAmountExceedsCancellableAmountError,
    PaymentAlreadyCancelledError,
    PaymentNotPaidError,
    PgProviderError,
)

T = TypeVar("T")


class PortOneGateway(Protocol):
    async def get_payment(self, payment_id: str) -> Payment: ...

    async def cancel_payment(
        self, payment_id: str, *, amount: int, current_cancellable_amount: int, reason: str
    ) -> PaymentCancellation: ...

    async def get_identity_verification(self, identity_verification_id: str) -> IdentityVerification: ...


async def _call(
    operation: str,
    call: Callable[[], Awaitable[T]],
    *,
    rejected: tuple[type[Exception], ...] = (),
) -> T:
    """`call` 을 시간 상한 안에서 부르고 실패를 원문 없는 도메인 예외로 바꾼다(모듈 docstring)."""
    rejected_reason: str | None = None
    unavailable_reason: str | None = None
    try:
        with anyio.fail_after(PORTONE_TIMEOUT_SECONDS):
            return await call()
    except rejected as exc:
        rejected_reason = type(exc).__name__
    except _UNAVAILABLE as exc:
        unavailable_reason = type(exc).__name__
    # 여기는 `except` 블록 밖이라 아래 예외에는 원 예외가 `__context__` 로 붙지 않는다.
    if rejected_reason is not None:
        raise PortOneCancelRejectedError(rejected_reason) from None
    raise PortOneUnavailableError(operation, unavailable_reason or "unknown") from None


class SdkPortOneGateway:
    def __init__(self, payments: PaymentClient, identity: IdentityVerificationClient) -> None:
        self._payments = payments
        self._identity = identity

    async def get_payment(self, payment_id: str) -> Payment:
        return await _call("get_payment", lambda: self._payments.get_payment_async(payment_id=payment_id))

    async def cancel_payment(
        self, payment_id: str, *, amount: int, current_cancellable_amount: int, reason: str
    ) -> PaymentCancellation:
        async def cancel() -> PaymentCancellation:
            response = await self._payments.cancel_payment_async(
                payment_id=payment_id,
                amount=amount,
                current_cancellable_amount=current_cancellable_amount,
                reason=reason,
            )
            return response.cancellation

        return await _call("cancel_payment", cancel, rejected=_CANCEL_REJECTED)

    async def get_identity_verification(self, identity_verification_id: str) -> IdentityVerification:
        return await _call(
            "get_identity_verification",
            lambda: self._identity.get_identity_verification_async(
                identity_verification_id=identity_verification_id
            ),
        )


_gateway: SdkPortOneGateway | None = None


def get_portone_gateway() -> PortOneGateway:
    """프로세스에 하나뿐인 게이트웨이를 처음 부를 때 만든다(모듈 docstring). 비밀이 비어 있어도 만들 수 있다 — 호출이
    인증 실패로 `PortOneUnavailableError` 가 될 뿐이고, 결제를 여는 판정은 라우트가 따로 한다."""
    global _gateway
    if _gateway is None:
        _gateway = SdkPortOneGateway(
            PaymentClient(secret=settings.portone_api_secret),
            IdentityVerificationClient(secret=settings.portone_api_secret),
        )
    return _gateway
