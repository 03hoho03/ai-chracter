"""결제 완료 확인 응답(`POST /payments/{payment_id}/complete`)의 `grantedPaid`·`grantedBonus` — 이 결제로 실제 지급한 수량.

화면은 결제 뒤 "유료 N개와 보너스 M개를 받았어요"를 이 값으로 보인다. 값은 그 결제로 만든 구매 로트의 지급량(`granted_amount`)에서
온다 — 상품표의 지금 숫자나 주문 행의 사본으로 계산하면 상품을 바꾼 뒤 확인한 옛 결제가 새 숫자를 보인다. 지급하지 않은 상태
(대기·실패·불일치·전액 취소)는 null 이다. 부분 취소는 지급한 뒤의 일이라 지급량을 그대로 보인다(회수는 내역이 보인다).

포트원 동기화는 이 파일의 대상이 아니라 `sync_payment` 를 지금 주문 상태를 그대로 돌려주는 가짜로 바꾼다 — 동기화 자체는
`test_payments_api.py` 가 본다.
"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.db.models.payment import Payment, PaymentStatus
from api.main import app
from api.payments import router as payments_router
from api.payments.portone import get_portone_gateway
from api.payments.service import SyncOutcome
from factories import _login_as, _make_payment, _make_user


@pytest.fixture(autouse=True)
def _no_gateway() -> object:
    app.dependency_overrides[get_portone_gateway] = lambda: object()
    yield
    app.dependency_overrides.pop(get_portone_gateway, None)


async def _order(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: PaymentStatus,
    grants: tuple[tuple[clover.CloverKind, int], ...] = (),
) -> Payment:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    order = await _make_payment(
        db_session, user_id=user.id, status=status, paid_at=datetime.now(UTC), paid_amount=3_300, bonus_amount=330
    )
    for kind, amount in grants:
        await clover.grant(db_session, user_id=user.id, amount=amount, kind=kind, payment_id=order.id)
    await db_session.commit()
    await _login_as(db_client, user.id)

    async def same_status(_db: AsyncSession, _gateway: object, _payment_id: str) -> SyncOutcome:
        return SyncOutcome(result="already", status=status)

    monkeypatch.setattr(payments_router, "sync_payment", same_status)
    return order


async def _complete(db_client: httpx.AsyncClient, order: Payment) -> dict[str, object]:
    resp = await db_client.post(f"/payments/{order.payment_id}/complete")
    assert resp.status_code == 200
    body: dict[str, object] = resp.json()
    return body


async def test_paid_order_reports_the_granted_lot_amounts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """값은 로트의 지급량이다 — 주문 행의 사본(3,300·330)과 일부러 다르게 지급해 둔다. 깨지는 시나리오: 사본이나 상품표로 계산해,
    상품을 바꾼 뒤 확인한 옛 결제가 지급하지 않은 숫자를 보인다."""
    order = await _order(
        db_client, db_session, monkeypatch, status="paid", grants=(("purchase_paid", 1_000), ("purchase_bonus", 50))
    )

    body = await _complete(db_client, order)

    assert (body["status"], body["grantedPaid"], body["grantedBonus"]) == ("paid", 1_000, 50)


async def test_paid_order_without_a_bonus_reports_zero_bonus(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """보너스 없는 상품은 보너스 로트가 없다 — 지급은 했으므로 null 이 아니라 0 이다."""
    order = await _order(db_client, db_session, monkeypatch, status="paid", grants=(("purchase_paid", 300),))

    body = await _complete(db_client, order)

    assert (body["grantedPaid"], body["grantedBonus"]) == (300, 0)


async def test_partially_cancelled_order_still_reports_what_was_granted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """부분 취소는 지급한 뒤의 회수다 — 회수로 남은 양이 줄어도 지급량은 그대로 보인다."""
    order = await _order(
        db_client,
        db_session,
        monkeypatch,
        status="partially_cancelled",
        grants=(("purchase_paid", 1_000), ("purchase_bonus", 50)),
    )
    assert await clover.revoke_purchase_lots(db_session, payment_id=order.id, limit=400) == (400, 0)
    await db_session.commit()

    body = await _complete(db_client, order)

    assert (body["grantedPaid"], body["grantedBonus"]) == (1_000, 50)


@pytest.mark.parametrize(
    ("status", "granted_before"),
    [
        pytest.param("pending", False, id="pending"),
        pytest.param("failed", False, id="failed"),
        pytest.param("mismatch", False, id="mismatch"),
        # 지급한 뒤 전액 취소됐다 — 로트는 남아 있지만 이번 결제로 받은 것이 없다.
        pytest.param("cancelled", True, id="cancelled-after-grant"),
    ],
)
async def test_order_without_a_standing_grant_reports_null(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    status: PaymentStatus,
    granted_before: bool,
) -> None:
    grants: tuple[tuple[clover.CloverKind, int], ...] = (("purchase_paid", 1_000),) if granted_before else ()
    order = await _order(db_client, db_session, monkeypatch, status=status, grants=grants)

    body = await _complete(db_client, order)

    assert (body["status"], body["grantedPaid"], body["grantedBonus"]) == (status, None, None)
