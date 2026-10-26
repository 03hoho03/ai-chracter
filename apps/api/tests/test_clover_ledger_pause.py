"""클로버 정지 스위치(`CLOVER_LEDGER_PAUSED`) — 켜지면 클로버를 새로 깎거나 주는 경로가 503 `CLOVER_PAUSED` 로 멈춘다.

단위 전환·되돌림처럼 잔액을 한꺼번에 옮기는 동안 새 차감·지급이 끼지 않게 하는 스위치다. 이 파일이 검증하는 성질:

1. 막는 경로 전부(아래 `_BLOCKED` 목록)가 503 이고 원장·잔액이 그대로다. 각 경로는 그 자리의 검사가 빠지면 다른 응답이 나오게
   셋업한다 — 채팅·이미지 유료 갈래는 오늘치 확인을 안 했고 가격 버전도 옛 값이라, 게이트의 정지 검사가 빠지면 확인 429 나 가격
   409 가 먼저 나간다(정지가 그 둘보다 앞이다). 라우트 의존성으로 막는 경로는 검사가 빠지면 그 라우트의 다음 거절(422·404·503
   결제 꺼짐)이나 지급이 나간다. 그래서 목록에서 경로 하나의 검사를 빼면 그 경우가 빨개진다.
2. 막지 않는 것: 무료 대화 턴, 무료 토큰 이미지, 환급, 지급(결제 완료·웹훅이 쓰는 함수), 결제 완료 확인 라우트, 웹훅 라우트,
   탈퇴 소멸. 이미 시작한 일의 마무리와 돈이 이미 나간 결제의 동기화는 멈추면 안 된다.

만료 배치(`scripts/ops/expire_clover.py`)는 앱 밖의 psql 원시 SQL 이라 이 스위치를 읽을 길이 없다 — 이 파일의 대상이 아니다.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.rate_limit_gate import charge_chat_turn, enforce_image_rate_limit
from api.db.models import User
from api.db.models.clover import CloverLedger
from api.images.schemas import GenerateImageRequest
from api.llm.chat_models import ChatModelId, chat_turn_cost
from api.main import app
from api.payments import router as payments_router
from api.payments.portone import get_portone_gateway
from api.payments.service import SyncOutcome
from factories import _create_admin, _login_as, _login_as_admin, _make_payment, _make_user_with_clover_lot

_START_BALANCE = 1000
_PAUSED_CODE = "CLOVER_PAUSED"


@pytest.fixture(autouse=True)
def _paused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "clover_ledger_paused", True)


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db.bind, expire_on_commit=False)


async def _member(db: AsyncSession, *, confirmed: bool = False, **overrides: object) -> User:
    if confirmed:
        overrides["clover_spend_confirmed_on"] = clover.kst_today(datetime.now(UTC))
    user = await _make_user_with_clover_lot(db, clover_balance=_START_BALANCE, **overrides)
    await db.commit()
    return user


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = (await db.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))).all()
    return [(row.kind, row.amount) for row in rows]


async def _balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(
        select(User.clover_balance).where(User.id == user_id).execution_options(populate_existing=True)
    )
    assert balance is not None
    return balance


async def _refused(call: Callable[[], Awaitable[object]]) -> tuple[int, object]:
    with pytest.raises(HTTPException) as caught:
        await call()
    return caught.value.status_code, caught.value.detail


def _stale() -> int:
    return clover.PRICE_VERSION + 1


# ── 막는 경로 ──────────────────────────────────────────────────────────────────
# 각 경우는 (응답 상태, detail, 셋업한 회원 id) 를 돌려준다. 회원의 원장·잔액은 공통 단언이 본다.
_Case = Callable[[httpx.AsyncClient, AsyncSession, pytest.MonkeyPatch], Awaitable[tuple[int, object, uuid.UUID]]]


async def _chat(db: AsyncSession, user: User, model: ChatModelId) -> tuple[int, object]:
    return await _refused(
        lambda: charge_chat_turn(
            user.id,
            db,
            _factory(db),
            model=model,
            price=chat_turn_cost(model),
            usage=clover.SpendUsage("preview"),
            price_version=_stale(),
        )
    )


async def _chat_after_daily_free(
    _client: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    user = await _member(db)
    return (*await _chat(db, user, "gemini"), user.id)


async def _chat_unverified(
    _client: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    monkeypatch.setattr(rate_limit_gate, "is_identity_gated", lambda _user: True)
    user = await _member(db)
    return (*await _chat(db, user, "gemini"), user.id)


async def _chat_premium(
    _client: httpx.AsyncClient, db: AsyncSession, _monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    user = await _member(db)
    return (*await _chat(db, user, "opus"), user.id)


async def _image_after_free_tokens(
    _client: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    monkeypatch.setattr(rate_limit_gate, "IMAGE_TOKEN_CAPACITY", 0)
    user = await _member(db)
    request = GenerateImageRequest.model_validate(
        {
            "prompt": "a cat wizard",
            "model": "v1",
            "style": "soft_portrait",
            "aspectRatio": "1:1",
            "count": 1,
            "priceVersion": _stale(),
        }
    )
    status, detail = await _refused(
        lambda: enforce_image_rate_limit(request, user_id=user.id, db=db, session_factory=_factory(db))
    )
    return status, detail, user.id


async def _direct_spend(
    _client: httpx.AsyncClient, db: AsyncSession, _monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    """모든 차감이 지나는 `spend` — 소설화 작업 생성·노벨 소장·요약 다시 만들기는 이 줄 하나가 막는다."""
    user = await _member(db, confirmed=True)
    status, detail = await _refused(
        lambda: clover.spend(db, user_id=user.id, amount=10, kind="novelize_spend")
    )
    return status, detail, user.id


async def _mission_claim(
    client: httpx.AsyncClient, db: AsyncSession, _monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    """검사가 빠지면 달성하지 않은 미션이라 422 다."""
    user = await _member(db)
    await _login_as(client, user.id)
    resp = await client.post("/me/clover/missions/first_message/claim")
    return resp.status_code, resp.json()["detail"], user.id


async def _admin_adjust(
    client: httpx.AsyncClient, db: AsyncSession, _monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    """검사가 빠지면 100 이 지급된다."""
    user = await _member(db)
    admin = await _create_admin(db)
    await db.commit()
    await _login_as_admin(client, admin)
    resp = await client.post(
        f"/admin/users/{user.id}/clover",
        json={"amount": 100, "adminComment": "보상", "idempotencyKey": f"t-{uuid.uuid4().hex}"},
    )
    return resp.status_code, resp.json()["detail"], user.id


async def _admin_refund(
    client: httpx.AsyncClient, db: AsyncSession, _monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    """검사가 빠지면 없는 결제라 404 다."""
    user = await _member(db)
    admin = await _create_admin(db)
    await db.commit()
    await _login_as_admin(client, admin)
    resp = await client.post(
        "/admin/payments/clv-none/refund",
        json={"reason": "환불", "expectedRefundKrw": 0, "receivedOn": "2026-10-26"},
    )
    return resp.status_code, resp.json()["detail"], user.id


async def _create_order(
    client: httpx.AsyncClient, db: AsyncSession, _monkeypatch: pytest.MonkeyPatch
) -> tuple[int, object, uuid.UUID]:
    """검사가 빠지면 결제 스위치·본인인증 거절이 나간다."""
    user = await _member(db)
    await _login_as(client, user.id)
    resp = await client.post("/payments", json={"productKey": "mini", "agreed": True})
    return resp.status_code, resp.json()["detail"], user.id


_BLOCKED = [
    pytest.param(_chat_after_daily_free, id="chat-after-daily-free"),
    pytest.param(_chat_unverified, id="chat-unverified"),
    pytest.param(_chat_premium, id="chat-premium"),
    pytest.param(_image_after_free_tokens, id="image-after-free-tokens"),
    pytest.param(_direct_spend, id="spend"),
    pytest.param(_mission_claim, id="mission-claim"),
    pytest.param(_admin_adjust, id="admin-adjust"),
    pytest.param(_admin_refund, id="admin-refund"),
    pytest.param(_create_order, id="create-order"),
]


@pytest.mark.parametrize("case", _BLOCKED)
async def test_paused_paths_refuse_with_503_and_move_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: _Case
) -> None:
    status, detail, user_id = await case(db_client, db_session, monkeypatch)

    assert status == 503
    assert isinstance(detail, dict) and detail["code"] == _PAUSED_CODE and detail["message"]
    assert await _ledger(db_session, user_id) == []
    assert await _balance(db_session, user_id) == _START_BALANCE


async def test_switch_off_lets_the_same_spend_through(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """위 막힘의 짝 — 스위치가 꺼져 있으면 같은 차감이 그대로 된다(정지가 늘 켜진 채로 구현되면 빨개진다)."""
    monkeypatch.setattr(settings, "clover_ledger_paused", False)
    user = await _member(db_session)

    assert await clover.spend(db_session, user_id=user.id, amount=10, kind="novelize_spend") is not None


# ── 막지 않는 것 ───────────────────────────────────────────────────────────────
async def test_free_daily_turn_still_runs(db_session: AsyncSession) -> None:
    user = await _member(db_session)

    charge = await charge_chat_turn(
        user.id,
        db_session,
        _factory(db_session),
        model="gemini",
        price=chat_turn_cost("gemini"),
        usage=clover.SpendUsage("preview"),
    )

    assert charge.source == "free"


async def test_free_token_image_still_runs(db_session: AsyncSession) -> None:
    user = await _member(db_session)
    request = GenerateImageRequest.model_validate(
        {"prompt": "a cat wizard", "model": "v1", "style": "soft_portrait", "aspectRatio": "1:1", "count": 1}
    )

    charge = await enforce_image_rate_limit(request, user_id=user.id, db=db_session, session_factory=_factory(db_session))

    assert charge.source == "token"


async def test_refund_of_an_earlier_spend_still_runs(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """정지 전에 깎은 작업이 정지 중에 실패하면 돌려받아야 한다 — 채팅·이미지·요약·소설화·노벨 환급이 모두 이 함수를 지난다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", False)
    user = await _member(db_session)
    spent = await clover.spend(db_session, user_id=user.id, amount=30, kind="image_spend")
    assert spent is not None
    monkeypatch.setattr(settings, "clover_ledger_paused", True)

    balance = await clover.refund_spend(
        db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=30, kind="image_refund"
    )

    assert balance == _START_BALANCE


async def test_grant_and_withdrawal_burn_still_run(db_session: AsyncSession) -> None:
    """결제 완료·웹훅의 지급(`grant`)과 탈퇴 소멸(`burn_all`)은 정지와 무관하다 — 돈이 이미 나간 결제와 탈퇴는 멈추지 않는다."""
    user = await _member(db_session)
    order = await _make_payment(db_session, user_id=user.id, status="paid", paid_at=datetime.now(UTC))

    await clover.grant(db_session, user_id=user.id, amount=300, kind="purchase_paid", payment_id=order.id)
    burned = await clover.burn_all(db_session, user_id=user.id)

    assert burned == _START_BALANCE + 300


async def test_payment_complete_route_is_not_paused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """결제 완료 확인 라우트에 정지 의존성이 붙으면 빨개진다 — 포트원 동기화는 가짜로 바꾼다(동기화는 결제 테스트가 본다)."""
    user = await _member(db_session)
    order = await _make_payment(db_session, user_id=user.id, status="pending")
    await db_session.commit()
    await _login_as(db_client, user.id)

    async def pending(_db: AsyncSession, _gateway: object, _payment_id: str) -> SyncOutcome:
        return SyncOutcome(result="already", status="pending")

    monkeypatch.setattr(payments_router, "sync_payment", pending)
    app.dependency_overrides[get_portone_gateway] = lambda: object()
    try:
        resp = await db_client.post(f"/payments/{order.payment_id}/complete")
    finally:
        app.dependency_overrides.pop(get_portone_gateway, None)

    assert resp.status_code == 200


async def test_portone_webhook_route_is_not_paused(db_client: httpx.AsyncClient) -> None:
    """웹훅에 정지 의존성이 붙으면 서명 검사 전에 503 이 나간다. 서명 없는 요청이라 정지와 무관한 거절이어야 한다."""
    resp = await db_client.post("/payments/portone/webhook", content=b"{}")

    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    detail = body.get("detail") if isinstance(body, dict) else None
    assert not (isinstance(detail, dict) and detail.get("code") == _PAUSED_CODE)


def test_pause_switch_reads_an_empty_env_value_as_off() -> None:
    """env 에 값만 비운 줄(`CLOVER_LEDGER_PAUSED=`)이 남아도 기동하고 꺼진 것으로 읽는다(정수·불리언 파싱은 빈 값에서 실패한다)."""
    from api.core.config import Settings

    assert Settings(clover_ledger_paused="").clover_ledger_paused is False  # type: ignore[arg-type]
    assert Settings(clover_ledger_paused="true").clover_ledger_paused is True  # type: ignore[arg-type]
