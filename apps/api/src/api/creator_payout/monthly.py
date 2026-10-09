"""크리에이터 정산 월 확정 배치.

    # 운영: 서빙 중인 api 컨테이너 안에서 (ops/creator-payout-settle.sh 가 매일 부른다)
    python -m api.creator_payout.monthly

승인 때의 소급과 같은 계산(`settlement.confirm_window`)을 쓰려고 앱 코드로 두고, 지금 서빙 중인 api 컨테이너 안에서 돈다 —
계산식과 비율 설정을 읽는 곳이 하나다.

1. 정산이 꺼져 있으면(`creator_payout_active()`) 아무것도 하지 않고 0 으로 끝난다.
2. 매월 3일 00:00(KST)부터 전월을 확정할 수 있다. 달이 끝나고 이틀을 두는 것은 달 끝 무렵에 시작해 늦게 커밋된 차감·환급을
   그 달 확정이 놓치지 않게 하기 위해서다.
3. 확정할 달 = 실행 기록(`creator_payout_batch_runs`)이 없는 달 중 월 확정 시작(`monthly_from_at`)이 가장 이른 신청의
   달부터 확정할 수 있는 마지막 달까지. 정산을 꺼 둔 동안 밀린 달을 한 번에 따라잡는다. 적립 시작(`accrual_start_at`)이
   아니라 월 확정 시작에서 출발하는 것은, 첫 승인의 소급 기간(적립 시작 ~ 월 확정 시작)은 소급 확정 행이 이미 셌기
   때문이다. 승인된 적 있는 사람이 없으면 달 목록이 비고 실행 기록도 남지 않는다.
4. 달마다 대상 크리에이터 = ⑴ 월 확정 구간 [`monthly_from_at`, `revoked_at`)이 그 달과 겹치는 신청이 있는 사람 ∪ ⑵ 이미
   확정한 내역 줄의 결제 중 확정 뒤 결제 취소 조정 대상(그 달 끝까지 성공한 취소가 있고 지금 계수가 1 보다 작은 결제)이
   있는 사람. ⑵는 승인 취소된 사람도 포함하고, 취소가 없는 달에도 계수가 내려간 결제가 있으면 대상이다.
   사람마다 트랜잭션 하나: `users` 행 잠금(탈퇴했으면 건너뜀 — 미확정 적립은 탈퇴로 소멸한다) → 그 달 월 확정 행이 이미
   있으면 건너뜀 → 신청 행마다 [max(월초, 월 확정 시작), min(다음 월초, 승인 취소 시각)) 중 길이가 있는 것을 모아(같은
   달 승인 취소 → 재승인이면 둘) `confirm_window` 를 한 번 → 커밋.
5. 그 달 크리에이터를 다 끝내면 감시 수 둘을 세어 실행 기록을 넣는다. 중간에 죽으면 실행 기록이 없어 다음 실행이 그
   달을 다시 돌고, 이미 확정된 크리에이터는 4의 확인에서 건너뛴다.
6. 다른 배치가 이미 돌고 있으면(advisory 잠금) 아무것도 하지 않고 0 으로 끝난다.
7. 표준출력 마지막 줄이 요약이다(`ops/creator-payout-settle.sh` 가 그 줄로 알림을 보낸다). 실패하면 Bugsink 에 남기고
   0 이 아닌 코드로 끝난다.

배분·환급 행은 잠그지 않고 읽는다. 확정하는 달은 끝난 지 이틀이 지났고, 실행 중에 커밋되는 환급은 환급 시각("지금")이
속한 달에서 빠지므로 결과가 실행 타이밍에 달리지 않는다.
"""

import asyncio
import sys
import traceback
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import sentry_sdk
from sqlalchemy import DateTime, exists, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.core.rate_limit import KST
from api.core.sentry import build_sentry_options, capture_dependency_failure
from api.creator_payout.config import creator_payout_active
from api.creator_payout.settlement import CAPPED_PAYMENTS_SQL, confirm_window
from api.db.models.auth import User
from api.db.models.creator_payout import CreatorPayoutApplication, CreatorPayoutBatchRun, CreatorPayoutConfirmation
from api.db.session import async_session_factory, engine

# 달이 끝나고 이만큼 지나야 그 달을 확정한다(매월 3일 00:00 KST 부터 전월).
SETTLE_AFTER_MONTH_END = timedelta(days=2)

# ⑵: 확정 뒤 결제 취소 조정 대상 결제로 이미 확정한 줄이 있는 크리에이터. 대상 결제 판정은 정산 계산과 같은 SQL 이다.
_ADJUSTMENT_CREATORS_SQL = text(
    f"""
SELECT DISTINCT c.user_id
  FROM creator_payout_confirmation_lines l
  JOIN creator_payout_confirmations c ON c.id = l.confirmation_id
 WHERE l.payment_id IN ({CAPPED_PAYMENTS_SQL})
"""
)

# 그 달의 채팅·소설 차감 중 사용처가 없는 것. 정산에서 빠진 차감의 수다.
_UNATTRIBUTED_SPEND_COUNT_SQL = text(
    """
SELECT count(*)
  FROM clover_ledger g
 WHERE g.kind IN ('chat_spend', 'novelize_spend')
   AND g.created_at >= :ms AND g.created_at < :me
   AND NOT EXISTS (SELECT 1 FROM clover_spend_usages u WHERE u.spend_ledger_id = g.id)
"""
)

# 사용처가 있는(그 달 끝 전에 일어난) 차감의 유료 배분 중 환급 합과 환급 행 합이 다른 것. 환급 행 없이 환급된 몫은 정산이
# 빼지 못해 사용으로 남는다.
_REFUND_EVENT_MISMATCH_COUNT_SQL = text(
    """
SELECT count(*)
  FROM clover_spend_allocations a
  JOIN clover_spend_usages u ON u.spend_ledger_id = a.spend_ledger_id
  JOIN clover_lots lot ON lot.id = a.lot_id AND lot.kind = 'purchase_paid'
 WHERE u.created_at < :me
   AND a.refunded_amount <> COALESCE((SELECT SUM(r.amount) FROM clover_spend_refunds r WHERE r.allocation_id = a.id), 0)
"""
)


@dataclass(frozen=True)
class MonthResult:
    period_month: date
    creator_count: int
    total_amount_krw: int
    unattributed_spend_count: int
    refund_event_mismatch_count: int


def month_bounds(month: date) -> tuple[datetime, datetime]:
    """그 달 [월초, 다음 월초) — KST 자정, tz-aware."""
    start = datetime(month.year, month.month, 1, tzinfo=KST)
    end = datetime(month.year + month.month // 12, month.month % 12 + 1, 1, tzinfo=KST)
    return start, end


def _month_of(at: datetime) -> date:
    local = at.astimezone(KST)
    return date(local.year, local.month, 1)


def _next_month(month: date) -> date:
    return month_bounds(month)[1].date()


def last_settleable_month(now: datetime) -> date:
    """`now` 에 확정할 수 있는 마지막 달. 다음 월초 + 2일이 지난 달이다."""
    month = _month_of(now)
    while month_bounds(month)[1] + SETTLE_AFTER_MONTH_END > now:
        month = _month_of(month_bounds(month)[0] - timedelta(days=1))
    return month


async def months_to_settle(db: AsyncSession, now: datetime) -> list[date]:
    earliest = await db.scalar(select(func.min(CreatorPayoutApplication.monthly_from_at)))
    if earliest is None:
        return []
    done = set((await db.scalars(select(CreatorPayoutBatchRun.period_month))).all())
    last = last_settleable_month(now)
    months: list[date] = []
    month = _month_of(earliest)
    while month <= last:
        if month not in done:
            months.append(month)
        month = _next_month(month)
    return months


async def _target_creators(db: AsyncSession, ms: datetime, me: datetime) -> list[uuid.UUID]:
    app = CreatorPayoutApplication
    month_start, month_end = literal(ms, DateTime(timezone=True)), literal(me, DateTime(timezone=True))
    accruing = await db.scalars(
        select(app.user_id)
        .where(
            app.status.in_(("approved", "revoked")),
            func.greatest(app.monthly_from_at, month_start)
            < func.least(func.coalesce(app.revoked_at, month_end), month_end),
        )
        .distinct()
    )
    adjusting = await db.scalars(_ADJUSTMENT_CREATORS_SQL, {"me": me})
    return sorted(set(accruing.all()) | set(adjusting.all()))


def _windows(
    applications: Sequence[CreatorPayoutApplication], ms: datetime, me: datetime
) -> list[tuple[datetime, datetime]]:
    """그 달 안의 월 확정 구간들(시작 순, 길이 0 제외)."""
    windows: list[tuple[datetime, datetime]] = []
    for application in applications:
        if application.monthly_from_at is None:
            continue
        start = max(ms, application.monthly_from_at)
        end = me if application.revoked_at is None else min(me, application.revoked_at)
        if start < end:
            windows.append((start, end))
    return sorted(windows)


async def _settle_creator(db: AsyncSession, creator_id: uuid.UUID, month: date) -> None:
    """크리에이터 한 명의 그 달 월 확정. 이 트랜잭션 안에서 커밋한다."""
    ms, me = month_bounds(month)
    # 승인·승인 취소·탈퇴와 이 행에서 줄을 선다. FK 의 KEY SHARE(차감의 사용처 기록 등)는 막지 않는다.
    deleted_at = await db.scalar(select(User.deleted_at).where(User.id == creator_id).with_for_update(key_share=True))
    if deleted_at is not None:
        return
    already = await db.scalar(
        select(
            exists().where(
                CreatorPayoutConfirmation.user_id == creator_id,
                CreatorPayoutConfirmation.kind == "monthly",
                CreatorPayoutConfirmation.period_month == month,
            )
        )
    )
    if already:
        return
    applications = (
        await db.scalars(
            select(CreatorPayoutApplication).where(
                CreatorPayoutApplication.user_id == creator_id,
                CreatorPayoutApplication.status.in_(("approved", "revoked")),
            )
        )
    ).all()
    # 구간이 둘이어도 한 번에 넘긴다 — 같은 달 월 확정 행은 하나뿐이다.
    await confirm_window(
        db,
        creator_id=creator_id,
        kind="monthly",
        period_month=month,
        windows=_windows(applications, ms, me),
        cancel_adjust_month=(ms, me),
    )
    await db.commit()


async def _settle_month(session_factory: async_sessionmaker[AsyncSession], month: date) -> MonthResult:
    ms, me = month_bounds(month)
    async with session_factory() as db:
        creators = await _target_creators(db, ms, me)
    for creator_id in creators:
        async with session_factory() as db:
            await _settle_creator(db, creator_id, month)

    async with session_factory() as db:
        count, total = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(CreatorPayoutConfirmation.amount_krw), 0)).where(
                    CreatorPayoutConfirmation.kind == "monthly", CreatorPayoutConfirmation.period_month == month
                )
            )
        ).one()
        result = MonthResult(
            period_month=month,
            creator_count=int(count),
            total_amount_krw=int(total),
            unattributed_spend_count=int((await db.scalar(_UNATTRIBUTED_SPEND_COUNT_SQL, {"ms": ms, "me": me})) or 0),
            refund_event_mismatch_count=int((await db.scalar(_REFUND_EVENT_MISMATCH_COUNT_SQL, {"me": me})) or 0),
        )
        db.add(
            CreatorPayoutBatchRun(
                period_month=month,
                creator_count=result.creator_count,
                total_amount_krw=result.total_amount_krw,
                unattributed_spend_count=result.unattributed_spend_count,
                refund_event_mismatch_count=result.refund_event_mismatch_count,
            )
        )
        await db.commit()
    return result


# 월 확정 배치끼리만 쓰는 advisory 잠금 키. 사람이 수동 실행을 크론과 겹쳐 돌려도 두 번째가 실행 기록 중복으로 실패 알림을
# 내지 않고 조용히 비켜서게 한다.
BATCH_LOCK_KEY = 0x63_70_6D_62  # "cpmb"

RunOutcome = list[MonthResult] | Literal["off", "busy"]


async def run_monthly(session_factory: async_sessionmaker[AsyncSession], *, now: datetime) -> RunOutcome:
    """확정할 달을 차례로 확정한다. 정산이 꺼져 있으면 `"off"`, 다른 배치가 돌고 있으면 `"busy"`, 확정할 달이 없으면
    빈 목록."""
    if not creator_payout_active():
        return "off"
    # 잠금 전용 세션: 자기 커넥션의 트랜잭션에 잠금을 걸고 배치가 끝날 때까지 커밋하지 않는다. 크리에이터별 커밋은 아래에서
    # 새로 여는 다른 세션(다른 커넥션)의 것이라 이 잠금을 풀지 않는다. 세션이 닫히면(예외로 끝나도) 트랜잭션이 롤백되며 풀린다
    # — 세션 수준 잠금과 달리 풀에 돌아간 커넥션에 잠금이 남지 않는다.
    async with session_factory() as lock_db:
        if not await lock_db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": BATCH_LOCK_KEY}):
            return "busy"
        async with session_factory() as db:
            months = await months_to_settle(db, now)
        return [await _settle_month(session_factory, month) for month in months]


def summary_line(results: RunOutcome) -> str:
    """표준출력 마지막 줄. 회원을 알아볼 단서는 싣지 않는다(외부 알림 채널로 나간다)."""
    if results == "off":
        return "크리에이터 정산 꺼짐 — 확정하지 않음"
    if results == "busy":
        return "크리에이터 정산 다른 실행 중 — 이번 실행은 확정하지 않음"
    if not results:
        return "크리에이터 정산 확정할 달 없음"
    parts = [
        f"{r.period_month:%Y-%m} {r.creator_count}명 {r.total_amount_krw:,}원"
        f" (사용처 없는 차감 {r.unattributed_spend_count}, 환급 기록 불일치 누적 {r.refund_event_mismatch_count})"
        for r in results
    ]
    return "크리에이터 정산 확정: " + "; ".join(parts)


def _init_sentry() -> None:
    # 서버(`main.py`)와 같은 옵션. DSN 이 없으면(dev) 부르지 않아 실패 기록이 no-op 이다.
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment, **build_sentry_options())


async def _main() -> None:
    try:
        results = await run_monthly(async_session_factory, now=datetime.now(UTC))
    finally:
        await engine.dispose()
    print(summary_line(results))


def main() -> int:
    _init_sentry()
    try:
        asyncio.run(_main())
    except Exception as exc:
        capture_dependency_failure(exc, dependency="creator_payout")
        # 로그 파일(VM)에만 남는다. 알림은 래퍼가 고정 문구로 보낸다 — 예외 문장에는 SQL 인자(회원 id)가 섞일 수 있다.
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
