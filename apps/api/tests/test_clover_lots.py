"""clover-page-goal-prompt.md CE-3 — `clover_lots` 스키마·백필·CHECK 제약(S1).

이 파일이 검증하는 성질 셋(§4-1 T-5·T-15, §4-1 CHECK 제약 2개):

1. 백필 마이그레이션의 SQL이 실제로 `clover_balance > 0`인 유저마다 로트 1행을 만들고
   Σ(remaining) == clover_balance가 성립한다. 잔액 0인 유저에겐 로트가 안 생긴다(T-5).
2. 백필 로트의 만료 시각 계산 함수가 마이그레이션 실행일(KST) 자정 + 8일을 낸다(T-15) —
   이 저장소에 시간을 얼리는 수단이 0건이라(freezegun 미설치) 순수 함수로 분리해 리터럴
   `datetime`을 주입해 검증한다. **마이그레이션 자체는 다시 돌리지 않는다** — `conftest.py`의
   `_migrated_schema`가 세션당 1회만 `upgrade(head)`를 실행해 실행 시각을 테스트가 통제할
   수 없다(사전 점검 PA-5). 경계 테스트 하나는 그 날 23:59에 실행돼도 보유 기간이 7일
   이상임을 검증한다 — "+7일"이면 자정 정규화 때문에 6일대로 떨어져 "7일 유효기간" 고지가
   깨진다(CE-7).
3. `remaining >= 0`·`remaining <= granted_amount` CHECK 제약 — `alembic check`가 CHECK
   제약을 비교하지 않으므로(`apps/api/CLAUDE.md` "쓰기 전 관문") 이 행위 테스트가 유일한
   검증이다.

T-5는 백필 마이그레이션의 실제 INSERT문(`_LEGACY_BACKFILL_SQL`)을 마이그레이션 파일에서
동적으로 불러와 그대로 실행한다 — SQL을 테스트에 다시 타이핑하면 마이그레이션이 나중에
바뀌어도 테스트가 낡은 사본을 계속 검증하는 드리프트가 생긴다(`test_chat_prompt_builder.py`의
`importlib.util.spec_from_file_location` 선례와 같은 기법).
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.clover import CloverLot
from factories import _make_user, _make_user_with_clover_lot

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "cf74d6d53561_clover_lots.py"
)


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("_migration_cf74d6d53561", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


# ── T-15 — 백필 만료 시각 계산(순수 함수) ────────────────────────────────────
def test_legacy_lot_expiry_is_execution_day_kst_midnight_plus_eight_days() -> None:
    """clover-page-goal-prompt.md CE-7 원문 예시 그대로: 실행일이 2026-09-21(KST)이면
    2026-09-29 00:00 KST가 나와야 한다."""
    migration = _load_migration()
    now = datetime(2026, 9, 21, 0, 0, tzinfo=migration.KST)  # type: ignore[attr-defined]

    result = migration._legacy_lot_expiry(now)  # type: ignore[attr-defined]

    assert result == datetime(2026, 9, 29, 0, 0, tzinfo=migration.KST)  # type: ignore[attr-defined]


def test_legacy_lot_expiry_converts_utc_across_the_kst_day_boundary() -> None:
    """UTC 15:30(=KST 다음 날 00:30)을 넣으면 **UTC 기준 같은 날짜가 아니라 KST 기준 다음
    날** 자정을 기준으로 계산해야 한다 — tzdata 존 이름이 아니라 고정 오프셋 산술이 실제로
    KST로 변환하는지 확인한다."""
    migration = _load_migration()
    now = datetime(2026, 9, 21, 15, 30, tzinfo=UTC)  # KST로는 2026-09-22 00:30

    result = migration._legacy_lot_expiry(now)  # type: ignore[attr-defined]

    assert result == datetime(2026, 9, 30, 0, 0, tzinfo=migration.KST)  # type: ignore[attr-defined]


def test_legacy_lot_expiry_rejects_naive_datetime() -> None:
    migration = _load_migration()

    with pytest.raises(ValueError, match="tz-aware"):
        migration._legacy_lot_expiry(datetime(2026, 9, 21, 0, 0))  # type: ignore[attr-defined]


def test_legacy_lot_expiry_guarantees_at_least_seven_days_even_at_end_of_day() -> None:
    """경계(CE-7의 존재 이유): 그 날 23:59(KST)에 실행돼도 보유 기간이 7일 이상이어야 한다.
    "+7일"으로 되돌리면 자정 정규화 때문에 보유 기간이 6일대로 떨어져 이 단언이 깨진다 —
    "7일 유효기간" 고지가 거짓이 되는 지점이다."""
    migration = _load_migration()
    now = datetime(2026, 9, 21, 23, 59, tzinfo=migration.KST)  # type: ignore[attr-defined]

    result = migration._legacy_lot_expiry(now)  # type: ignore[attr-defined]

    assert result - now >= timedelta(days=7)


# ── T-5 — 백필 INSERT ────────────────────────────────────────────────────────
async def test_backfill_creates_one_lot_matching_balance_and_skips_zero_balance(
    db_session: AsyncSession,
) -> None:
    migration = _load_migration()
    cutoff = datetime(2026, 9, 28, tzinfo=UTC)

    funded = _make_user(clover_balance=155)
    empty = _make_user(clover_balance=0)
    db_session.add_all([funded, empty])
    await db_session.flush()

    await db_session.execute(
        sa.text(migration._LEGACY_BACKFILL_SQL),  # type: ignore[attr-defined]
        {"cutoff": cutoff},
    )

    funded_lots = (
        await db_session.scalars(sa.select(CloverLot).where(CloverLot.user_id == funded.id))
    ).all()
    assert len(funded_lots) == 1
    lot = funded_lots[0]
    assert lot.kind == "legacy_balance"
    assert lot.granted_amount == 155
    assert lot.remaining == 155
    assert lot.expires_at == cutoff
    assert sum(l.remaining for l in funded_lots) == 155

    empty_lots = (
        await db_session.scalars(sa.select(CloverLot).where(CloverLot.user_id == empty.id))
    ).all()
    assert empty_lots == []


# ── CHECK 제약 2개 ────────────────────────────────────────────────────────────
async def test_check_constraint_rejects_remaining_below_zero(db_session: AsyncSession) -> None:
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        CloverLot(user_id=user.id, granted_amount=10, remaining=-1, kind="legacy_balance")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_check_constraint_rejects_remaining_above_granted_amount(
    db_session: AsyncSession,
) -> None:
    user = _make_user(clover_balance=0)
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        CloverLot(user_id=user.id, granted_amount=10, remaining=11, kind="legacy_balance")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── 로트 시딩 공용 테스트 헬퍼(CE-35) ─────────────────────────────────────────
async def test_make_user_with_clover_lot_matches_the_sum_invariant(db_session: AsyncSession) -> None:
    """`_make_user_with_clover_lot`이 CE-4 불변식(Σremaining == clover_balance)을
    셋업 시점부터 지키는지 — S2가 51곳을 옮길 때 의지할 헬퍼라 그 자체를 검증한다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=42)

    lots = (await db_session.scalars(sa.select(CloverLot).where(CloverLot.user_id == user.id))).all()
    assert sum(l.remaining for l in lots) == 42 == user.clover_balance


async def test_make_user_with_clover_lot_skips_lot_for_zero_balance(
    db_session: AsyncSession,
) -> None:
    user = await _make_user_with_clover_lot(db_session, clover_balance=0)

    lots = (await db_session.scalars(sa.select(CloverLot).where(CloverLot.user_id == user.id))).all()
    assert lots == []
