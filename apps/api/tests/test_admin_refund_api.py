"""어드민 환불: 견적, 실행(회수가 포트원 호출 앞), 포트원 결과 매핑, 재시도·웹훅 대사.

실제 포트원을 부르지 않는다 — 게이트웨이를 가짜로 갈아끼우고, 가짜는 SDK 의 결제·취소 클래스를 그대로 돌려준다(대사가
`isinstance` 로 상태를 가른다). 처리일은 `refund._utcnow` 를 리터럴 시각으로 고정해, 비율 판정이 처리일이 아니라
신청 접수일로 정해지는지 가른다.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from portone_server_sdk.common import Customer, SelectedChannel
from portone_server_sdk.payment import (
    CancelledPayment,
    FailedPaymentCancellation,
    PaidPayment,
    PartialCancelledPayment,
    Payment as PortOnePayment,
    PaymentAmount,
    PaymentCancellation as PortOneCancellation,
    PaymentOrigin,
    RequestedPaymentCancellation,
    SucceededPaymentCancellation,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot
from api.db.models.moderation import AdminActionLog
from api.db.models.payment import Payment, PaymentCancellation
from api.main import app
from api.payments import refund
from api.payments import service as payments_service
from api.payments.errors import PaymentConsolePartialCancelError, PortOneCancelRejectedError, PortOneUnavailableError
from api.payments.notify import get_payment_notifier
from api.payments.portone import get_portone_gateway
from api.payments.service import sync_payment
from factories import _clover_lots, _create_admin, _login_as, _login_as_admin, _make_payment, _make_user

# 결제 시각은 KST 2026-10-01 12:00, 처리일(지금)은 그 30일 뒤다.
_PAID_AT = datetime(2026, 10, 1, 3, tzinfo=UTC)
_NOW = datetime(2026, 10, 31, 3, tzinfo=UTC)
_DAY_7 = date(2026, 10, 8)
_DAY_8 = date(2026, 10, 9)
_TODAY = date(2026, 10, 31)
# 베이직 상품(`_make_payment` 기본값): 9,900원에 유료 3,300 + 보너스 300 — 유료 1개 = 3원.
_PRICE, _PAID, _BONUS = 9_900, 3_300, 300
_FULL_LOTS = [("purchase_bonus", _BONUS), ("purchase_paid", _PAID)]
_EMPTY_LOTS = [("purchase_bonus", 0), ("purchase_paid", 0)]


# 멈춘 취소 호출·그 호출을 기다리는 요청의 상한(초). 정상 경로는 1초 안에 풀린다.
_HOLD_LIMIT_SECONDS = 10


class _RefundGateway:
    """취소 결과를 차례로 돌려주는 가짜. `hold` 를 걸면 취소 호출이 그 이벤트를 기다린다(포트원 응답 대기 구간)."""

    def __init__(self) -> None:
        self.payments: dict[str, PortOnePayment] = {}
        self.cancel_results: list[PortOneCancellation | Exception] = []
        self.cancel_calls: list[tuple[str, int, int]] = []
        self.hold: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def get_payment(self, payment_id: str) -> PortOnePayment:
        if payment_id not in self.payments:
            raise PortOneUnavailableError("get_payment", "ConnectError")
        return self.payments[payment_id]

    async def cancel_payment(
        self, payment_id: str, *, amount: int, current_cancellable_amount: int, reason: str
    ) -> PortOneCancellation:
        self.cancel_calls.append((payment_id, amount, current_cancellable_amount))
        self.entered.set()
        if self.hold is not None:
            # 시간 상한: 테스트가 풀어 주지 않는 경로(예: 두 번째 전송)에서 영원히 멈추지 않고 실패하게 한다.
            await asyncio.wait_for(self.hold.wait(), timeout=_HOLD_LIMIT_SECONDS)
        result = self.cancel_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def get_identity_verification(self, identity_verification_id: str) -> Any:
        raise AssertionError("환불은 본인인증을 조회하지 않는다")


@pytest.fixture(autouse=True)
def gateway() -> Iterator[_RefundGateway]:
    fake = _RefundGateway()
    app.dependency_overrides[get_portone_gateway] = lambda: fake
    yield fake
    if fake.hold is not None:
        fake.hold.set()
    app.dependency_overrides.pop(get_portone_gateway, None)


@pytest.fixture(autouse=True)
def notifications() -> Iterator[list[str]]:
    sent: list[str] = []

    async def record(message: str) -> None:
        sent.append(message)

    app.dependency_overrides[get_payment_notifier] = lambda: record
    yield sent
    app.dependency_overrides.pop(get_payment_notifier, None)


@pytest.fixture(autouse=True)
def captured(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, BaseException | None]]:
    events: list[tuple[str, BaseException | None]] = []

    def record(exc: BaseException | None = None, *, dependency: str) -> None:
        events.append((dependency, exc))

    monkeypatch.setattr(refund, "capture_dependency_failure", record)
    monkeypatch.setattr(payments_service, "capture_dependency_failure", record)
    return events


@pytest.fixture(autouse=True)
def _processing_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(refund, "_utcnow", lambda: _NOW)


def _later(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 날 안에서 시계를 전송 차지 시간 너머로 옮긴다 — 앞선 전송이 끝났다고 볼 수 있는 재시도."""
    later = _NOW + timedelta(seconds=refund.SEND_CLAIM_SECONDS + 1)
    monkeypatch.setattr(refund, "_utcnow", lambda: later)


# ── 셋업 ─────────────────────────────────────────────────────────────────
async def _paid_order(db: AsyncSession, **overrides: object) -> tuple[User, Payment]:
    """구매 로트만 가진 회원과 지급을 마친 베이직 주문."""
    user = _make_user()
    db.add(user)
    await db.flush()
    fields: dict[str, object] = {"status": "paid", "paid_at": _PAID_AT, "transaction_id": "tx", **overrides}
    order = await _make_payment(db, user_id=user.id, **fields)
    purchases: tuple[tuple[clover.CloverKind, int], ...] = (("purchase_paid", _PAID), ("purchase_bonus", _BONUS))
    for kind, amount in purchases:
        await clover.grant(
            db, user_id=user.id, amount=amount, kind=kind, idempotency_key=f"t:{order.id}:{kind}", payment_id=order.id
        )
    return user, order


async def _admin(db_client: httpx.AsyncClient, db: AsyncSession) -> uuid.UUID:
    admin = await _create_admin(db)
    await _login_as_admin(db_client, admin)
    admin_id = admin["id"]
    assert isinstance(admin_id, uuid.UUID)
    return admin_id


def _cancellation(cls: type[Any], cancellation_id: str, amount: int = _PRICE) -> PortOneCancellation:
    result: PortOneCancellation = cls(
        id=cancellation_id,
        total_amount=amount,
        tax_free_amount=0,
        vat_amount=0,
        reason="클로버 구매 환불",
        requested_at="2026-10-31T03:00:00Z",
    )
    return result


def _remote(
    order: Payment, cancellations: list[PortOneCancellation], *, partial: bool = False, still_paid: bool = False
) -> PortOnePayment:
    """포트원 결제 조회 결과. 취소 내역이 없거나 `still_paid` 면 아직 결제 완료 상태다 — 성공한 취소가 생기기 전의 대기·실패
    취소는 결제 완료 상태의 취소 내역에 보인다."""
    cancelled = sum(c.total_amount for c in cancellations if isinstance(c, SucceededPaymentCancellation))
    fields: dict[str, Any] = {
        "id": order.payment_id,
        "transaction_id": "tx",
        "merchant_id": "merchant-test",
        "store_id": "store-test",
        "channel": SelectedChannel(type="TEST", pg_provider="INICIS_V2", pg_merchant_id="m", key=order.channel_key),
        "version": "V2",
        "requested_at": "2026-10-01T02:59:00Z",
        "updated_at": "2026-10-31T03:00:00Z",
        "status_changed_at": "2026-10-31T03:00:00Z",
        "order_name": order.order_name,
        "amount": PaymentAmount(
            total=order.amount_krw, tax_free=0, discount=0, paid=order.amount_krw, cancelled=cancelled, cancelled_tax_free=0
        ),
        "currency": "KRW",
        "customer": Customer(name="홍길동"),
        "origin": PaymentOrigin(platform_type="PC", ip_address="127.0.0.1"),
    }
    if still_paid or not cancellations:
        return PaidPayment(
            **fields, paid_at="2026-10-01T03:00:00Z", disputes=[], cancellations=cancellations or None
        )
    cls = PartialCancelledPayment if partial else CancelledPayment
    return cls(**fields, cancellations=cancellations, cancelled_at="2026-10-31T03:00:00Z")


async def _quote(
    client: httpx.AsyncClient, order: Payment, received_on: date, *, company_fault: bool = False
) -> httpx.Response:
    return await client.get(
        f"/admin/payments/{order.payment_id}/refund-quote",
        params={"receivedOn": received_on.isoformat(), "companyFault": str(company_fault).lower()},
    )


async def _refund(
    client: httpx.AsyncClient,
    order: Payment,
    *,
    expected: int = _PRICE,
    received_on: date = _DAY_7,
    company_fault: bool = False,
    reason: str = "고객 환불 요청",
) -> httpx.Response:
    return await client.post(
        f"/admin/payments/{order.payment_id}/refund",
        json={
            "reason": reason,
            "expectedRefundKrw": expected,
            "receivedOn": received_on.isoformat(),
            "companyFault": company_fault,
        },
    )


async def _attempts(db: AsyncSession, order: Payment) -> list[tuple[str, str, int, str | None]]:
    rows = await db.execute(
        select(
            PaymentCancellation.source,
            PaymentCancellation.status,
            PaymentCancellation.amount_krw,
            PaymentCancellation.portone_cancellation_id,
        )
        .where(PaymentCancellation.payment_id == order.id)
        .order_by(PaymentCancellation.source, PaymentCancellation.status)
    )
    return [(source, status, amount, cancellation_id) for source, status, amount, cancellation_id in rows.all()]


async def _order(db: AsyncSession, order: Payment) -> tuple[str, int]:
    row = await db.scalar(select(Payment).where(Payment.id == order.id).execution_options(populate_existing=True))
    assert row is not None
    return row.status, row.cancelled_amount_krw


async def _ledger(db: AsyncSession, user: User) -> list[tuple[str, int]]:
    rows = await db.execute(
        select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user.id)
        .order_by(CloverLedger.kind)
    )
    return [(kind, amount) for kind, amount in rows.all()]


async def _audit(db: AsyncSession, user: User) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(AdminActionLog.action_type, AdminActionLog.reason_text).where(AdminActionLog.target_user_id == user.id)
    )
    return [(action, reason) for action, reason in rows.all()]


# ── 견적 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("received_on", "ratio", "refund_krw"),
    [
        pytest.param(date(2026, 10, 1), 100, 9_900, id="payment-day"),
        pytest.param(_DAY_7, 100, 9_900, id="day-7"),
        pytest.param(_DAY_8, 90, 8_910, id="day-8"),
    ],
)
async def test_quote_ratio_follows_the_received_day_not_the_processing_day(
    db_client: httpx.AsyncClient, db_session: AsyncSession, received_on: date, ratio: int, refund_krw: int
) -> None:
    """결제일을 세지 않고 접수일이 7일째 안이면 전액이다. 처리일은 결제 30일 뒤로 고정했다 — 처리일로 판정하면 7일째
    접수도 90% 가 된다(늦게 처리해 제때 신청한 사용자가 손해 본다)."""
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)

    resp = await _quote(db_client, order, received_on)

    assert resp.status_code == 200
    assert resp.json() == {
        "refundKrw": refund_krw,
        "ratioPercent": ratio,
        "paidRemaining": _PAID,
        "bonusUsed": 0,
        "clawbackPaid": _PAID,
        "clawbackBonus": _BONUS,
        "cancellableKrw": _PRICE,
        "paidAt": "2026-10-01T03:00:00Z",
    }


async def test_quote_with_company_fault_is_full_even_long_after(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)

    fault = await _quote(db_client, order, _TODAY, company_fault=True)
    plain = await _quote(db_client, order, _TODAY)

    assert (fault.json()["ratioPercent"], fault.json()["refundKrw"]) == (100, 9_900)
    assert (plain.json()["ratioPercent"], plain.json()["refundKrw"]) == (90, 8_910)


@pytest.mark.parametrize(
    "received_on",
    [pytest.param(date(2026, 9, 30), id="before-payment"), pytest.param(date(2026, 11, 1), id="future")],
)
async def test_quote_rejects_a_received_day_outside_payment_to_today(
    db_client: httpx.AsyncClient, db_session: AsyncSession, received_on: date
) -> None:
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)

    resp = await _quote(db_client, order, received_on)

    assert (resp.status_code, resp.json()["detail"]) == (422, {"code": "REFUND_RECEIVED_ON_INVALID"})


async def test_quote_subtracts_the_bonus_used_from_that_purchase(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """500 을 쓰면 보너스 300 이 먼저, 유료 200 이 그다음 깎인다. 쓴 보너스만큼 유료 환불 수량에서 뺀다:
    (3,100 − 300) × 3원 = 8,400원."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    assert await clover.spend(db_session, user_id=user.id, amount=500, kind="chat_spend") is not None

    body = (await _quote(db_client, order, _DAY_7)).json()

    assert (body["paidRemaining"], body["bonusUsed"], body["refundKrw"]) == (3_100, 300, 8_400)
    assert (body["clawbackPaid"], body["clawbackBonus"]) == (3_100, 0)


async def test_quote_never_goes_below_zero(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """남은 유료(100)가 쓴 보너스(300)보다 적으면 0원이다 — 음수 견적은 없다. 0원은 실행되지 않는다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    assert await clover.spend(db_session, user_id=user.id, amount=3_500, kind="chat_spend") is not None

    quote = await _quote(db_client, order, _DAY_7)
    run = await _refund(db_client, order, expected=0)

    assert (quote.json()["paidRemaining"], quote.json()["refundKrw"]) == (100, 0)
    assert (run.status_code, run.json()["detail"]) == (422, {"code": "REFUND_AMOUNT_ZERO"})
    assert await _attempts(db_session, order) == []
    assert await _clover_lots(db_session, user.id) == [("purchase_bonus", 0), ("purchase_paid", 100)]


async def test_quote_is_capped_by_the_cancellable_amount(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session, status="partially_cancelled", cancelled_amount_krw=9_000)

    body = (await _quote(db_client, order, _DAY_7)).json()

    assert (body["refundKrw"], body["cancellableKrw"]) == (900, 900)


async def test_quote_refuses_a_payment_that_is_not_refundable(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session, status="cancelled", cancelled_amount_krw=_PRICE)

    resp = await _quote(db_client, order, _DAY_7)

    assert (resp.status_code, resp.json()["detail"]) == (422, {"code": "PAYMENT_NOT_REFUNDABLE"})


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", f"/admin/users/{uuid.uuid4()}/payments", id="list"),
        pytest.param("GET", "/admin/payments/clvx/refund-quote?receivedOn=2026-10-08", id="quote"),
        pytest.param("POST", "/admin/payments/clvx/refund", id="refund"),
    ],
)
async def test_payment_routes_require_an_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession, method: str, path: str
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    body = {"reason": "x", "expectedRefundKrw": 0, "receivedOn": "2026-10-08"} if method == "POST" else None

    resp = await db_client.request(method, path, json=body)

    assert resp.status_code == 401


async def test_user_payment_list_flags_a_pending_refund(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [PortOneUnavailableError("cancel_payment", "TimeoutError")]
    assert (await _refund(db_client, order)).status_code == 202

    resp = await db_client.get(f"/admin/users/{user.id}/payments")

    assert resp.status_code == 200
    assert [(i["paymentId"], i["status"], i["refundPending"]) for i in resp.json()["items"]] == [
        (order.payment_id, "paid", True)
    ]


# ── 실행 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("received_on", "company_fault", "ratio", "tag"),
    [
        pytest.param(_DAY_7, False, 100, "[접수 2026-10-08] ", id="within-7-days"),
        pytest.param(_TODAY, True, 100, "[접수 2026-10-31 · 회사 귀책] ", id="company-fault"),
    ],
)
async def test_refund_succeeds_and_records_the_received_day_and_fault(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    gateway: _RefundGateway,
    notifications: list[str],
    received_on: date,
    company_fault: bool,
    ratio: int,
    tag: str,
) -> None:
    admin_id = await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-1")]

    resp = await _refund(db_client, order, received_on=received_on, company_fault=company_fault)

    assert resp.status_code == 200
    assert resp.json() == {"status": "succeeded", "amountKrw": _PRICE, "clawbackPaid": _PAID, "clawbackBonus": _BONUS}
    assert gateway.cancel_calls == [(order.payment_id, _PRICE, _PRICE)]
    row = await db_session.scalar(select(PaymentCancellation).where(PaymentCancellation.payment_id == order.id))
    assert row is not None
    assert (
        row.source,
        row.status,
        row.portone_cancellation_id,
        row.ratio_percent,
        row.request_received_on,
        row.company_fault,
        row.admin_id,
        row.completed_at is not None,
    ) == ("admin", "succeeded", "c-1", ratio, received_on, company_fault, admin_id, True)
    assert await _order(db_session, order) == ("cancelled", _PRICE)
    assert await _clover_lots(db_session, user.id) == _EMPTY_LOTS
    assert await _ledger(db_session, user) == [
        ("purchase_bonus", _BONUS),
        ("purchase_paid", _PAID),
        ("purchase_revoke", -(_PAID + _BONUS)),
    ]
    assert await _audit(db_session, user) == [("user-payment-refund", tag + "고객 환불 요청")]
    # 디스코드에는 상품·금액·상태만 — 주문 id 는 조각도 없다.
    assert notifications == ["클로버 베이직 9,900원 환불 완료"]


async def test_refund_takes_the_clovers_back_before_portone_answers(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """포트원 응답을 기다리는 동안 그 구매의 유료·보너스는 이미 회수돼 있고 그 사이 차감은 실패한다. 깨지는 시나리오:
    회수를 응답 뒤로 미루면 그 구간에 사용자가 환불 대상 유료를 다 쓰고도 돈을 받는다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.hold = asyncio.Event()
    gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-1")]

    request = asyncio.ensure_future(_refund(db_client, order))
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=5)
        lots_during_call = await _clover_lots(db_session, user.id)
        spend_during_call = await clover.spend(db_session, user_id=user.id, amount=10, kind="chat_spend")
    finally:
        gateway.hold.set()
    resp = await asyncio.wait_for(request, timeout=_HOLD_LIMIT_SECONDS)

    assert lots_during_call == _EMPTY_LOTS
    assert spend_during_call is None
    assert resp.status_code == 200


async def test_requested_cancellation_waits_and_the_webhook_finishes_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """PG 가 비동기로 처리 중이면 성공이 아니다 — 202 로 두고 클로버는 회수한 채, 뒤이은 취소 웹훅이 id 로 끝낸다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [_cancellation(RequestedPaymentCancellation, "c-r")]

    resp = await _refund(db_client, order)

    assert (resp.status_code, resp.json()["status"]) == (202, "requested")
    assert await _attempts(db_session, order) == [("admin", "requested", _PRICE, "c-r")]
    assert await _order(db_session, order) == ("paid", 0)
    assert await _clover_lots(db_session, user.id) == _EMPTY_LOTS

    gateway.payments[order.payment_id] = _remote(order, [_cancellation(SucceededPaymentCancellation, "c-r")])
    outcome = await sync_payment(db_session, gateway, order.payment_id)

    assert (outcome.result, outcome.notification) == ("cancelled", "클로버 베이직 9,900원 환불 완료")
    assert await _attempts(db_session, order) == [("admin", "succeeded", _PRICE, "c-r")]
    assert await _order(db_session, order) == ("cancelled", _PRICE)


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(_cancellation(FailedPaymentCancellation, "c-f"), id="failed-cancellation"),
        pytest.param(PortOneCancelRejectedError("PgProviderError"), id="rejected"),
    ],
)
async def test_rejected_refund_restores_the_clovers(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    gateway: _RefundGateway,
    notifications: list[str],
    result: PortOneCancellation | Exception,
) -> None:
    """포트원이 취소하지 않았음이 확정이면 시도를 실패로 닫고 회수한 클로버를 원래 구매 로트로 돌려준다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [result]

    resp = await _refund(db_client, order)

    assert (resp.status_code, resp.json()["detail"]) == (422, {"code": "REFUND_REJECTED"})
    assert [status for _, status, _, _ in await _attempts(db_session, order)] == ["failed"]
    assert await _order(db_session, order) == ("paid", 0)
    assert await _clover_lots(db_session, user.id) == _FULL_LOTS
    assert await _ledger(db_session, user) == [
        ("purchase_bonus", _BONUS),
        ("purchase_paid", _PAID),
        ("purchase_restore", _PAID + _BONUS),
        ("purchase_revoke", -(_PAID + _BONUS)),
    ]
    assert notifications == []


async def test_already_cancelled_rejection_is_checked_against_portone_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """"이미 취소됨" 거절은 우리 취소가 먼저 처리된 경우일 수 있다 — 포트원에 그 금액의 성공 취소가 보이면 성공이다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [PortOneCancelRejectedError("PaymentAlreadyCancelledError")]
    gateway.payments[order.payment_id] = _remote(order, [_cancellation(SucceededPaymentCancellation, "c-x")])

    resp = await _refund(db_client, order)

    assert (resp.status_code, resp.json()["status"]) == (200, "succeeded")
    assert await _attempts(db_session, order) == [("admin", "succeeded", _PRICE, "c-x")]
    assert await _clover_lots(db_session, user.id) == _EMPTY_LOTS


async def test_quote_change_is_refused_without_touching_anything(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)

    resp = await _refund(db_client, order, expected=9_000)

    assert (resp.status_code, resp.json()["detail"]) == (409, {"code": "REFUND_QUOTE_CHANGED"})
    assert await _attempts(db_session, order) == []
    assert await _clover_lots(db_session, user.id) == _FULL_LOTS
    assert await _audit(db_session, user) == []
    assert gateway.cancel_calls == []


@pytest.mark.parametrize(
    ("portone_processed", "calls"),
    [pytest.param(True, 1, id="portone-processed"), pytest.param(False, 2, id="never-reached-portone")],
)
async def test_timeout_then_another_admin_retries_the_same_attempt(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    gateway: _RefundGateway,
    monkeypatch: pytest.MonkeyPatch,
    portone_processed: bool,
    calls: int,
) -> None:
    """시간 초과는 결과 모름이라 202 로 회수한 채 둔다. 다른 어드민이 (전송 차지 시간이 지난 뒤) 다시 눌러도 새 시도를
    만들지 않고 그 시도를 잇는다 — 포트원이 처리했으면 재조회로 끝내고(취소 호출 1회), 안 닿았으면 같은 가드 금액으로
    다시 보낸다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [PortOneUnavailableError("cancel_payment", "TimeoutError")]

    first = await _refund(db_client, order)

    assert (first.status_code, first.json()["status"]) == (202, "requested")
    assert await _attempts(db_session, order) == [("admin", "requested", _PRICE, None)]

    await _admin(db_client, db_session)
    _later(monkeypatch)
    if portone_processed:
        gateway.payments[order.payment_id] = _remote(order, [_cancellation(SucceededPaymentCancellation, "c-1")])
    else:
        gateway.payments[order.payment_id] = _remote(order, [])
        gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-1")]

    second = await _refund(db_client, order, expected=123, received_on=_DAY_8)

    assert (second.status_code, second.json()["status"]) == (200, "succeeded")
    assert gateway.cancel_calls == [(order.payment_id, _PRICE, _PRICE)] * calls
    assert await _attempts(db_session, order) == [("admin", "succeeded", _PRICE, "c-1")]
    assert await _order(db_session, order) == ("cancelled", _PRICE)
    assert len(await _audit(db_session, user)) == 1


async def test_webhook_arriving_before_our_portone_answer_is_counted_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway, notifications: list[str]
) -> None:
    """포트원이 취소 웹훅을 우리 응답보다 먼저 보내도 취소 하나는 한 번만 반영된다(취소액 = 결제액, 알림 1회)."""
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)
    gateway.hold = asyncio.Event()
    gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-1")]

    request = asyncio.ensure_future(_refund(db_client, order))
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=5)
        gateway.payments[order.payment_id] = _remote(order, [_cancellation(SucceededPaymentCancellation, "c-1")])
        webhook = await sync_payment(db_session, gateway, order.payment_id)
    finally:
        gateway.hold.set()
    resp = await asyncio.wait_for(request, timeout=_HOLD_LIMIT_SECONDS)

    assert webhook.notification == "클로버 베이직 9,900원 환불 완료"
    assert (resp.status_code, resp.json()["status"]) == (200, "succeeded")
    assert notifications == []
    assert await _attempts(db_session, order) == [("admin", "succeeded", _PRICE, "c-1")]
    assert await _order(db_session, order) == ("cancelled", _PRICE)


# ── 콘솔 취소(웹훅) ──────────────────────────────────────────────────────
async def _clawbacks(db: AsyncSession, order: Payment) -> dict[str, tuple[str, int, int]]:
    """취소 행의 출처별 (상태, 회수 유료, 회수 보너스)."""
    rows = await db.execute(
        select(
            PaymentCancellation.source,
            PaymentCancellation.status,
            PaymentCancellation.clawback_paid,
            PaymentCancellation.clawback_bonus,
        )
        .where(PaymentCancellation.payment_id == order.id)
        .execution_options(populate_existing=True)
    )
    return {source: (status, paid, bonus) for source, status, paid, bonus in rows.all()}


def _partial_console_captures(captured: list[tuple[str, BaseException | None]]) -> int:
    return sum(isinstance(exc, PaymentConsolePartialCancelError) for _, exc in captured)


async def test_console_partial_cancel_claws_back_only_what_was_refunded_once(
    db_session: AsyncSession, gateway: _RefundGateway, captured: list[tuple[str, BaseException | None]]
) -> None:
    """콘솔 부분 취소는 취소 금액 ÷ 구매 단가(올림)만큼만 유료에서 회수한다 — 3,001원 ÷ 3원 = 1,000.3 → 1,001. 나머지
    클로버는 돈을 돌려받지 않았으니 사용자에게 남는다. 운영 규칙(부분 환불은 어드민 버튼) 위반이라 Bugsink 에 남긴다.
    일부 취소라 같은 웹훅이 다시 오면 대사를 한 번 더 거치는데, 취소 id 로 맞아 행·회수·취소액·알림·캡처가 늘지 않는다."""
    user, order = await _paid_order(db_session)
    gateway.payments[order.payment_id] = _remote(
        order, [_cancellation(SucceededPaymentCancellation, "console-1", 3_001)], partial=True
    )

    first = await sync_payment(db_session, gateway, order.payment_id)
    second = await sync_payment(db_session, gateway, order.payment_id)

    assert (first.result, first.notification) == ("reconciled", "클로버 베이직 3,001원 환불 완료")
    assert (second.result, second.notification) == ("reconciled", None)
    assert await _attempts(db_session, order) == [("console", "succeeded", 3_001, "console-1")]
    assert await _clawbacks(db_session, order) == {"console": ("succeeded", 1_001, 0)}
    assert await _order(db_session, order) == ("partially_cancelled", 3_001)
    assert await _clover_lots(db_session, user.id) == [("purchase_bonus", _BONUS), ("purchase_paid", _PAID - 1_001)]
    assert await _ledger(db_session, user) == [
        ("purchase_bonus", _BONUS),
        ("purchase_paid", _PAID),
        ("purchase_revoke", -1_001),
    ]
    assert _partial_console_captures(captured) == 1


async def test_console_partial_cancel_takes_the_bonus_when_paid_runs_short(
    db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """유료가 모자라면 같은 구매의 보너스에서 마저 회수한다: 1,800원 → 600개, 남은 유료 500 + 보너스 100."""
    user, order = await _paid_order(db_session)
    await db_session.execute(
        update(CloverLot)
        .where(CloverLot.payment_id == order.id, CloverLot.kind == "purchase_paid")
        .values(remaining=500)
    )
    await db_session.execute(
        update(User).where(User.id == user.id).values(clover_balance=User.clover_balance - (_PAID - 500))
    )
    gateway.payments[order.payment_id] = _remote(
        order, [_cancellation(SucceededPaymentCancellation, "console-1", 1_800)], partial=True
    )

    await sync_payment(db_session, gateway, order.payment_id)

    assert await _clawbacks(db_session, order) == {"console": ("succeeded", 500, 100)}
    assert await _clover_lots(db_session, user.id) == [("purchase_bonus", 200), ("purchase_paid", 0)]


async def test_console_full_cancel_claws_back_everything_left(
    db_session: AsyncSession, gateway: _RefundGateway, captured: list[tuple[str, BaseException | None]]
) -> None:
    """앞선 부분 취소 뒤 나머지를 콘솔에서 모두 취소하면 전액 취소다 — 금액 비례가 아니라 남은 전부를 회수한다."""
    user, order = await _paid_order(db_session)
    first = _cancellation(SucceededPaymentCancellation, "console-1", 3_000)
    gateway.payments[order.payment_id] = _remote(order, [first], partial=True)
    await sync_payment(db_session, gateway, order.payment_id)
    gateway.payments[order.payment_id] = _remote(
        order, [first, _cancellation(SucceededPaymentCancellation, "console-2", 6_900)]
    )

    await sync_payment(db_session, gateway, order.payment_id)

    assert await _order(db_session, order) == ("cancelled", _PRICE)
    assert await _clover_lots(db_session, user.id) == _EMPTY_LOTS
    assert _partial_console_captures(captured) == 1


# ── 리뷰 재현: 결제 완료 상태의 대기·실패 취소, 동시 재전송, 금액 맞춤, 겹친 콘솔 취소 ─────────────
async def test_async_cancel_failure_on_a_still_paid_payment_ends_the_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """PG 가 비동기 취소를 나중에 실패시키면 포트원 결제는 `PAID` 그대로이고 실패 취소는 그 취소 내역에만 보인다. 재시도가
    그것을 읽어 시도를 실패로 닫고 클로버를 돌려준다. 깨지는 시나리오: 영원히 202 — 돈도 클로버도 없다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [_cancellation(RequestedPaymentCancellation, "c-r")]
    assert (await _refund(db_client, order)).status_code == 202
    gateway.payments[order.payment_id] = _remote(
        order, [_cancellation(FailedPaymentCancellation, "c-r")], still_paid=True
    )

    retry = await _refund(db_client, order)

    assert (retry.status_code, retry.json()["detail"]) == (422, {"code": "REFUND_REJECTED"})
    assert await _attempts(db_session, order) == [("admin", "failed", _PRICE, "c-r")]
    assert await _clover_lots(db_session, user.id) == _FULL_LOTS
    assert len(gateway.cancel_calls) == 1


async def test_pending_cancel_on_a_still_paid_payment_is_not_resent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """첫 전송이 시간 초과였지만 포트원은 받아서 PG 가 처리 중이다(결제는 `PAID`, 취소 내역에 대기 취소). 재시도는 그 대기
    취소를 우리 시도에 붙이고 다시 보내지 않는다. 깨지는 시나리오: 같은 환불이 두 번 PG 로 간다."""
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)
    gateway.cancel_results = [PortOneUnavailableError("cancel_payment", "TimeoutError")]
    assert (await _refund(db_client, order)).status_code == 202
    gateway.payments[order.payment_id] = _remote(
        order, [_cancellation(RequestedPaymentCancellation, "c-1")], still_paid=True
    )
    _later(monkeypatch)

    retry = await _refund(db_client, order)

    assert (retry.status_code, retry.json()["status"]) == (202, "requested")
    assert len(gateway.cancel_calls) == 1
    assert await _attempts(db_session, order) == [("admin", "requested", _PRICE, "c-1")]


async def test_second_click_while_the_first_send_waits_does_not_send_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """첫 요청이 포트원 응답을 기다리는 동안 같은 시도를 다시 누르면(더블클릭·다른 어드민) 지금 상태(202)만 돌려준다.
    포트원 조회에는 아직 아무것도 없어 "닿지 않음"처럼 보이지만, 결제 행 잠금 아래 적힌 전송 시각이 재전송을 막는다."""
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)
    gateway.hold = asyncio.Event()
    gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-1")]
    gateway.payments[order.payment_id] = _remote(order, [])

    first = asyncio.ensure_future(_refund(db_client, order))
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=5)
        # 둘째 요청이 다시 보내면 그 전송도 멈춘 취소에 걸린다 — 상한을 둬 멈추지 않고 실패하게 한다.
        second = await asyncio.wait_for(_refund(db_client, order), timeout=_HOLD_LIMIT_SECONDS / 2)
    finally:
        gateway.hold.set()
    first_resp = await asyncio.wait_for(first, timeout=_HOLD_LIMIT_SECONDS)

    assert (second.status_code, second.json()["status"]) == (202, "requested")
    assert (first_resp.status_code, first_resp.json()["status"]) == (200, "succeeded")
    assert len(gateway.cancel_calls) == 1


async def test_an_old_failed_cancellation_does_not_close_a_new_attempt(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """앞선 시도가 PG 에서 거절돼 포트원 내역에 같은 금액의 실패 취소가 남아 있다. 새 시도의 재시도가 그 실패를 금액으로
    자기 것으로 보면 진행 중인 새 취소를 두고 클로버를 돌려준다. 실패는 id 로만 맞춰, 새 시도는 다시 보내져 성공한다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.cancel_results = [PortOneCancelRejectedError("PgProviderError")]
    assert (await _refund(db_client, order)).status_code == 422
    gateway.cancel_results = [PortOneUnavailableError("cancel_payment", "TimeoutError")]
    assert (await _refund(db_client, order)).status_code == 202
    gateway.payments[order.payment_id] = _remote(
        order, [_cancellation(FailedPaymentCancellation, "f-old")], still_paid=True
    )
    gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-new")]
    _later(monkeypatch)

    retry = await _refund(db_client, order)

    assert (retry.status_code, retry.json()["status"]) == (200, "succeeded")
    assert await _attempts(db_session, order) == [
        ("admin", "failed", _PRICE, None),
        ("admin", "succeeded", _PRICE, "c-new"),
    ]
    assert await _clover_lots(db_session, user.id) == _EMPTY_LOTS


async def test_direct_answer_binds_to_its_own_attempt_even_with_another_amount(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """우리 취소 요청의 응답은 어느 시도의 것인지 이미 안다 — 금액이 요청과 달라도 그 시도를 닫는다. 깨지는 시나리오:
    응답이 콘솔 취소로 기록되고 시도는 `requested` 로 남아 재시도가 또 보낸다."""
    await _admin(db_client, db_session)
    _, order = await _paid_order(db_session)
    gateway.cancel_results = [_cancellation(SucceededPaymentCancellation, "c-1", 9_000)]

    resp = await _refund(db_client, order)

    assert (resp.status_code, resp.json()["status"]) == (200, "succeeded")
    assert await _attempts(db_session, order) == [("admin", "succeeded", _PRICE, "c-1")]


async def test_console_cancel_during_an_attempt_takes_its_clawback(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _RefundGateway
) -> None:
    """어드민 시도가 클로버를 회수해 쥔 채 응답을 기다리는 동안 콘솔 부분 취소 3,000원이 대사되고, 그 시도는 낡은 가드로
    거절된다. 콘솔 취소가 시도의 회수분에서 1,000 을 옮겨 갔으므로 거절의 복원은 나머지만 돌려준다. 깨지는 시나리오:
    3,000원을 돌려받고 클로버도 전부 되찾는다."""
    await _admin(db_client, db_session)
    user, order = await _paid_order(db_session)
    gateway.hold = asyncio.Event()
    gateway.cancel_results = [PortOneCancelRejectedError("CancellableAmountConsistencyBrokenError")]

    request = asyncio.ensure_future(_refund(db_client, order))
    try:
        await asyncio.wait_for(gateway.entered.wait(), timeout=5)
        gateway.payments[order.payment_id] = _remote(
            order, [_cancellation(SucceededPaymentCancellation, "console-1", 3_000)], partial=True
        )
        await sync_payment(db_session, gateway, order.payment_id)
    finally:
        gateway.hold.set()
    resp = await asyncio.wait_for(request, timeout=_HOLD_LIMIT_SECONDS)

    assert resp.status_code == 422
    assert await _clawbacks(db_session, order) == {
        "admin": ("failed", _PAID - 1_000, _BONUS),
        "console": ("succeeded", 1_000, 0),
    }
    assert await _order(db_session, order) == ("partially_cancelled", 3_000)
    assert await _clover_lots(db_session, user.id) == [("purchase_bonus", _BONUS), ("purchase_paid", _PAID - 1_000)]
