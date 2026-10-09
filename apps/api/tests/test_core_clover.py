import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import anyio
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.core import clover
from api.core.clover import (
    CHAT_TURN_COST,
    CHAT_TURN_COST_OPUS,
    CHAT_TURN_COST_SONNET,
    IMAGE_UNIT_COST,
    NOVELIZE_AI_EDIT_COST,
    NOVELIZE_EPISODE_COST,
    NOVELIZE_EPISODE_COST_OPUS,
    NOVELIZE_EPISODE_COST_SONNET,
    PURCHASE_LOT_KINDS,
    CloverRefundExceedsSpendError,
    earned_lot_expiry,
    grant,
    is_same_kst_day,
    kst_today,
    refund_spend,
    refund_spend_in_new_transaction,
    restore_purchase_lots,
    revoke,
    revoke_purchase_lots,
    spend,
)
from api.core.rate_limit_gate import CHAT_DAILY_LIMIT
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot, CloverSpendAllocation, CloverSpendRefund
from factories import _make_payment, _make_user, _make_user_with_clover_lot


async def _ledger_rows(db: AsyncSession, user_id: uuid.UUID) -> list[CloverLedger]:
    return list(
        (
            await db.scalars(
                select(CloverLedger)
                .where(CloverLedger.user_id == user_id)
                # `created_at`의 server_default(`func.now()`)는 Postgres에서 트랜잭션 시작
                # 시각이라 한 트랜잭션에 쌓인 행들이 전부 동률이다. tiebreaker가 없으면 정렬이
                # 비결정적이 된다(`7109dac`가 고친 것과 같은 원인). 선례는
                # `admin/image_generations.py:51`.
                # ⚠️ `id`는 uuid4라 이 정렬은 "결정적"일 뿐 "삽입 순서"가 아니다 — 여러 행을
                # 단언하는 테스트는 순서가 아니라 내용으로 비교해야 한다.
                .order_by(CloverLedger.created_at, CloverLedger.id)
            )
        ).all()
    )


async def _balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


# ── 차감 ────────────────────────────────────────────────────────────────────
async def test_spend_deducts_balance_and_writes_one_ledger_row(db_session: AsyncSession) -> None:
    # `spend()`가 이제 로트를 잠가 깎으므로 셋업이 매칭되는
    # 로트도 만들어야 한다 — `_make_user(clover_balance=N)`만으로는 로트가 0행이라
    # 부족 예외(`CloverLotShortfallError`)가 난다.
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)

    spent = await spend(db_session, user_id=user.id, amount=CHAT_TURN_COST, kind="chat_spend")

    assert spent is not None and spent.balance_after == 90
    assert await _balance(db_session, user.id) == 90

    rows = await _ledger_rows(db_session, user.id)
    assert len(rows) == 1
    # 환급이 이 id 로 배분을 찾는다 — 다른 행을 가리키면 엉뚱한 차감을 되돌린다.
    assert spent.ledger_id == rows[0].id
    # 부호 있는 증감이라 소모는 음수다(`db/models/clover.py`의 `amount` 주석).
    assert rows[0].amount == -CHAT_TURN_COST
    assert rows[0].kind == "chat_spend"
    # `balance_after`가 잔액 컬럼과 어긋나면 원장만 보고는 잔액을 설명할 수 없게 된다.
    assert rows[0].balance_after == 90


# ── 잔액 부족 ───────────────────────────────────────────────────────────────
async def test_spend_returns_none_and_changes_nothing_when_insufficient(
    db_session: AsyncSession,
) -> None:
    user = _make_user(clover_balance=9)
    db_session.add(user)
    await db_session.flush()

    assert await spend(db_session, user_id=user.id, amount=CHAT_TURN_COST, kind="chat_spend") is None

    # 조건부 UPDATE가 막았으므로 잔액도 원장도 그대로여야 한다 — 원장에 실패 기록을 남기지 않는다.
    assert await _balance(db_session, user.id) == 9
    assert await _ledger_rows(db_session, user.id) == []


async def test_spend_exact_balance_succeeds_and_leaves_zero(db_session: AsyncSession) -> None:
    # 경계값: `>=`가 아니라 `>`로 쓰면 여기서 깨진다.
    user = await _make_user_with_clover_lot(db_session, clover_balance=CHAT_TURN_COST)

    spent = await spend(db_session, user_id=user.id, amount=CHAT_TURN_COST, kind="chat_spend")
    assert spent is not None and spent.balance_after == 0
    assert await _balance(db_session, user.id) == 0


async def test_spend_twice_cannot_overdraw(db_session: AsyncSession) -> None:
    """조건부 UPDATE의 존재 이유 — 두 번째 차감이 잔액을 넘기면 통과하지 못한다.

    `WHERE clover_balance >= :amount`를 빼면 두 번째가 -5를 만들며 통과한다(CHECK 제약이
    있어 실제로는 `IntegrityError`가 되지만, 어느 쪽이든 이 테스트는 깨진다).
    """
    user = await _make_user_with_clover_lot(db_session, clover_balance=15)

    first = await spend(db_session, user_id=user.id, amount=10, kind="chat_spend")
    assert first is not None and first.balance_after == 5
    assert await spend(db_session, user_id=user.id, amount=10, kind="chat_spend") is None

    assert await _balance(db_session, user.id) == 5
    assert len(await _ledger_rows(db_session, user.id)) == 1


# ── CHECK 제약 ──────────────────────────────────────────────────────────────
async def test_check_constraint_rejects_negative_balance(db_session: AsyncSession) -> None:
    """`alembic check`가 CHECK 제약을 비교하지 않으므로
    (alembic 1.18.5, `db/models/story.py:190-196`) **이 행위 테스트가 유일한 검증**이다.
    조건부 UPDATE를 우회하는 경로(어드민 직접 수정·수동 SQL·환불 버그)를 여기서 막는다.
    """
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(update(User).where(User.id == user.id).values(clover_balance=-1))
        await db_session.flush()


# ── grant / revoke ──────────────────────────────────────────────────────────
async def test_grant_increases_balance_and_writes_ledger(db_session: AsyncSession) -> None:
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()

    assert await grant(db_session, user_id=user.id, amount=100, kind="attendance_grant") == 100

    rows = await _ledger_rows(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].amount == 100
    assert rows[0].balance_after == 100
    assert rows[0].idempotency_key is None


async def test_revoke_returns_none_when_amount_exceeds_balance(db_session: AsyncSession) -> None:
    # 회수는 음수로 내려가지 않는다 — 라우트가 이 `None`을 422로 번역한다.
    user = _make_user(clover_balance=30)
    db_session.add(user)
    await db_session.flush()

    assert await revoke(db_session, user_id=user.id, amount=31) is None
    assert await _balance(db_session, user.id) == 30
    assert await _ledger_rows(db_session, user.id) == []


async def test_revoke_writes_admin_revoke_kind(db_session: AsyncSession) -> None:
    # `revoke()`도 `_apply()`를 공유해 로트를 잠가 깎는다 — 셋업이 매칭 로트를 필요로 한다.
    user = await _make_user_with_clover_lot(db_session, clover_balance=30)

    assert await revoke(db_session, user_id=user.id, amount=30, idempotency_key="key-1") == 0

    rows = await _ledger_rows(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].kind == "admin_revoke"
    assert rows[0].amount == -30
    assert rows[0].idempotency_key == "key-1"


# ── grant()가 매칭되는 로트를 만든다 ───────────────────────────────────
async def test_grant_creates_a_matching_lot(db_session: AsyncSession) -> None:
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()
    expires_at = datetime(2026, 9, 28, tzinfo=UTC)

    balance = await grant(
        db_session,
        user_id=user.id,
        amount=100,
        kind="attendance_grant",
        expires_at=expires_at,
    )
    assert balance == 100

    lots = (await db_session.scalars(select(CloverLot).where(CloverLot.user_id == user.id))).all()
    assert len(lots) == 1
    assert lots[0].granted_amount == 100
    assert lots[0].remaining == 100
    assert lots[0].expires_at == expires_at
    assert lots[0].kind == "attendance_grant"


async def test_grant_defaults_to_a_permanent_lot(db_session: AsyncSession) -> None:
    """`expires_at`을 안 주면(어드민 지급·환불) 무기한
    로트가 생긴다."""
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()

    await grant(db_session, user_id=user.id, amount=50, kind="admin_grant")

    lot = await db_session.scalar(select(CloverLot).where(CloverLot.user_id == user.id))
    assert lot is not None
    assert lot.expires_at is None


# ── 로트 소진 순서와 경계 ──────────────────────────────────────────
async def test_spend_consumes_the_soonest_expiring_lot_first(db_session: AsyncSession) -> None:
    """소진 순서는 만료 임박 우선. 깨지는 시나리오: 순서를 어기면 무기한 로트가 먼저
    깎여 유저가 만료로 잃는 양이 늘어난다."""
    user = _make_user(clover_balance=50)
    db_session.add(user)
    await db_session.flush()
    expiring_soon = CloverLot(
        user_id=user.id,
        granted_amount=20,
        remaining=20,
        kind="attendance_grant",
        expires_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    permanent = CloverLot(
        user_id=user.id, granted_amount=30, remaining=30, kind="admin_grant", expires_at=None
    )
    db_session.add_all([expiring_soon, permanent])
    await db_session.flush()

    spent = await spend(db_session, user_id=user.id, amount=15, kind="chat_spend")
    assert spent is not None and spent.balance_after == 35

    await db_session.refresh(expiring_soon)
    await db_session.refresh(permanent)
    assert expiring_soon.remaining == 5
    assert permanent.remaining == 30  # 무기한 로트는 안 건드렸다


async def test_spend_crosses_a_lot_boundary(db_session: AsyncSession) -> None:
    """로트 경계를 걸친 차감(로트 A 3개 남음 + 로트 B로 7개 더 필요, 총 10 차감).
    깨지는 시나리오: 단일 로트만 보는 구현이면 부족한데도 성공 처리되거나 잔액이 어긋난다."""
    user = _make_user(clover_balance=10)
    db_session.add(user)
    await db_session.flush()
    first = CloverLot(
        user_id=user.id,
        granted_amount=3,
        remaining=3,
        kind="attendance_grant",
        expires_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    second = CloverLot(
        user_id=user.id, granted_amount=7, remaining=7, kind="admin_grant", expires_at=None
    )
    db_session.add_all([first, second])
    await db_session.flush()

    spent = await spend(db_session, user_id=user.id, amount=10, kind="chat_spend")
    assert spent is not None and spent.balance_after == 0

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.remaining == 0
    assert second.remaining == 0


# ── 회수는 최근 지급분부터, 차감과 정반대 ─────────────────────────
async def test_revoke_consumes_the_most_recent_lot_first(db_session: AsyncSession) -> None:
    """깨지는 시나리오: 차감과 같은 정렬을 타면 오지급분이 아니라 만료 임박분이 먼저 사라진다."""
    user = _make_user(clover_balance=80)
    db_session.add(user)
    await db_session.flush()
    older = CloverLot(
        user_id=user.id,
        granted_amount=50,
        remaining=50,
        kind="admin_grant",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    newer = CloverLot(
        user_id=user.id,
        granted_amount=30,
        remaining=30,
        kind="admin_grant",
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    db_session.add_all([older, newer])
    await db_session.flush()

    assert await revoke(db_session, user_id=user.id, amount=30) == 50

    await db_session.refresh(older)
    await db_session.refresh(newer)
    assert newer.remaining == 0  # 최근 지급분이 먼저 깎였다
    assert older.remaining == 50  # 오래된 로트는 그대로


# ── 차감 등급: 무료 → 보너스 → 유료 ─────────────────────────────────────────
async def _user_with_lots(db: AsyncSession, *lots: tuple[str, int, datetime | None]) -> tuple[User, list[CloverLot]]:
    """`(kind, amount, expires_at)` 로트들과 그 합을 잔액으로 갖는 사용자를 만든다. 구매 로트는 결제 하나를 가리킨다
    (로트 CHECK — 한 결제에 유료·보너스 로트가 하나씩이라 kind 마다 하나까지만 받는다)."""
    user = _make_user(clover_balance=sum(amount for _, amount, _ in lots))
    db.add(user)
    await db.flush()
    payment_id = None
    if any(kind in PURCHASE_LOT_KINDS for kind, _, _ in lots):
        payment_id = (await _make_payment(db, user_id=user.id, status="paid")).id
    rows = [
        CloverLot(
            user_id=user.id,
            granted_amount=amount,
            remaining=amount,
            kind=kind,
            expires_at=expires_at,
            payment_id=payment_id if kind in PURCHASE_LOT_KINDS else None,
        )
        for kind, amount, expires_at in lots
    ]
    db.add_all(rows)
    await db.flush()
    return user, rows


async def _allocations(db: AsyncSession, ledger_id: uuid.UUID) -> list[CloverSpendAllocation]:
    return list(
        (
            await db.scalars(
                select(CloverSpendAllocation)
                .where(CloverSpendAllocation.spend_ledger_id == ledger_id)
                .order_by(CloverSpendAllocation.seq)
            )
        ).all()
    )


async def test_spend_uses_free_then_bonus_then_paid_and_records_allocations(db_session: AsyncSession) -> None:
    """유료·보너스 로트가 무료보다 먼저 만료돼도 무료를 다 쓴 뒤에야 보너스, 그다음 유료를 쓴다. 깨지는 시나리오:
    만료 순서만 보면 가장 먼저 만료되는 유료 로트를 먼저 깎아, 환불할 남은 유료 수량이 줄어든다."""
    user, (paid, bonus, free_soon, free_late, free_permanent) = await _user_with_lots(
        db_session,
        ("purchase_paid", 10, datetime(2026, 10, 9, tzinfo=UTC)),
        ("purchase_bonus", 10, datetime(2026, 10, 10, tzinfo=UTC)),
        ("attendance_grant", 10, datetime(2026, 10, 12, tzinfo=UTC)),
        ("mission_grant", 10, datetime(2026, 10, 20, tzinfo=UTC)),
        ("admin_grant", 10, None),
    )

    spent = await spend(db_session, user_id=user.id, amount=35, kind="chat_spend")

    assert spent is not None and spent.balance_after == 15
    for lot in (paid, bonus, free_soon, free_late, free_permanent):
        await db_session.refresh(lot)
    assert [free_soon.remaining, free_late.remaining, free_permanent.remaining] == [0, 0, 0]
    assert bonus.remaining == 5
    assert paid.remaining == 10
    allocations = await _allocations(db_session, spent.ledger_id)
    assert [(a.lot_id, a.seq, a.amount) for a in allocations] == [
        (free_soon.id, 0, 10),
        (free_late.id, 1, 10),
        (free_permanent.id, 2, 10),
        (bonus.id, 3, 5),
    ]
    assert sum(a.amount for a in allocations) == 35


# ── 환급: 깎은 로트로 역순, 탈퇴 건너뜀, id 없음 폴백 ──────────────────────────
async def test_partial_refund_returns_paid_before_bonus_before_free(db_session: AsyncSession) -> None:
    """부분 환급은 깎은 역순이라 유료부터 돌아간다. 깨지는 시나리오: 정순으로 돌리면 못 받은 서비스 몫이 무료
    로트로 돌아가고 현금으로 산 유료는 쓴 채로 남는다."""
    user, (free, bonus, paid) = await _user_with_lots(
        db_session,
        ("attendance_grant", 10, datetime(2026, 10, 12, tzinfo=UTC)),
        ("purchase_bonus", 10, None),
        ("purchase_paid", 10, None),
    )
    spent = await spend(db_session, user_id=user.id, amount=25, kind="image_spend")
    assert spent is not None

    balance = await refund_spend(
        db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=8, kind="image_refund"
    )

    assert balance == 13
    for lot in (free, bonus, paid):
        await db_session.refresh(lot)
    assert (free.remaining, bonus.remaining, paid.remaining) == (0, 3, 10)
    # 깎은 로트로 되돌렸으므로 새 로트가 생기지 않는다.
    lots = (await db_session.scalars(select(CloverLot).where(CloverLot.user_id == user.id))).all()
    assert len(lots) == 3
    assert [a.refunded_amount for a in await _allocations(db_session, spent.ledger_id)] == [0, 3, 5]
    rows = await _ledger_rows(db_session, user.id)
    assert [(r.kind, r.amount, r.balance_after) for r in rows if r.kind == "image_refund"] == [
        ("image_refund", 8, 13)
    ]
    assert await _balance(db_session, user.id) == 13


async def _refund_events(db: AsyncSession, spend_ledger_id: uuid.UUID) -> list[CloverSpendRefund]:
    return list(
        (
            await db.scalars(
                select(CloverSpendRefund)
                .join(CloverSpendAllocation, CloverSpendAllocation.id == CloverSpendRefund.allocation_id)
                .where(CloverSpendAllocation.spend_ledger_id == spend_ledger_id)
            )
        ).all()
    )


async def test_partial_refunds_leave_one_event_per_returned_allocation(db_session: AsyncSession) -> None:
    """부분 환급 두 번이 배분마다 돌려준 몫을 그 환급의 원장 행과 함께 남기고, 배분별 합이 `refunded_amount` 와 같다.
    정산은 이 행의 시각으로 환급을 그 달에 빼므로, 몫이 틀리면 크리에이터 몫이 틀린다. 두 번째 환급은 첫 환급이 다
    돌려준 유료 배분을 지나는데(돌려줄 양 0) 그 배분에는 행을 남기지 않는다 — 남기면 0 행이 CHECK 에 걸려 환급 전체가
    실패한다."""
    user, (free, bonus, paid) = await _user_with_lots(
        db_session,
        ("attendance_grant", 10, datetime(2026, 10, 12, tzinfo=UTC)),
        ("purchase_bonus", 10, None),
        ("purchase_paid", 10, None),
    )
    spent = await spend(db_session, user_id=user.id, amount=25, kind="chat_spend")
    assert spent is not None

    await refund_spend(db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=8, kind="chat_refund")
    await refund_spend(db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=4, kind="chat_refund")

    allocations = {a.lot_id: a for a in await _allocations(db_session, spent.ledger_id)}
    # 원장 정렬은 삽입 순서가 아니라서 두 환급의 원장 행을 금액으로 가른다.
    refund_ledgers = {r.amount: r.id for r in await _ledger_rows(db_session, user.id) if r.kind == "chat_refund"}
    first, second = refund_ledgers[8], refund_ledgers[4]
    events = await _refund_events(db_session, spent.ledger_id)
    assert sorted((e.allocation_id, e.refund_ledger_id, e.amount) for e in events) == sorted(
        [
            (allocations[paid.id].id, first, 5),
            (allocations[bonus.id].id, first, 3),
            (allocations[bonus.id].id, second, 4),
        ]
    )
    for allocation in allocations.values():
        assert sum(e.amount for e in events if e.allocation_id == allocation.id) == allocation.refunded_amount
    assert allocations[free.id].refunded_amount == 0


async def test_refund_skips_allocations_from_lots_the_caller_excludes(db_session: AsyncSession) -> None:
    """`skip_lot` 에 맞는 로트(여기선 보너스)에서 나간 몫은 돌려주지 않고 건너뛴다 — 그 몫은 채울 대상이 아니라 전액(25)을
    청해도 부족 예외 없이 나머지(유료 5 + 무료 10)만 돌아가고, 잔액·원장·환급 행 모두 15 다. 건너뛴 배분은 그대로다."""
    user, (free, bonus, paid) = await _user_with_lots(
        db_session,
        ("attendance_grant", 10, datetime(2026, 10, 12, tzinfo=UTC)),
        ("purchase_bonus", 10, None),
        ("purchase_paid", 10, None),
    )
    spent = await spend(db_session, user_id=user.id, amount=25, kind="novel_read_spend")
    assert spent is not None

    balance = await refund_spend(
        db_session,
        user_id=user.id,
        spend_ledger_id=spent.ledger_id,
        amount=25,
        kind="novel_read_refund",
        skip_lot=CloverLot.kind == "purchase_bonus",
    )

    assert balance == 20 == await _balance(db_session, user.id)
    for lot in (free, bonus, paid):
        await db_session.refresh(lot)
    assert (free.remaining, bonus.remaining, paid.remaining) == (10, 0, 10)
    assert [a.refunded_amount for a in await _allocations(db_session, spent.ledger_id)] == [10, 0, 5]
    rows = await _ledger_rows(db_session, user.id)
    assert [(r.amount, r.balance_after) for r in rows if r.kind == "novel_read_refund"] == [(15, 20)]
    assert sorted(e.amount for e in await _refund_events(db_session, spent.ledger_id)) == [5, 10]


async def test_refund_beyond_the_unrefunded_spend_raises(db_session: AsyncSession) -> None:
    """같은 차감을 두 번 환급하면 두 번째가 남은 환급 가능량을 넘어 예외로 롤백된다(이중 환급 방지)."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=50)
    spent = await spend(db_session, user_id=user.id, amount=30, kind="novelize_spend")
    assert spent is not None
    await refund_spend(db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=30, kind="novelize_refund")

    with pytest.raises(CloverRefundExceedsSpendError):
        await refund_spend(
            db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=1, kind="novelize_refund"
        )


async def test_refund_to_a_withdrawn_user_changes_nothing(db_session: AsyncSession) -> None:
    """탈퇴로 잔액·로트가 소멸된 뒤 늦게 도착한 환급은 적용하지 않는다. 깨지는 시나리오: 탈퇴 회원에게 지울 수 없는
    잔액이 되살아난다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=50)
    spent = await spend(db_session, user_id=user.id, amount=30, kind="chat_spend")
    assert spent is not None
    await db_session.execute(update(User).where(User.id == user.id).values(deleted_at=datetime.now(UTC)))
    ledger_before = len(await _ledger_rows(db_session, user.id))

    result = await refund_spend(
        db_session, user_id=user.id, spend_ledger_id=spent.ledger_id, amount=30, kind="chat_refund"
    )

    assert result is None
    assert await _balance(db_session, user.id) == 20
    assert len(await _ledger_rows(db_session, user.id)) == ledger_before
    assert [a.refunded_amount for a in await _allocations(db_session, spent.ledger_id)] == [0]
    assert await _refund_events(db_session, spent.ledger_id) == []


async def test_refund_without_a_spend_id_grants_a_permanent_lot(db_session: AsyncSession) -> None:
    """배분을 남기기 전의 차감(차감 id 없음)은 예전처럼 무기한 새 로트로 돌려준다."""
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()

    assert await refund_spend(db_session, user_id=user.id, spend_ledger_id=None, amount=40, kind="novelize_refund") == 40

    lot = await db_session.scalar(select(CloverLot).where(CloverLot.user_id == user.id))
    assert lot is not None
    assert (lot.kind, lot.remaining, lot.expires_at) == ("novelize_refund", 40, None)
    # 돌려줄 배분이 없으므로 환급 행도 없다.
    refund_ledger_ids = [r.id for r in await _ledger_rows(db_session, user.id)]
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CloverSpendRefund)
            .where(CloverSpendRefund.refund_ledger_id.in_(refund_ledger_ids))
        )
        == 0
    )


# ── 어드민 회수는 무료 로트만 ───────────────────────────────────────────────
async def test_revoke_skips_purchase_lots(db_session: AsyncSession) -> None:
    """회수는 최근 지급분부터지만 구매 로트는 건너뛴다. 깨지는 시나리오: 가장 최근 로트인 유료분을 깎아 결제 기록 밖에서
    남은 유료 수량이 준다."""
    user = _make_user(clover_balance=40)
    db_session.add(user)
    await db_session.flush()
    free = CloverLot(
        user_id=user.id, granted_amount=10, remaining=10, kind="admin_grant", created_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    paid = CloverLot(
        user_id=user.id,
        granted_amount=30,
        remaining=30,
        kind="purchase_paid",
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
        payment_id=(await _make_payment(db_session, user_id=user.id, status="paid")).id,
    )
    db_session.add_all([free, paid])
    await db_session.flush()

    assert await revoke(db_session, user_id=user.id, amount=10) == 30

    await db_session.refresh(free)
    await db_session.refresh(paid)
    assert (free.remaining, paid.remaining) == (0, 30)
    # 회수는 환급 대상이 아니라 배분을 남기지 않는다.
    allocations = await db_session.scalars(
        select(CloverSpendAllocation).where(CloverSpendAllocation.lot_id.in_([free.id, paid.id]))
    )
    assert allocations.all() == []


async def test_revoke_returns_none_when_free_lots_are_short_even_if_balance_suffices(
    db_session: AsyncSession,
) -> None:
    """잔액은 넉넉해도 무료 로트 합이 모자라면 `None`(라우트 422). 깨지는 시나리오: 총액만 보면 통과한 뒤 로트가
    모자라 500 이 난다."""
    user, (free, paid) = await _user_with_lots(
        db_session, ("admin_grant", 5, None), ("purchase_paid", 30, None)
    )

    assert await revoke(db_session, user_id=user.id, amount=10) is None

    await db_session.refresh(free)
    await db_session.refresh(paid)
    assert (free.remaining, paid.remaining) == (5, 30)
    assert await _balance(db_session, user.id) == 35
    assert await _ledger_rows(db_session, user.id) == []


# ── 구매 로트 회수·복원 ─────────────────────────────────────────────────
async def _user_with_purchase(db: AsyncSession) -> tuple[User, uuid.UUID, uuid.UUID]:
    """무료 50 + 결제 A(유료 100·보너스 10) + 결제 B(유료 30). 결제 A 의 id 와 B 의 id 를 돌려준다."""
    user = await _make_user_with_clover_lot(db, clover_balance=50)
    payment_a = await _make_payment(db, user_id=user.id, status="paid")
    payment_b = await _make_payment(db, user_id=user.id, status="paid")
    await grant(db, user_id=user.id, amount=100, kind="purchase_paid", payment_id=payment_a.id)
    await grant(db, user_id=user.id, amount=10, kind="purchase_bonus", payment_id=payment_a.id)
    await grant(db, user_id=user.id, amount=30, kind="purchase_paid", payment_id=payment_b.id)
    return user, payment_a.id, payment_b.id


async def _lots_by_payment(db: AsyncSession, user_id: uuid.UUID) -> dict[tuple[uuid.UUID | None, str], int]:
    rows = (await db.scalars(select(CloverLot).where(CloverLot.user_id == user_id))).all()
    for row in rows:
        await db.refresh(row)
    return {(row.payment_id, row.kind): row.remaining for row in rows}


async def test_purchase_grant_makes_lots_that_point_to_the_payment(db_session: AsyncSession) -> None:
    """환불이 그 구매의 로트를 집으려면 로트가 결제를 가리켜야 한다. 깨지는 시나리오: 결제 참조를 로트에 싣지 않아 구매
    지급이 로트 CHECK 에 걸리거나, 환불이 회수할 로트를 찾지 못한다."""
    user, payment_a, payment_b = await _user_with_purchase(db_session)

    assert await _lots_by_payment(db_session, user.id) == {
        (None, "legacy_balance"): 50,
        (payment_a, "purchase_paid"): 100,
        (payment_a, "purchase_bonus"): 10,
        (payment_b, "purchase_paid"): 30,
    }
    assert await _balance(db_session, user.id) == 190


async def test_revoke_purchase_lots_takes_only_what_is_left_of_that_payment(db_session: AsyncSession) -> None:
    """회수는 그 결제의 남은 유료·보너스만 가져간다. 깨지는 시나리오: 다른 결제나 무료 로트까지 깎거나, 이미 쓴 양까지
    회수하려다 잔액이 음수가 된다."""
    user, payment_a, payment_b = await _user_with_purchase(db_session)
    # 무료 50 → 보너스 6 순으로 쓴다(유료는 그대로).
    assert await spend(db_session, user_id=user.id, amount=56, kind="chat_spend") is not None

    assert await revoke_purchase_lots(db_session, payment_id=payment_a) == (100, 4)

    assert await _lots_by_payment(db_session, user.id) == {
        (None, "legacy_balance"): 0,
        (payment_a, "purchase_paid"): 0,
        (payment_a, "purchase_bonus"): 0,
        (payment_b, "purchase_paid"): 30,
    }
    assert await _balance(db_session, user.id) == 30
    rows = await _ledger_rows(db_session, user.id)
    assert [(r.kind, r.amount, r.balance_after) for r in rows if r.kind == "purchase_revoke"] == [
        ("purchase_revoke", -104, 30)
    ]


async def test_revoke_purchase_lots_with_nothing_left_writes_nothing(db_session: AsyncSession) -> None:
    user, payment_a, _ = await _user_with_purchase(db_session)
    await revoke_purchase_lots(db_session, payment_id=payment_a)
    ledger_before = len(await _ledger_rows(db_session, user.id))

    assert await revoke_purchase_lots(db_session, payment_id=payment_a) == (0, 0)

    assert len(await _ledger_rows(db_session, user.id)) == ledger_before


async def test_restore_purchase_lots_puts_the_clawback_back(db_session: AsyncSession) -> None:
    """포트원이 환불을 거절하면 회수분을 그 결제의 로트로 되돌린다. 깨지는 시나리오: 돈은 돌려받지 못했는데 클로버도 없는
    채로 남는다."""
    user, payment_a, payment_b = await _user_with_purchase(db_session)
    paid, bonus = await revoke_purchase_lots(db_session, payment_id=payment_a)

    assert await restore_purchase_lots(db_session, payment_id=payment_a, paid=paid, bonus=bonus) == 190

    assert await _lots_by_payment(db_session, user.id) == {
        (None, "legacy_balance"): 50,
        (payment_a, "purchase_paid"): 100,
        (payment_a, "purchase_bonus"): 10,
        (payment_b, "purchase_paid"): 30,
    }
    rows = await _ledger_rows(db_session, user.id)
    assert [(r.kind, r.amount, r.balance_after) for r in rows if r.kind == "purchase_restore"] == [
        ("purchase_restore", 110, 190)
    ]


async def test_restore_purchase_lots_to_a_withdrawn_user_changes_nothing(db_session: AsyncSession) -> None:
    """탈퇴가 소멸시킨 잔액을 늦게 도착한 복원이 되살리지 않는다(환급과 같은 규칙)."""
    user, payment_a, _ = await _user_with_purchase(db_session)
    paid, bonus = await revoke_purchase_lots(db_session, payment_id=payment_a)
    await db_session.execute(update(User).where(User.id == user.id).values(deleted_at=datetime.now(UTC)))
    ledger_before = len(await _ledger_rows(db_session, user.id))

    assert await restore_purchase_lots(db_session, payment_id=payment_a, paid=paid, bonus=bonus) is None

    assert await _balance(db_session, user.id) == 80
    assert len(await _ledger_rows(db_session, user.id)) == ledger_before


async def test_refund_spend_in_new_transaction_swallows_failures() -> None:
    """환급 래퍼는 SSE 본문·실패 정리에서 불린다 — 예외가 새면 스트림이 깨지고 망가진 커넥션이 풀로 돌아간다."""
    dead_engine = create_async_engine("postgresql+asyncpg://invalid:invalid@127.0.0.1:1/nonexistent")
    dead_factory = async_sessionmaker(dead_engine, expire_on_commit=False)
    try:
        await refund_spend_in_new_transaction(
            dead_factory, user_id=uuid.uuid4(), spend_ledger_id=uuid.uuid4(), amount=CHAT_TURN_COST, kind="chat_refund"
        )
    finally:
        await dead_engine.dispose()


async def test_refund_spend_in_new_transaction_finishes_inside_a_cancelled_scope(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 기준: 끊긴 SSE 요청의 정리처럼 이미 취소된 범위에서 불려도 환급이 `await` 다섯 번을 거쳐 끝까지 가고, 그 뒤
    호출자의 취소는 그대로 이어진다(래퍼 다음 줄에 닿지 않는다). 차폐가 없으면 환급이 첫 `await` 에서 다시 취소된다."""
    started = asyncio.Event()
    refunded: list[int] = []
    reached_after: list[bool] = []

    async def _slow_refund_spend(db: AsyncSession, **kwargs: Any) -> int:
        started.set()
        for _ in range(5):
            await asyncio.sleep(0)
        refunded.append(kwargs["amount"])
        return 0

    monkeypatch.setattr(clover, "refund_spend", _slow_refund_spend)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    async def _caller() -> None:
        await refund_spend_in_new_transaction(
            factory, user_id=uuid.uuid4(), spend_ledger_id=uuid.uuid4(), amount=CHAT_TURN_COST, kind="chat_refund"
        )
        await asyncio.sleep(1)
        reached_after.append(True)

    async with asyncio.timeout(5):
        async with anyio.create_task_group() as group:
            group.start_soon(_caller)
            await started.wait()
            group.cancel_scope.cancel()

    assert refunded == [CHAT_TURN_COST]
    assert reached_after == []


# ── KST 순수 함수 ──────────────────────────────────────────────────────
def test_kst_today_uses_fixed_plus_nine_offset() -> None:
    # 구현의 KST 상수를 빌려 쓰지 않는다 — 여기서 오프셋을 직접 만들어야 오프셋이 틀렸을 때 깨진다
    # (`tests/test_core_rate_limit.py`의 같은 관례).
    kst = timezone(timedelta(hours=9))

    assert kst_today(datetime(2026, 9, 17, 0, 0, tzinfo=kst)) == date(2026, 9, 17)
    assert kst_today(datetime(2026, 9, 17, 23, 59, tzinfo=kst)) == date(2026, 9, 17)
    # UTC 15:00 == KST 익일 00:00 — 날짜가 넘어간다.
    assert kst_today(datetime(2026, 9, 17, 15, 0, tzinfo=UTC)) == date(2026, 9, 18)
    assert kst_today(datetime(2026, 9, 17, 14, 59, tzinfo=UTC)) == date(2026, 9, 17)


def test_kst_today_rejects_naive_datetime() -> None:
    # `seconds_until_kst_midnight`와 같은 이유 — naive를 받아주면 `astimezone`이 프로세스 로컬
    # 시간으로 재해석해 같은 입력이 컨테이너 TZ마다 다른 날짜를 낸다.
    with pytest.raises(ValueError, match="tz-aware"):
        kst_today(datetime(2026, 9, 17, 12, 0))


def test_is_same_kst_day_boundary() -> None:
    kst = timezone(timedelta(hours=9))
    now = datetime(2026, 9, 17, 12, 0, tzinfo=kst)

    assert is_same_kst_day(date(2026, 9, 17), now) is True
    assert is_same_kst_day(date(2026, 9, 16), now) is False
    # 한 번도 확인한 적 없는 유저 — 차감 확인 판정의 첫 호출이 여기로 온다.
    assert is_same_kst_day(None, now) is False


def test_is_same_kst_day_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        is_same_kst_day(date(2026, 9, 17), datetime(2026, 9, 17, 12, 0))


# ── earned_lot_expiry(미션 지급용) ───────────────────────────
def test_earned_lot_expiry_is_kst_midnight_plus_eight_days() -> None:
    """마이그레이션의 `_legacy_lot_expiry` 테스트와 같은 예시 — 지급일이 2026-09-21(KST)이면
    2026-09-29 00:00 KST가 나와야 한다."""
    kst = timezone(timedelta(hours=9))
    now = datetime(2026, 9, 21, 0, 0, tzinfo=kst)

    assert earned_lot_expiry(now) == datetime(2026, 9, 29, 0, 0, tzinfo=kst)


def test_earned_lot_expiry_guarantees_at_least_seven_days_even_at_end_of_day() -> None:
    """"+8일"의 존재 이유: 그 날 23:59(KST)에 지급돼도 보유 기간이 7일 이상이어야 한다.
    "+7일"로 되돌리면 자정 정규화 때문에 보유 기간이 6일대로 떨어져 이 단언이 깨진다."""
    kst = timezone(timedelta(hours=9))
    now = datetime(2026, 9, 21, 23, 59, tzinfo=kst)

    assert earned_lot_expiry(now) - now >= timedelta(days=7)


def test_earned_lot_expiry_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        earned_lot_expiry(datetime(2026, 9, 21, 0, 0))


# ── 정책 상수 ────────────────────────────────────────────────────────────────
def test_policy_constants_match_decisions() -> None:
    # 값이 조용히 바뀌면 원장에 쌓인 과거 수치의 의미가
    # 달라지므로 정한 값을 여기서 고정한다.
    assert CHAT_TURN_COST == 10
    assert IMAGE_UNIT_COST == 30
    assert NOVELIZE_EPISODE_COST == 80
    assert NOVELIZE_AI_EDIT_COST == 30
    assert CHAT_TURN_COST_SONNET == 60
    assert CHAT_TURN_COST_OPUS == 110
    assert NOVELIZE_EPISODE_COST_SONNET == 180
    assert NOVELIZE_EPISODE_COST_OPUS == 300
    assert CHAT_DAILY_LIMIT == 15


async def test_ledger_table_is_reachable(db_session: AsyncSession) -> None:
    # 마이그레이션이 실제로 적용됐는지(= `alembic upgrade head`가 돌았는지) 한 줄로 확인한다.
    assert await db_session.scalar(text("SELECT COUNT(*) FROM clover_ledger")) == 0
