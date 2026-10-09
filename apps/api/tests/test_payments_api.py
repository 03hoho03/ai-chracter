"""클로버 구매: 주문 생성, 결제 완료 동기화, 포트원 웹훅.

실제 포트원을 부르지 않는다 — 게이트웨이를 가짜로 갈아끼우고, 가짜는 SDK 의 결제 클래스를 그대로 돌려준다(동기화가
`isinstance` 로 상태를 가르므로). 포트원 키는 로컬 `.env` 의 실제 값이 아니라 테스트가 정한다. 웹훅 서명은 Standard
Webhooks 규격대로 테스트가 직접 만든다.
"""

import asyncio
import base64
import hmac
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import pytest_asyncio
from portone_server_sdk.common import Customer, SelectedChannel
from portone_server_sdk.payment import (
    CancelledPayment,
    FailedPayment,
    PaidPayment,
    PartialCancelledPayment,
    Payment as PortOnePayment,
    PaymentAmount,
    PaymentCancellation,
    PaymentFailure,
    PaymentOrigin,
    ReadyPayment,
    SucceededPaymentCancellation,
)
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.auth.withdrawal import erase_account
from api.core.clover import purchase_lot_expiry
from api.core.config import settings
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot
from api.db.models.payment import Payment, PaymentCancellation as CancellationRow
from api.legal.dependencies import _latest_published_legal_version
from api.main import app
from api.payments import router as payments_router
from api.payments import service as payments_service
from api.payments.errors import (
    PaymentMismatchError,
    PaymentOwnerWithdrawnError,
    PaymentWebhookConfigError,
    PortOneUnavailableError,
)
from api.payments.methods import PAY_METHODS
from api.payments.notify import get_payment_notifier
from api.payments.portone import get_portone_gateway
from api.payments.service import payment_paid_message, sync_payment
from factories import _assert_blocked, _login_as, _make_payment, _make_published, _make_user

_STORE = "store-test-0001"
_CHANNEL = "channel-key-test-inicis"
_WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"portone-webhook-secret-for-tests").decode()
_PAID_AT = "2026-10-08T03:00:00Z"
KST = timezone(timedelta(hours=9))


# ── 셋업 ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _portone_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """로컬 `.env` 에 실제 포트원 키가 있다 — 키 유무로 갈리는 분기를 환경이 아니라 테스트가 정한다."""
    monkeypatch.setattr(settings, "portone_store_id", _STORE)
    monkeypatch.setattr(settings, "portone_payment_channel_key", _CHANNEL)
    monkeypatch.setattr(settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(settings, "portone_webhook_secret", _WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(settings, "payments_enabled", True)


class _FakeGateway:
    def __init__(self) -> None:
        self.payments: dict[str, PortOnePayment] = {}
        self.calls: list[str] = []
        self.unavailable = False

    async def get_payment(self, payment_id: str) -> PortOnePayment:
        self.calls.append(payment_id)
        if self.unavailable:
            raise PortOneUnavailableError("get_payment", "ConnectError")
        return self.payments[payment_id]

    async def cancel_payment(
        self, payment_id: str, *, amount: int, current_cancellable_amount: int, reason: str
    ) -> PaymentCancellation:
        raise AssertionError("결제 확인은 취소를 부르지 않는다")

    async def get_identity_verification(self, identity_verification_id: str) -> Any:
        raise AssertionError("결제 확인은 본인인증을 조회하지 않는다")


@pytest.fixture(autouse=True)
def gateway() -> Iterator[_FakeGateway]:
    fake = _FakeGateway()
    app.dependency_overrides[get_portone_gateway] = lambda: fake
    yield fake
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

    monkeypatch.setattr(payments_service, "capture_dependency_failure", record)
    monkeypatch.setattr(payments_router, "capture_dependency_failure", record)
    return events


def _common(order: Payment) -> dict[str, Any]:
    return {
        "id": order.payment_id,
        "transaction_id": "tx-test",
        "merchant_id": "merchant-test",
        "store_id": _STORE,
        "version": "V2",
        "requested_at": "2026-10-08T02:59:00Z",
        "updated_at": _PAID_AT,
        "status_changed_at": _PAID_AT,
        "order_name": order.order_name,
        "currency": "KRW",
        "customer": Customer(name="홍길동"),
        "origin": PaymentOrigin(platform_type="PC", ip_address="127.0.0.1"),
    }


def _amount(total: int, *, cancelled: int = 0) -> PaymentAmount:
    return PaymentAmount(total=total, tax_free=0, discount=0, paid=total, cancelled=cancelled, cancelled_tax_free=0)


def _channel(key: str | None) -> SelectedChannel:
    return SelectedChannel(type="TEST", pg_provider="INICIS_V2", pg_merchant_id="inicis-test", key=key)


def _paid(order: Payment, **overrides: Any) -> PaidPayment:
    fields: dict[str, Any] = {
        **_common(order),
        "channel": _channel(_CHANNEL),
        "amount": _amount(order.amount_krw),
        "paid_at": _PAID_AT,
        "disputes": [],
    }
    fields.update(overrides)
    return PaidPayment(**fields)


async def _user(db: AsyncSession, client: httpx.AsyncClient | None = None, **overrides: object) -> User:
    user = _make_user(**overrides)
    db.add(user)
    await db.flush()
    if client is not None:
        await _login_as(client, user.id)
    return user


async def _buyer(db: AsyncSession, client: httpx.AsyncClient, **overrides: object) -> User:
    """주문을 만들 수 있는 회원: 본인인증을 마쳤고 만 19세 이상이다(기본 생년월일 2000-01-01)."""
    return await _user(
        db, client, identity_ci_hmac=f"ci-{uuid.uuid4().hex}", identity_verified_at=datetime.now(UTC), **overrides
    )


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int, str | None]]:
    rows = await db.execute(
        select(CloverLedger.kind, CloverLedger.amount, CloverLedger.idempotency_key)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.kind)
    )
    return [(kind, amount, key) for kind, amount, key in rows.all()]


async def _lots(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int, uuid.UUID | None, datetime | None]]:
    rows = await db.execute(
        select(CloverLot.kind, CloverLot.remaining, CloverLot.payment_id, CloverLot.expires_at)
        .where(CloverLot.user_id == user_id)
        .order_by(CloverLot.kind)
    )
    return [(kind, remaining, payment_id, expires_at) for kind, remaining, payment_id, expires_at in rows.all()]


async def _order(db: AsyncSession, order_id: uuid.UUID) -> Payment:
    row = await db.scalar(select(Payment).where(Payment.id == order_id).execution_options(populate_existing=True))
    assert row is not None
    return row


# ── 구매 로트 만료 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("paid_at", "expected"),
    [
        pytest.param(datetime(2026, 10, 8, 3, tzinfo=UTC), datetime(2031, 10, 9, tzinfo=KST), id="same-day"),
        # UTC 로는 10월 7일이지만 KST 로는 10월 8일이다.
        pytest.param(datetime(2026, 10, 7, 15, 30, tzinfo=UTC), datetime(2031, 10, 9, tzinfo=KST), id="kst-day"),
        pytest.param(datetime(2028, 2, 29, 12, tzinfo=KST), datetime(2033, 3, 2, tzinfo=KST), id="leap-day"),
    ],
)
def test_purchase_lot_expiry_is_five_years_from_the_kst_purchase_day(paid_at: datetime, expected: datetime) -> None:
    """환불정책이 "구매일로부터 5년"이라 고지한다. 자정 정규화에 하루를 더해 누구도 5년보다 적게 갖지 않는다."""
    assert purchase_lot_expiry(paid_at) == expected


# ── 주문 생성 ─────────────────────────────────────────────────────────────
async def test_create_payment_fixes_the_amount_on_the_server(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """금액·수량·채널키·동의 시점 문서 버전을 서버가 정해 주문에 복사한다. 깨지는 시나리오: 브라우저가 보낸 값을 믿거나
    상품 정의가 바뀐 뒤 대조 기준이 흔들린다."""
    await _make_published(db_session, kind="refund-policy", version="2026-10-01")
    user = await _buyer(db_session, db_client)

    resp = await db_client.post("/payments", json={"productKey": "plus_v2", "agreed": True})

    assert resp.status_code == 201
    body = resp.json()
    order = await db_session.scalar(select(Payment).where(Payment.payment_id == body["paymentId"]))
    assert order is not None
    assert body == {
        "paymentId": order.payment_id,
        "storeId": _STORE,
        "channelKey": _CHANNEL,
        "orderName": "클로버 플러스",
        "totalAmount": 30_000,
        "currency": "KRW",
    }
    assert order.payment_id.startswith("clv") and len(order.payment_id) == 35
    assert (
        order.user_id,
        order.product_key,
        order.amount_krw,
        order.paid_amount,
        order.bonus_amount,
        order.channel_key,
        order.status,
        order.terms_version,
        order.refund_policy_version,
    ) == (
        user.id,
        "plus_v2",
        30_000,
        10_000,
        1_500,
        _CHANNEL,
        "pending",
        await _latest_published_legal_version(db_session, "terms"),
        "2026-10-01",
    )


async def test_create_payment_rejects_a_retired_product_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """예전 상품표의 키로는 주문이 생기지 않는다. 깨지는 시나리오: 배포 전에 열어 둔 화면이 옛 상품을 눌렀는데 그 키가
    아직 받아들여져 옛 가격으로 주문이 생기거나, 같은 키가 새 가격의 상품을 가리킨다."""
    await _make_published(db_session, kind="refund-policy", version="2026-10-01")
    user = await _buyer(db_session, db_client)

    resp = await db_client.post("/payments", json={"productKey": "basic", "agreed": True})

    assert resp.status_code == 422
    assert [error["loc"] for error in resp.json()["detail"]] == [["body", "productKey"]]
    assert await db_session.scalar(select(Payment).where(Payment.user_id == user.id)) is None


async def test_create_payment_requires_agreement(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _make_published(db_session, kind="refund-policy", version="2026-10-01")
    await _user(db_session, db_client)

    resp = await db_client.post("/payments", json={"productKey": "basic_v2", "agreed": False})

    assert resp.status_code == 422


@pytest.mark.parametrize(
    "setting",
    [pytest.param("payments_enabled", id="switch-off"), pytest.param("identity_ci_hmac_key", id="identity-unset")],
)
async def test_create_payment_is_closed_when_payments_are_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    await _make_published(db_session, kind="refund-policy", version="2026-10-01")
    user = await _user(db_session, db_client)
    monkeypatch.setattr(settings, setting, False if setting == "payments_enabled" else "")

    resp = await db_client.post("/payments", json={"productKey": "basic_v2", "agreed": True})

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "PAYMENTS_UNAVAILABLE"})
    assert await db_session.scalar(select(Payment).where(Payment.user_id == user.id)) is None


async def test_create_payment_needs_a_published_refund_policy(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """동의를 기록할 환불정책 게시본이 없으면 유료 조건 동의가 성립하지 않는다."""
    assert await _latest_published_legal_version(db_session, "refund-policy") is None
    await _buyer(db_session, db_client)

    resp = await db_client.post("/payments", json={"productKey": "basic_v2", "agreed": True})

    assert (resp.status_code, resp.json()["detail"]) == (503, {"code": "PAYMENTS_UNAVAILABLE"})


@pytest.mark.parametrize("gate", [pytest.param(False, id="gate-off"), pytest.param(True, id="gate-on")])
@pytest.mark.parametrize("exempt", [pytest.param(False, id="member"), pytest.param(True, id="exempt")])
async def test_create_payment_requires_identity_verification(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    gate: bool,
    exempt: bool,
) -> None:
    """결제의 본인인증은 만 19세를 확인하는 유일한 수단이라 미인증 회원 게이트 스위치와도, 레이트리밋 면제와도 무관하게
    걸린다. 주문 행은 만들지 않는다."""
    await _make_published(db_session, kind="refund-policy", version="2026-10-01")
    monkeypatch.setattr(settings, "identity_gate_enabled", gate)
    user = await _user(db_session, db_client, rate_limit_exempt=exempt)

    resp = await db_client.post("/payments", json={"productKey": "basic_v2", "agreed": True})

    assert (resp.status_code, resp.json()["detail"]) == (403, {"code": "IDENTITY_VERIFICATION_REQUIRED"})
    assert await db_session.scalar(select(Payment).where(Payment.user_id == user.id)) is None


@pytest.mark.parametrize(
    ("age", "status_code"),
    [pytest.param(18, 403, id="eighteen-refused"), pytest.param(19, 201, id="nineteen-allowed")],
)
async def test_create_payment_requires_the_verified_age_of_nineteen(
    db_client: httpx.AsyncClient, db_session: AsyncSession, age: int, status_code: int
) -> None:
    """미성년자의 결제는 막는다. 경계(만 19세)는 통과한다 — 1월 1일생이라 올해 생일이 이미 지났다."""
    await _make_published(db_session, kind="refund-policy", version="2026-10-01")
    born = date(datetime.now(UTC).date().year - age, 1, 1)
    user = await _buyer(db_session, db_client, birth_date=born)

    resp = await db_client.post("/payments", json={"productKey": "basic_v2", "agreed": True})

    assert resp.status_code == status_code
    orders = (await db_session.scalars(select(Payment).where(Payment.user_id == user.id))).all()
    if status_code == 403:
        assert resp.json()["detail"] == {"code": "PAYMENT_AGE_RESTRICTED"}
        assert orders == []
    else:
        assert len(orders) == 1


async def test_pricing_exposes_the_payment_switch_and_methods(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (await db_client.get("/clover/pricing")).json()
    assert body["paymentsEnabled"] is True
    assert body["payMethods"] == [
        {"payMethod": m.pay_method, "easyPayProvider": m.easy_pay_provider} for m in PAY_METHODS
    ]
    assert {"payMethod": "CARD", "easyPayProvider": None} in body["payMethods"]

    monkeypatch.setattr(settings, "portone_webhook_secret", "")
    assert (await db_client.get("/clover/pricing")).json()["paymentsEnabled"] is False


# ── 결제 완료 동기화 ───────────────────────────────────────────────────────
async def test_complete_grants_paid_and_bonus_with_separate_keys(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, notifications: list[str]
) -> None:
    """정상 결제는 유료·보너스를 각자의 원장 키로 지급하고, 로트는 결제를 가리키며 5년 뒤 만료된다."""
    user = await _user(db_session, db_client)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order)

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert resp.status_code == 200
    assert resp.json() == {"status": "paid", "balance": 3_600}
    assert await _ledger(db_session, user.id) == [
        ("purchase_bonus", 300, f"purchase:{order.id}:bonus"),
        ("purchase_paid", 3_300, f"purchase:{order.id}:paid"),
    ]
    expires = datetime(2031, 10, 9, tzinfo=KST)
    assert await _lots(db_session, user.id) == [
        ("purchase_bonus", 300, order.id, expires),
        ("purchase_paid", 3_300, order.id, expires),
    ]
    row = await _order(db_session, order.id)
    assert (row.status, row.paid_at, row.transaction_id) == ("paid", datetime(2026, 10, 8, 3, tzinfo=UTC), "tx-test")
    assert notifications == [payment_paid_message(row)]


async def test_starter_product_without_bonus_gets_no_bonus_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """보너스 0 인 상품은 보너스 원장·로트를 만들지 않는다. 깨지는 시나리오: 0 클로버 지급 행이 원장에 남는다."""
    user = await _user(db_session, db_client)
    order = await _make_payment(
        db_session, user_id=user.id, channel_key=_CHANNEL, product_key="starter", amount_krw=3_300,
        paid_amount=1_100, bonus_amount=0,
    )
    gateway.payments[order.payment_id] = _paid(order)

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert resp.json() == {"status": "paid", "balance": 1_100}
    assert await _ledger(db_session, user.id) == [("purchase_paid", 1_100, f"purchase:{order.id}:paid")]
    assert [lot[0] for lot in await _lots(db_session, user.id)] == ["purchase_paid"]


async def test_paid_message_carries_no_identifier(db_session: AsyncSession) -> None:
    """디스코드 문구는 상품·금액·상태만 — 회원·주문을 알아볼 단서는 조각도 싣지 않는다."""
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id)

    message = payment_paid_message(order)

    assert "9,900" in message and "베이직" in message
    for identifier in (order.payment_id, order.id.hex, str(order.id), user.id.hex, str(user.id)):
        for start in range(len(identifier) - 5):
            assert identifier[start : start + 6] not in message


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        pytest.param({"amount": _amount(100)}, "amount", id="amount"),
        pytest.param({"currency": "USD"}, "currency", id="currency"),
        pytest.param({"store_id": "store-someone-else"}, "store", id="store"),
        pytest.param({"channel": _channel("channel-key-other")}, "channel", id="channel"),
        pytest.param({"channel": _channel(None)}, "channel", id="channel-missing"),
    ],
)
async def test_mismatch_records_the_field_and_grants_nothing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    gateway: _FakeGateway,
    captured: list[tuple[str, BaseException | None]],
    notifications: list[str],
    overrides: dict[str, Any],
    field: str,
) -> None:
    """포트원이 결제 완료라 해도 주문과 맞지 않으면 지급하지 않고 사람이 볼 건으로 남긴다(자동 취소 없음)."""
    user = await _user(db_session, db_client)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order, **overrides)

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert resp.json() == {"status": "mismatch", "balance": 0}
    row = await _order(db_session, order.id)
    assert (row.status, row.status_reason) == ("mismatch", field)
    assert await _ledger(db_session, user.id) == []
    assert [(dep, type(exc), getattr(exc, "field", None)) for dep, exc in captured] == [
        ("payment", PaymentMismatchError, field)
    ]
    assert notifications == []


async def test_already_paid_order_ignores_a_later_paid_payment(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, captured: list[Any]
) -> None:
    """이미 지급한 주문은 다시 판단하지 않는다 — 금액이 다른 결제 완료가 와도 그대로다. 깨지는 시나리오: 상태 검사가 빠져
    지급 판단을 다시 하고(대조에서 mismatch 로 덮어쓰거나, 대조를 통과하면 멱등키 그물에만 기대게 된다)."""
    user = await _user(db_session, db_client)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL, status="paid")
    gateway.payments[order.payment_id] = _paid(order, amount=_amount(1))

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert resp.json() == {"status": "paid", "balance": 0}
    assert (await _order(db_session, order.id)).status == "paid"
    assert captured == []


async def test_existing_ledger_key_stops_a_second_grant(db_session: AsyncSession, gateway: _FakeGateway) -> None:
    """상태 검사를 지나쳐도 원장 멱등키가 두 번째 지급을 막고 되돌린다(로트·잔액 변화 없음)."""
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    db_session.add(
        CloverLedger(
            user_id=user.id, amount=1, balance_after=0, kind="purchase_paid", idempotency_key=f"purchase:{order.id}:paid"
        )
    )
    await db_session.flush()
    gateway.payments[order.payment_id] = _paid(order)

    user_id = user.id  # 되감긴 SAVEPOINT 가 세션의 객체를 만료시키므로 id 를 먼저 잡아 둔다

    outcome = await sync_payment(db_session, gateway, order.payment_id)

    assert (outcome.result, outcome.status, outcome.notification) == ("already", "pending", None)
    assert await _lots(db_session, user_id) == []
    assert await db_session.scalar(select(User.clover_balance).where(User.id == user_id)) == 0


async def test_bonus_key_collision_commits_nothing(db_session: AsyncSession, gateway: _FakeGateway) -> None:
    """보너스 키에서만 충돌해도 앞서 flush 된 유료 지급까지 함께 되감긴다 — 유료·보너스가 한 SAVEPOINT 안에 있어서다.
    깨지는 시나리오: 둘을 따로 묶으면 유료만 커밋된 반쪽 지급이 남고 주문은 pending 이라 재시도마다 같은 반쪽이 쌓인다."""
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    db_session.add(
        CloverLedger(
            user_id=user.id, amount=1, balance_after=0, kind="purchase_bonus", idempotency_key=f"purchase:{order.id}:bonus"
        )
    )
    await db_session.flush()
    gateway.payments[order.payment_id] = _paid(order)
    user_id, order_id = user.id, order.id  # 되감긴 SAVEPOINT 가 세션의 객체를 만료시킨다

    outcome = await sync_payment(db_session, gateway, order.payment_id)

    assert (outcome.result, outcome.status) == ("already", "pending")
    assert await _lots(db_session, user_id) == []
    assert await _ledger(db_session, user_id) == [("purchase_bonus", 1, f"purchase:{order_id}:bonus")]
    assert await db_session.scalar(select(User.clover_balance).where(User.id == user_id)) == 0
    assert (await _order(db_session, order_id)).status == "pending"


async def test_payment_confirmed_after_the_owner_withdrew_is_not_credited(
    db_session: AsyncSession, gateway: _FakeGateway, captured: list[tuple[str, BaseException | None]]
) -> None:
    """결제창에서 돈이 나간 뒤 확정이 늦게 오는 사이에 탈퇴했으면 지급하지 않고 운영자 환불로 넘긴다. 깨지는 시나리오:
    탈퇴 계정에 아무도 쓸 수 없는 잔액·로트가 생기고 주문은 paid 라 아무도 알아채지 못한다. 그 뒤 콘솔 환불의 취소
    웹훅이 오면 회수할 것 없이 cancelled 로 맞고, 돌려준 돈은 콘솔 취소 기록으로 남는다."""
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    await db_session.execute(update(User).where(User.id == user.id).values(deleted_at=datetime.now(UTC)))
    gateway.payments[order.payment_id] = _paid(order)

    outcome = await sync_payment(db_session, gateway, order.payment_id)

    assert (outcome.result, outcome.status, outcome.notification) == ("owner_withdrawn", "owner_withdrawn", None)
    assert (await _order(db_session, order.id)).status == "owner_withdrawn"
    assert await _lots(db_session, user.id) == []
    assert await _ledger(db_session, user.id) == []
    assert [(dep, type(exc)) for dep, exc in captured] == [("payment", PaymentOwnerWithdrawnError)]

    gateway.payments[order.payment_id] = CancelledPayment(
        **_common(order),
        channel=_channel(_CHANNEL),
        amount=_amount(order.amount_krw, cancelled=order.amount_krw),
        cancellations=[
            SucceededPaymentCancellation(
                id="console-cancel",
                total_amount=order.amount_krw,
                tax_free_amount=0,
                vat_amount=0,
                reason="탈퇴 회원 환불",
                requested_at=_PAID_AT,
            )
        ],
        cancelled_at=_PAID_AT,
    )
    assert (await sync_payment(db_session, gateway, order.payment_id)).result == "cancelled"
    refunded = await _order(db_session, order.id)
    assert (refunded.status, refunded.cancelled_amount_krw) == ("cancelled", order.amount_krw)
    assert await _lots(db_session, user.id) == []
    assert await _ledger(db_session, user.id) == []
    rows = (
        await db_session.execute(
            select(CancellationRow.source, CancellationRow.status).where(
                CancellationRow.payment_id == order.id
            )
        )
    ).all()
    assert [tuple(row) for row in rows] == [("console", "succeeded")]


async def test_complete_twice_grants_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, committing_request_session: None
) -> None:
    """요청마다 커밋이 진짜 경계인 채로 두 번 불러도 원장은 두 행(유료·보너스)이다."""
    user = await _user(db_session, db_client)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order)

    first = await db_client.post(f"/payments/{order.payment_id}/complete")
    second = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert [first.json(), second.json()] == [{"status": "paid", "balance": 3_600}] * 2
    assert [kind for kind, _, _ in await _ledger(db_session, user.id)] == ["purchase_bonus", "purchase_paid"]


async def test_complete_for_someone_elses_order_is_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    owner = await _user(db_session)
    order = await _make_payment(db_session, user_id=owner.id, channel_key=_CHANNEL)
    await _user(db_session, db_client)

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (404, {"code": "PAYMENT_NOT_FOUND"})
    assert gateway.calls == []


async def test_complete_when_portone_is_unreachable_is_retryable(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, captured: list[Any]
) -> None:
    user = await _user(db_session, db_client)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.unavailable = True

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert (resp.status_code, resp.json()["detail"]) == (502, {"code": "PORTONE_UNAVAILABLE"})
    assert (await _order(db_session, order.id)).status == "pending"
    assert [dep for dep, _ in captured] == ["portone"]


async def test_complete_works_even_when_payments_are_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이미 돈이 나간 결제의 동기화는 스위치와 무관하다 — 끄기 직전에 시작한 결제도 지급받아야 한다."""
    user = await _user(db_session, db_client)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order)
    monkeypatch.setattr(settings, "payments_enabled", False)

    resp = await db_client.post(f"/payments/{order.payment_id}/complete")

    assert resp.json() == {"status": "paid", "balance": 3_600}


async def test_failed_pending_and_cancelled_before_grant(db_session: AsyncSession, gateway: _FakeGateway) -> None:
    """지급 전 상태들: 실패 → failed, 미확정 → 그대로, 전액 취소 → cancelled, 일부 취소 → mismatch(지급량 규칙이 없다)."""
    user = await _user(db_session)
    failed, ready, cancelled, partial = [
        await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL) for _ in range(4)
    ]
    gateway.payments[failed.payment_id] = FailedPayment(
        **_common(failed), amount=_amount(failed.amount_krw), failed_at=_PAID_AT, failure=PaymentFailure()
    )
    gateway.payments[ready.payment_id] = ReadyPayment(**_common(ready), amount=_amount(ready.amount_krw))
    for order, cls in ((cancelled, CancelledPayment), (partial, PartialCancelledPayment)):
        gateway.payments[order.payment_id] = cls(
            **_common(order),
            channel=_channel(_CHANNEL),
            amount=_amount(order.amount_krw, cancelled=order.amount_krw),
            cancellations=[],
            cancelled_at=_PAID_AT,
        )

    outcomes = [
        (await sync_payment(db_session, gateway, o.payment_id)).result for o in (failed, ready, cancelled, partial)
    ]

    assert outcomes == ["failed", "pending", "cancelled", "mismatch"]
    assert [(await _order(db_session, o.id)).status for o in (failed, ready, cancelled, partial)] == [
        "failed",
        "pending",
        "cancelled",
        "mismatch",
    ]
    assert await _ledger(db_session, user.id) == []


async def test_paid_after_failed_is_granted(db_session: AsyncSession, gateway: _FakeGateway) -> None:
    """포트원 상태가 진실이다 — 실패로 기록한 뒤 결제 완료가 오면 지급한다. 막으면 돈은 나갔는데 지급이 없는 행이 남는다."""
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL, status="failed")
    gateway.payments[order.payment_id] = _paid(order)

    assert (await sync_payment(db_session, gateway, order.payment_id)).result == "granted"


async def test_erase_account_leaves_payment_rows_untouched(db_session: AsyncSession) -> None:
    """결제 기록은 법정 보존 대상이라 탈퇴가 지우지도 고치지도 않는다(회원 행은 가명으로 남는다)."""
    user = await _user(db_session)
    order = await _make_payment(
        db_session, user_id=user.id, status="paid", paid_at=datetime(2026, 10, 8, tzinfo=UTC), transaction_id="tx"
    )
    table = Payment.__table__
    before = (await db_session.execute(select(table).where(table.c.id == order.id))).mappings().one()

    async def keep(storage_key: str) -> None:
        return None

    await erase_account(db_session, user, delete_storage_object=keep)

    after = (await db_session.execute(select(table).where(table.c.id == order.id))).mappings().one()
    assert dict(after) == dict(before)
    assert (await db_session.get(User, user.id)) is not None


# ── 웹훅 ─────────────────────────────────────────────────────────────────
def _signed(payload: str, *, secret: str = _WEBHOOK_SECRET) -> dict[str, str]:
    """Standard Webhooks 서명: `id.timestamp.payload` 를 시크릿(`whsec_` 뒤 base64)으로 HMAC-SHA256."""
    message_id = f"msg_{uuid.uuid4().hex}"
    timestamp = str(int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signature = base64.b64encode(hmac.digest(key, f"{message_id}.{timestamp}.{payload}".encode(), "sha256")).decode()
    return {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{signature}",
        "content-type": "application/json",
    }


def _event(kind: str, payment_id: str, *, store_id: str = _STORE) -> str:
    data: dict[str, str] = {"paymentId": payment_id, "storeId": store_id, "transactionId": "tx-test"}
    if "Cancel" in kind:
        data["cancellationId"] = "cancel-test"
    return json.dumps({"type": f"Transaction.{kind}", "timestamp": "2026-10-08T03:00:01Z", "data": data})


async def _post_webhook(client: httpx.AsyncClient, payload: str, headers: dict[str, str]) -> httpx.Response:
    return await client.post("/payments/portone/webhook", content=payload.encode(), headers=headers)


async def test_webhook_paid_grants(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, notifications: list[str]
) -> None:
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order)
    payload = _event("Paid", order.payment_id)

    resp = await _post_webhook(db_client, payload, _signed(payload))

    assert resp.status_code == 200
    assert [kind for kind, _, _ in await _ledger(db_session, user.id)] == ["purchase_bonus", "purchase_paid"]
    assert len(notifications) == 1


async def test_webhook_with_a_bad_signature_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    payload = _event("Paid", order.payment_id)
    forged = _signed(payload, secret="whsec_" + base64.b64encode(b"someone-elses-secret").decode())

    resp = await _post_webhook(db_client, payload, forged)

    assert resp.status_code == 401
    assert gateway.calls == []


async def test_webhook_body_is_verified_as_sent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    """서명은 받은 원문 그대로에 대해 맞는다 — 서명한 뒤 본문을 바꾸면(공백 하나라도) 거절된다."""
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    payload = _event("Paid", order.payment_id)

    resp = await _post_webhook(db_client, payload + " ", _signed(payload))

    assert resp.status_code == 401


@pytest.mark.parametrize(
    "secret", [pytest.param("", id="empty"), pytest.param("whsec_###", id="malformed")]
)
async def test_webhook_secret_problem_is_retryable_and_reported(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, captured: list[Any], secret: str
) -> None:
    monkeypatch.setattr(settings, "portone_webhook_secret", secret)
    payload = _event("Paid", "clvwhatever")

    resp = await _post_webhook(db_client, payload, _signed(payload))

    assert resp.status_code == 503
    assert [dep for dep, _ in captured] == ["payment"]


async def test_webhook_secret_problem_with_payments_off_is_not_reported(
    db_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, captured: list[Any]
) -> None:
    """결제가 꺼져 비밀이 빈 것이 정상인 동안에는 인증 없는 요청마다 Bugsink 이벤트를 만들지 않는다(응답은 그대로 503)."""
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "portone_webhook_secret", "")
    payload = _event("Paid", "clvwhatever")

    resp = await _post_webhook(db_client, payload, _signed(payload))

    assert resp.status_code == 503
    assert captured == []


async def test_webhook_with_an_unrecognized_shape_is_reported(
    db_client: httpx.AsyncClient, gateway: _FakeGateway, captured: list[tuple[str, BaseException | None]]
) -> None:
    """서명은 맞는데 SDK 가 모르는 모양(예: 옛 웹훅 버전)이면 SDK 가 원본 dict 를 돌려준다. 깨지는 시나리오: 모든 결제
    웹훅이 흔적 없이 200 으로 사라지고, 창을 닫은 결제가 pending 으로 쌓인다."""
    payload = json.dumps({"tx_id": "tx-old", "payment_id": "clvold", "status": "Paid"})

    resp = await _post_webhook(db_client, payload, _signed(payload))

    assert resp.status_code == 200
    assert [(dep, type(exc)) for dep, exc in captured] == [("payment", PaymentWebhookConfigError)]
    assert "clvold" not in str(captured[0][1])
    assert gateway.calls == []


async def test_webhook_portone_failure_asks_for_a_retry(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway
) -> None:
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.unavailable = True
    payload = _event("Paid", order.payment_id)

    resp = await _post_webhook(db_client, payload, _signed(payload))

    assert resp.status_code == 503


@pytest.mark.parametrize(
    ("kind", "store_id", "known"),
    [
        pytest.param("Ready", _STORE, True, id="unrelated-event"),
        pytest.param("Paid", "store-someone-else", True, id="other-store"),
        pytest.param("Paid", _STORE, False, id="unknown-order"),
    ],
)
async def test_webhook_ignores_what_is_not_ours(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, kind: str, store_id: str, known: bool
) -> None:
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order)
    payment_id = order.payment_id if known else f"clv{uuid.uuid4().hex}"
    payload = _event(kind, payment_id, store_id=store_id)

    resp = await _post_webhook(db_client, payload, _signed(payload))

    assert resp.status_code == 200
    assert gateway.calls == []
    assert await _ledger(db_session, user.id) == []


async def test_webhook_works_with_payments_switched_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, gateway: _FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(db_session)
    order = await _make_payment(db_session, user_id=user.id, channel_key=_CHANNEL)
    gateway.payments[order.payment_id] = _paid(order)
    monkeypatch.setattr(settings, "payments_enabled", False)
    payload = _event("Paid", order.payment_id)

    assert (await _post_webhook(db_client, payload, _signed(payload))).status_code == 200
    assert (await _order(db_session, order.id)).status == "paid"


# ── 겹친 확인: 독립 커넥션 둘 ────────────────────────────────────────────────
_MARKER_DOMAIN = "payments-independent.test"


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """롤백되지 않는 독립 커넥션. 이 파일이 만든 표지 도메인 사용자의 행만 FK 순서대로 지운다."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            await cleanup.execute(delete(Payment).where(Payment.user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def test_overlapping_complete_and_webhook_grant_once(
    independent_factory: async_sessionmaker[AsyncSession], gateway: _FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    """브라우저 알림과 웹훅이 같은 결제를 동시에 맞춰도 주문 행 잠금에서 줄을 서 지급은 한 번(원장 두 행)이다. 둘이 실제로
    잠금을 기다리는지 먼저 단언한다 — 아니면 순차로 돌아도 통과하는 항진명제가 된다. 뒤쪽이 원장 멱등키 그물이 아니라 행
    잠금 뒤의 상태 검사에서 멈췄는지도 본다(그물에 걸리면 되감기 경고가 남는다) — 그물만으로도 지급은 한 번이라, 이것을 안
    보면 행 잠금이 빠져도 통과한다."""
    async with independent_factory() as setup:
        user = _make_user(email=f"pay-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        setup.add(user)
        await setup.flush()
        order = await _make_payment(setup, user_id=user.id, channel_key=_CHANNEL)
        await setup.commit()
    gateway.payments[order.payment_id] = _paid(order)

    async def run_sync() -> str:
        async with independent_factory() as session:
            return (await sync_payment(session, gateway, order.payment_id)).result

    async with independent_factory() as holder:
        await holder.execute(select(Payment.id).where(Payment.id == order.id).with_for_update())
        first = asyncio.ensure_future(run_sync())
        second = asyncio.ensure_future(run_sync())
        await _assert_blocked(first)
        await _assert_blocked(second)
        await holder.commit()
    with caplog.at_level(logging.WARNING, logger="api.payments.service"):
        results = await asyncio.gather(first, second)

    assert sorted(results) == ["already", "granted"]
    assert [r.getMessage() for r in caplog.records if r.name == "api.payments.service"] == []
    async with independent_factory() as check:
        assert [kind for kind, _, _ in await _ledger(check, user.id)] == ["purchase_bonus", "purchase_paid"]
        assert await check.scalar(select(User.clover_balance).where(User.id == user.id)) == 3_600

