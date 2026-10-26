"""`GET /me/clover` 의 `breakdown` — 잔액을 유료·보너스·무료 몫으로 나눈 값.

허브가 "충전한 클로버 / 보너스 / 무료" 를 나눠 보이고, 환불 안내는 유료 몫을 쓴다. 기존 `paidBalance`(유료 + 보너스)의 뜻은
바뀌지 않는다 — 탈퇴 경고가 `GET /me` 의 같은 값을 읽는다.
"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover import router as clover_router
from api.core.clover import grant, spend
from api.db.models.auth import User
from factories import _login_as, _make_payment, _make_user


async def _logged_in(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def test_breakdown_splits_the_balance_into_paid_bonus_and_free(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """세 몫의 합이 잔액이고, 유료·보너스는 구매 로트의 남은 양이다. 깨지는 시나리오: 무료 몫을 로트 합으로 따로 세어 합이
    잔액과 어긋나거나, 쓴 몫(보너스부터 깎인다)이 반영되지 않아 남은 보너스가 지급량 그대로 보인다. `paidBalance` 는 여전히
    유료와 보너스의 합이고 탈퇴 경고가 읽는 `GET /me` 의 값과 같다."""
    user = await _logged_in(db_client, db_session)
    order = await _make_payment(db_session, user_id=user.id, status="paid", paid_at=datetime.now(UTC))
    await grant(db_session, user_id=user.id, amount=1_000, kind="purchase_paid", payment_id=order.id)
    await grant(db_session, user_id=user.id, amount=150, kind="purchase_bonus", payment_id=order.id)
    await grant(db_session, user_id=user.id, amount=100, kind="mission_grant")
    # 무료 100 을 다 쓰고 보너스 40 을 쓴다 — 차감 순서는 무료 → 보너스 → 유료다.
    assert await spend(db_session, user_id=user.id, amount=140, kind="chat_spend") is not None
    await db_session.commit()

    body = (await db_client.get("/me/clover")).json()
    me = (await db_client.get("/me")).json()

    assert body["breakdown"] == {"paid": 1_000, "bonus": 110, "free": 0}
    assert sum(body["breakdown"].values()) == body["balance"] == 1_110
    assert body["paidBalance"] == me["paidCloverBalance"] == 1_110


async def test_breakdown_free_share_is_the_rest_of_the_balance(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """구매 로트가 없으면 잔액 전부가 무료 몫이다(무료 로트의 종류와 무관하다 — 백필 로트도 무료다)."""
    user = await _logged_in(db_client, db_session)
    await grant(db_session, user_id=user.id, amount=70, kind="mission_grant")
    await grant(db_session, user_id=user.id, amount=5, kind="admin_grant")
    await db_session.commit()

    body = (await db_client.get("/me/clover")).json()

    assert body["breakdown"] == {"paid": 0, "bonus": 0, "free": 75}


async def test_balance_and_shares_come_from_one_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """잔액을 앞서 읽은 회원 객체에서 가져오면, 그 뒤 결제 지급이 커밋됐을 때 로트 합만 늘어 무료 몫이 음수가 된다. 앞서 읽은
    잔액이 낡았다고(0) 꾸며도 응답의 잔액·세 몫은 한 SELECT 의 값이라 합이 맞다."""
    user = await _logged_in(db_client, db_session)
    order = await _make_payment(db_session, user_id=user.id, status="paid", paid_at=datetime.now(UTC))
    await grant(db_session, user_id=user.id, amount=1_000, kind="purchase_paid", payment_id=order.id)
    await db_session.commit()

    stale = await clover_router._require_active_user(db_session, user.id)
    stale_copy = User(id=stale.id, clover_balance=0)

    async def stale_user(_db: AsyncSession, _user_id: object) -> User:
        return stale_copy

    monkeypatch.setattr(clover_router, "_require_active_user", stale_user)

    body = (await db_client.get("/me/clover")).json()

    assert body["balance"] == 1_000
    assert body["breakdown"] == {"paid": 1_000, "bonus": 0, "free": 0}
