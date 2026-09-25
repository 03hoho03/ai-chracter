import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.core.clover import (
    ATTENDANCE_GRANT_AMOUNT,
    CHAT_TURN_COST,
    IMAGE_UNIT_COST,
    earned_lot_expiry,
    grant,
    is_same_kst_day,
    kst_today,
    refund_in_new_transaction,
    revoke,
    spend,
)
from api.db.models.auth import User
from api.db.models.clover import CloverLedger, CloverLot
from factories import _make_user, _make_user_with_clover_lot


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

    remaining = await spend(db_session, user_id=user.id, amount=CHAT_TURN_COST, kind="chat_spend")

    assert remaining == 90
    assert await _balance(db_session, user.id) == 90

    rows = await _ledger_rows(db_session, user.id)
    assert len(rows) == 1
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

    assert await spend(db_session, user_id=user.id, amount=CHAT_TURN_COST, kind="chat_spend") == 0
    assert await _balance(db_session, user.id) == 0


async def test_spend_twice_cannot_overdraw(db_session: AsyncSession) -> None:
    """조건부 UPDATE의 존재 이유 — 두 번째 차감이 잔액을 넘기면 통과하지 못한다.

    `WHERE clover_balance >= :amount`를 빼면 두 번째가 -5를 만들며 통과한다(CHECK 제약이
    있어 실제로는 `IntegrityError`가 되지만, 어느 쪽이든 이 테스트는 깨진다).
    """
    user = await _make_user_with_clover_lot(db_session, clover_balance=15)

    assert await spend(db_session, user_id=user.id, amount=10, kind="chat_spend") == 5
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

    assert (
        await grant(
            db_session, user_id=user.id, amount=ATTENDANCE_GRANT_AMOUNT, kind="attendance_grant"
        )
        == ATTENDANCE_GRANT_AMOUNT
    )

    rows = await _ledger_rows(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].amount == ATTENDANCE_GRANT_AMOUNT
    assert rows[0].balance_after == ATTENDANCE_GRANT_AMOUNT
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
        amount=ATTENDANCE_GRANT_AMOUNT,
        kind="attendance_grant",
        expires_at=expires_at,
    )
    assert balance == ATTENDANCE_GRANT_AMOUNT

    lots = (await db_session.scalars(select(CloverLot).where(CloverLot.user_id == user.id))).all()
    assert len(lots) == 1
    assert lots[0].granted_amount == ATTENDANCE_GRANT_AMOUNT
    assert lots[0].remaining == ATTENDANCE_GRANT_AMOUNT
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

    assert await spend(db_session, user_id=user.id, amount=15, kind="chat_spend") == 35

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

    assert await spend(db_session, user_id=user.id, amount=10, kind="chat_spend") == 0

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


# ── 환불 래퍼가 예외를 밖으로 내지 않는다 ────────────────────────────────────
async def test_refund_in_new_transaction_swallows_failures() -> None:
    """환불은 제너레이터 본문에서 불린다. 예외가 새면 이미 시작된
    SSE 스트림을 뚫고 나가 태스크가 취소되고, 망가진 asyncpg 커넥션이 풀로 반환돼 **무관한
    요청이 500**이 된다(`core/rate_limit_gate.py:11-14`).
    """
    # 붙을 수 없는 엔진이라 `async with`가 즉시 터진다 — 그 예외를 삼키는지만 본다.
    dead_engine = create_async_engine(
        "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/nonexistent"
    )
    dead_factory = async_sessionmaker(dead_engine, expire_on_commit=False)
    try:
        await refund_in_new_transaction(
            dead_factory, user_id=uuid.uuid4(), amount=CHAT_TURN_COST, kind="chat_refund"
        )
    finally:
        await dead_engine.dispose()


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
    # 한 번도 받은 적 없는 유저 — 출석/확인 판정의 첫 호출이 여기로 온다.
    assert is_same_kst_day(None, now) is False


def test_is_same_kst_day_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="tz-aware"):
        is_same_kst_day(date(2026, 9, 17), datetime(2026, 9, 17, 12, 0))


# ── earned_lot_expiry(출석·미션 지급용) ───────────────────────────
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
    assert ATTENDANCE_GRANT_AMOUNT == 100


async def test_ledger_table_is_reachable(db_session: AsyncSession) -> None:
    # 마이그레이션이 실제로 적용됐는지(= `alembic upgrade head`가 돌았는지) 한 줄로 확인한다.
    assert await db_session.scalar(text("SELECT COUNT(*) FROM clover_ledger")) == 0
