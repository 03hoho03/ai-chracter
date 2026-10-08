"""결제·취소·구매 로트의 CHECK 와 부분 유니크. alembic 1.18.5 의 `alembic check` 는 CHECK 와 부분 인덱스의 WHERE 를
비교하지 않아, 이 행위 테스트가 마이그레이션이 실제로 그 제약을 걸었는지의 유일한 검증이다(테스트 DB 는
`alembic upgrade head` 로 만든다)."""

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.clover import CloverLot
from api.db.models.payment import Payment, PaymentCancellation
from factories import _create_admin, _make_payment, _make_user


async def _user_id(db: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db.add(user)
    await db.flush()
    return user.id


# ── 주문 ─────────────────────────────────────────────────────────────────
async def test_valid_payment_is_accepted(db_session: AsyncSession) -> None:
    """대조군 — 아래 거부들이 셋업 탓이 아니라 그 값 탓임을 보인다(보너스 0 인 상품도 정상이다)."""
    await _make_payment(db_session, user_id=await _user_id(db_session), bonus_amount=0, cancelled_amount_krw=9_900)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": "refunded"}, id="unknown-status"),
        pytest.param({"amount_krw": 0}, id="amount-zero"),
        pytest.param({"paid_amount": 0}, id="paid-zero"),
        pytest.param({"bonus_amount": -1}, id="bonus-negative"),
        pytest.param({"cancelled_amount_krw": 9_901}, id="cancelled-over-amount"),
        pytest.param({"cancelled_amount_krw": -1}, id="cancelled-negative"),
    ],
)
async def test_payment_check_constraints_reject(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    user_id = await _user_id(db_session)
    with pytest.raises(IntegrityError):
        await _make_payment(db_session, user_id=user_id, **overrides)


# ── 취소 ─────────────────────────────────────────────────────────────────
async def _cancellation(db: AsyncSession, payment: Payment, **overrides: object) -> PaymentCancellation:
    defaults: dict[str, object] = {
        "payment_id": payment.id,
        "source": "console",
        "status": "succeeded",
        "amount_krw": 1_000,
    }
    defaults.update(overrides)
    row = PaymentCancellation(**defaults)
    db.add(row)
    await db.flush()
    return row


async def test_valid_admin_and_console_cancellations_are_accepted(db_session: AsyncSession) -> None:
    payment = await _make_payment(db_session, user_id=await _user_id(db_session), status="paid")
    admin = await _create_admin(db_session)
    await _cancellation(db_session, payment)
    await _cancellation(
        db_session,
        payment,
        source="admin",
        status="requested",
        admin_id=admin["id"],
        request_received_on=date(2026, 10, 8),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"source": "user"}, id="unknown-source"),
        pytest.param({"status": "pending"}, id="unknown-status"),
        pytest.param({"amount_krw": 0}, id="amount-zero"),
        pytest.param({"clawback_paid": -1}, id="clawback-negative"),
        pytest.param({"source": "admin", "request_received_on": date(2026, 10, 8)}, id="admin-without-admin-id"),
        pytest.param({"with_admin": True}, id="console-with-admin-id"),
        pytest.param({"source": "admin", "with_admin": True}, id="admin-without-received-on"),
        pytest.param({"request_received_on": date(2026, 10, 8)}, id="console-with-received-on"),
    ],
)
async def test_cancellation_check_constraints_reject(db_session: AsyncSession, overrides: dict[str, object]) -> None:
    payment = await _make_payment(db_session, user_id=await _user_id(db_session), status="paid")
    if overrides.pop("with_admin", False):
        overrides["admin_id"] = (await _create_admin(db_session))["id"]
    with pytest.raises(IntegrityError):
        await _cancellation(db_session, payment, **overrides)


async def test_one_payment_has_at_most_one_requested_cancellation(db_session: AsyncSession) -> None:
    """진행 중 환불 시도는 결제당 하나다 — 이 행이 환불 시도의 멱등 단위다. 끝난 시도와는 함께 있을 수 있다."""
    payment = await _make_payment(db_session, user_id=await _user_id(db_session), status="paid")
    await _cancellation(db_session, payment, status="succeeded")
    await _cancellation(db_session, payment, status="requested")

    with pytest.raises(IntegrityError):
        await _cancellation(db_session, payment, status="requested")


# ── 구매 로트 ↔ 결제 ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("kind", "with_payment"),
    [
        pytest.param("purchase_paid", False, id="purchase-without-payment"),
        pytest.param("purchase_bonus", False, id="bonus-without-payment"),
        pytest.param("admin_grant", True, id="free-with-payment"),
    ],
)
async def test_lot_payment_reference_matches_purchase_kind(
    db_session: AsyncSession, kind: str, with_payment: bool
) -> None:
    """구매 로트만 결제를 가리킨다. 깨지는 시나리오: 결제 없는 구매 로트는 환불이 회수하지 못하고, 결제를 가리키는 무료
    로트는 환불이 무료분까지 회수한다."""
    user_id = await _user_id(db_session)
    payment_id = (await _make_payment(db_session, user_id=user_id)).id if with_payment else None
    db_session.add(
        CloverLot(user_id=user_id, granted_amount=10, remaining=10, kind=kind, payment_id=payment_id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_one_payment_has_one_lot_per_purchase_kind(db_session: AsyncSession) -> None:
    """같은 결제의 유료 로트는 하나뿐이다 — 결제 확인이 겹쳐 두 번 지급되는 것을 막는 마지막 방어선. 같은 결제의 유료·
    보너스 한 쌍은 정상이다."""
    user_id = await _user_id(db_session)
    payment = await _make_payment(db_session, user_id=user_id)
    for kind in ("purchase_paid", "purchase_bonus"):
        db_session.add(CloverLot(user_id=user_id, granted_amount=10, remaining=10, kind=kind, payment_id=payment.id))
    await db_session.flush()

    db_session.add(
        CloverLot(user_id=user_id, granted_amount=10, remaining=10, kind="purchase_paid", payment_id=payment.id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
