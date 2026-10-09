"""크리에이터 정산 월 확정 배치(`creator_payout/monthly.py`): 확정할 달, 대상 크리에이터, 달 안의 구간, 재실행, 감시 수.

결제는 모두 1클로버 = 3원이라 비율 500bps 에서 유료 22클로버 = 3원이다. 시각은 사용처·환급·원장 행의 `created_at` 을 직접
고쳐 만들고, 배치의 "지금"은 인자로 준다. 배치는 크리에이터마다 세션을 새로 열어 커밋하므로 테스트 커넥션에 묶인 세션
팩토리를 넘긴다 — 그 커밋은 바깥 트랜잭션을 끝내지 않아 테스트가 끝나면 함께 롤백된다. 확정 중 환급이 배치를 막지 않는지는
진짜로 커밋되는 독립 커넥션 둘로 본다(맨 아래).
"""

import asyncio
import importlib.util
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import pytest_asyncio
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core import config
from api.core.clover import CloverKind, refund_spend, spend
from api.creator_payout import monthly
from api.creator_payout.monthly import (
    BATCH_LOCK_KEY,
    MonthResult,
    RunOutcome,
    _settle_creator,
    month_bounds,
    run_monthly,
    summary_line,
)
from api.creator_payout.settlement import confirm_window
from api.db.models.auth import User
from api.db.models.clover import (
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
)
from api.db.models.content import Content
from api.db.models.creator_payout import (
    CreatorPayoutApplication,
    CreatorPayoutBatchRun,
    CreatorPayoutConfirmation,
    CreatorPayoutConfirmationLine,
)
from api.db.models.payment import Payment
from factories import (
    Player,
    _application,
    _console_cancel,
    _make_draft_content,
    _make_player,
    _make_user,
    _refund,
    _use,
    kst,
)

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _creator_payout_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """정산은 스위치와 본인인증 설정이 모두 있어야 켜진다. 로컬 `.env` 의 값이 아니라 테스트가 정한다."""
    monkeypatch.setattr(config.settings, "portone_store_id", "store-test-0001")
    monkeypatch.setattr(config.settings, "portone_identity_channel_key", "identity-channel-test")
    monkeypatch.setattr(config.settings, "portone_api_secret", "api-secret-test")
    monkeypatch.setattr(config.settings, "identity_ci_hmac_key", "ci-key-test")
    monkeypatch.setattr(config.settings, "creator_payout_enabled", True)
    monkeypatch.setattr(config.settings, "creator_payout_rate_bps", 500)


@pytest.fixture
def factory(db_session: AsyncSession) -> Factory:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False)


async def _creator(db: AsyncSession) -> tuple[User, Content]:
    creator = _make_user()
    db.add(creator)
    await db.flush()
    return creator, await _make_draft_content(db, creator_user_id=creator.id)


async def _player(db: AsyncSession) -> Player:
    return await _make_player(db, amount_krw=9_900, paid=3_300)


async def _monthly_rows(db: AsyncSession, creator: User) -> list[CreatorPayoutConfirmation]:
    return list(
        (
            await db.scalars(
                select(CreatorPayoutConfirmation)
                .where(CreatorPayoutConfirmation.user_id == creator.id, CreatorPayoutConfirmation.kind == "monthly")
                .order_by(CreatorPayoutConfirmation.period_month)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def _run_months(db: AsyncSession) -> list[date]:
    return list(
        (
            await db.scalars(select(CreatorPayoutBatchRun.period_month).order_by(CreatorPayoutBatchRun.period_month))
        ).all()
    )


def _months(results: RunOutcome) -> list[date]:
    assert isinstance(results, list)
    return [result.period_month for result in results]


# ── 확정할 달 ─────────────────────────────────────────────────────────────────
async def test_running_the_same_month_twice_changes_nothing(db_session: AsyncSession, factory: Factory) -> None:
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
    await _use(db_session, await _player(db_session), content, 22, kst(10, 15))

    first = await run_monthly(factory, now=kst(11, 3))
    second = await run_monthly(factory, now=kst(11, 4))

    assert first == [MonthResult(date(2026, 10, 1), 1, 3, 0, 0)]
    assert second == []
    assert summary_line(second) == "크리에이터 정산 확정할 달 없음"
    assert [row.amount_krw for row in await _monthly_rows(db_session, creator)] == [3]
    assert await _run_months(db_session) == [date(2026, 10, 1)]


async def test_months_missed_while_switched_off_are_confirmed_in_one_run(
    db_session: AsyncSession, factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
    player = await _player(db_session)
    await _use(db_session, player, content, 22, kst(10, 15))
    await _use(db_session, player, content, 44, kst(11, 15))

    monkeypatch.setattr(config.settings, "creator_payout_enabled", False)
    off = await run_monthly(factory, now=kst(12, 5))
    assert (off, await _run_months(db_session)) == ("off", [])
    assert summary_line(off) == "크리에이터 정산 꺼짐 — 확정하지 않음"

    monkeypatch.setattr(config.settings, "creator_payout_enabled", True)
    results = await run_monthly(factory, now=kst(12, 5))

    assert _months(results) == [date(2026, 10, 1), date(2026, 11, 1)]
    assert [(row.period_month, row.amount_krw) for row in await _monthly_rows(db_session, creator)] == [
        (date(2026, 10, 1), 3),
        (date(2026, 11, 1), 6),
    ]
    assert summary_line(results) == (
        "크리에이터 정산 확정: 2026-10 1명 3원 (사용처 없는 차감 0, 환급 기록 불일치 누적 0);"
        " 2026-11 1명 6원 (사용처 없는 차감 0, 환급 기록 불일치 누적 0)"
    )


async def test_previous_month_is_confirmed_from_the_third_at_midnight_kst(
    db_session: AsyncSession, factory: Factory
) -> None:
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
    await _use(db_session, await _player(db_session), content, 22, kst(10, 15))

    before = await run_monthly(factory, now=kst(11, 2, 23, 59, 59))
    assert (before, await _monthly_rows(db_session, creator)) == ([], [])

    after = await run_monthly(factory, now=kst(11, 3))
    assert _months(after) == [date(2026, 10, 1)]


async def test_no_one_ever_approved_leaves_no_run_record(db_session: AsyncSession, factory: Factory) -> None:
    """승인된 적 있는 사람이 없으면 확정할 달이 없고, 그 달들의 감시 수도 남지 않는다."""
    creator, content = await _creator(db_session)
    db_session.add(
        CreatorPayoutApplication(
            user_id=creator.id, status="pending", consented_at=kst(10, 1), privacy_version="2026-10-01"
        )
    )
    player = await _player(db_session)
    await _use(db_session, player, content, 22, kst(10, 15))
    await spend(db_session, user_id=player.user.id, amount=10, kind="chat_spend")

    assert await run_monthly(factory, now=kst(12, 3)) == []
    assert await _run_months(db_session) == []


async def test_resuming_a_month_that_died_midway_settles_only_the_rest(
    db_session: AsyncSession, factory: Factory
) -> None:
    """두 크리에이터 중 A 만 확정하고 실행 기록 없이 죽은 10월을 다시 돌리면, A 는 그대로 두고 B 만 확정한 뒤 실행 기록을
    남기고 정상으로 끝난다 — A 를 다시 확정하려 들면 월 확정 유니크에 걸려 그 달과 뒤의 달이 매일 막힌다."""
    player = await _player(db_session)
    creators = []
    for amount in (22, 44):
        creator, content = await _creator(db_session)
        await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
        await _use(db_session, player, content, amount, kst(10, 15))
        creators.append(creator)
    a, b = creators
    async with factory() as db:
        await _settle_creator(db, a.id, date(2026, 10, 1))

    results = await run_monthly(factory, now=kst(11, 3))

    assert results == [MonthResult(date(2026, 10, 1), 2, 9, 0, 0)]
    assert [row.amount_krw for row in await _monthly_rows(db_session, a)] == [3]
    assert [row.amount_krw for row in await _monthly_rows(db_session, b)] == [6]
    assert await _run_months(db_session) == [date(2026, 10, 1)]


async def test_a_second_batch_steps_aside_while_one_is_running(
    db_engine: AsyncEngine, db_session: AsyncSession, factory: Factory
) -> None:
    """다른 커넥션이 배치 잠금을 쥔 동안 실행하면 아무것도 확정하지 않고 "다른 실행 중"으로 끝난다(실패가 아니다)."""
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
    await _use(db_session, await _player(db_session), content, 22, kst(10, 15))

    async with db_engine.connect() as holder:
        transaction = await holder.begin()
        try:
            await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BATCH_LOCK_KEY})
            results = await run_monthly(factory, now=kst(11, 3))
        finally:
            await transaction.rollback()

    assert results == "busy"
    assert summary_line(results) == "크리에이터 정산 다른 실행 중 — 이번 실행은 확정하지 않음"
    assert (await _monthly_rows(db_session, creator), await _run_months(db_session)) == ([], [])


# ── 첫 승인 달 ────────────────────────────────────────────────────────────────
async def _first_approval_on_december_tenth(db: AsyncSession) -> tuple[User, Content, Player]:
    """승인 12-10 12:00 KST, 컷 C = 11:55. 소급 [C − 90일, C) 은 승인이 확정했고 월 확정은 C 부터 센다."""
    creator, content = await _creator(db)
    cut = kst(12, 10, 11, 55)
    await _application(db, creator.id, accrual_start_at=cut - timedelta(days=90), monthly_from_at=cut)
    player = await _player(db)
    await _use(db, player, content, 22, kst(12, 5))
    await _use(db, player, content, 44, cut)
    retro = await confirm_window(
        db,
        creator_id=creator.id,
        kind="retro",
        period_month=None,
        windows=[(cut - timedelta(days=90), cut)],
        cancel_adjust_month=None,
    )
    assert retro is not None and retro.gross_units == 22
    return creator, content, player


async def test_first_approval_month_counts_only_from_the_cut(db_session: AsyncSession, factory: Factory) -> None:
    """12-05 차감은 소급이 셌다 — 12월 확정은 [C, 01-01) 의 44 만 센다."""
    creator, _, _ = await _first_approval_on_december_tenth(db_session)

    await run_monthly(factory, now=kst(1, 3, year=2027))

    rows = await _monthly_rows(db_session, creator)
    assert [(row.period_month, row.gross_units, row.amount_krw) for row in rows] == [(date(2026, 12, 1), 44, 6)]
    assert rows[0].window_start == kst(12, 10, 11, 55)


async def test_retro_months_get_no_monthly_rows_on_an_empty_run_table(
    db_session: AsyncSession, factory: Factory
) -> None:
    """실행 기록이 하나도 없는 DB 에서 첫 승인 뒤 첫 배치는 12월만 확정한다 — 소급 기간(9~11월)은 소급 행이 셌다."""
    await _first_approval_on_december_tenth(db_session)

    results = await run_monthly(factory, now=kst(1, 3, year=2027))

    assert _months(results) == [date(2026, 12, 1)]
    assert await _run_months(db_session) == [date(2026, 12, 1)]


# ── 달 안의 구간 ──────────────────────────────────────────────────────────────
async def test_revoked_month_counts_until_the_revocation(db_session: AsyncSession, factory: Factory) -> None:
    """10-20 승인 취소. 10-10 차감 44 는 세고, 취소 뒤 10-25 에 그 차감에서 돌려준 22 는 빼지 않는다(적립 구간 밖의
    환급) — 그 달 구간이 [월초, 취소 시각) 이라서다."""
    creator, content = await _creator(db_session)
    revoked_at = kst(10, 20)
    await _application(db_session, creator.id, accrual_start_at=kst(9, 1), revoked_at=revoked_at)
    player = await _player(db_session)
    spent = await _use(db_session, player, content, 44, kst(10, 10))
    await _refund(db_session, player, spent, 22, kst(10, 25))
    await _use(db_session, player, content, 66, kst(10, 26))

    await run_monthly(factory, now=kst(11, 3))

    rows = await _monthly_rows(db_session, creator)
    october = rows[-1]
    assert (october.period_month, october.gross_units, october.refunded_units, october.amount_krw) == (
        date(2026, 10, 1),
        44,
        0,
        6,
    )
    assert (october.window_start, october.window_end) == (kst(10, 1), revoked_at)


async def test_revoke_and_reapproval_in_one_month_make_one_row_without_the_gap(
    db_session: AsyncSession, factory: Factory
) -> None:
    """10-10 승인 취소 → 10-20 재승인(소급 없이 적립·월 확정 모두 10-20 부터). 10월 행은 하나이고, 틈(10-15)의 44 는
    빠진다: 22 + 66 = 88 → 12원."""
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(9, 1), revoked_at=kst(10, 10))
    await _application(db_session, creator.id, accrual_start_at=kst(10, 20))
    player = await _player(db_session)
    await _use(db_session, player, content, 22, kst(10, 5))
    await _use(db_session, player, content, 44, kst(10, 15))
    await _use(db_session, player, content, 66, kst(10, 25))

    await run_monthly(factory, now=kst(11, 3))

    october = [row for row in await _monthly_rows(db_session, creator) if row.period_month == date(2026, 10, 1)]
    assert [(row.gross_units, row.amount_krw) for row in october] == [(88, 12)]


async def test_withdrawn_creator_is_skipped(db_session: AsyncSession, factory: Factory) -> None:
    """10월에 쓰인 뒤 11-01 탈퇴. 미확정 적립은 탈퇴로 소멸한다 — 그 사용이 정산 대상(사용 뒤 탈퇴)이어도 행이 없다."""
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
    await _use(db_session, await _player(db_session), content, 22, kst(10, 15))
    creator.deleted_at = kst(11, 1)
    await db_session.flush()

    results = await run_monthly(factory, now=kst(11, 3))

    assert await _monthly_rows(db_session, creator) == []
    assert results == [MonthResult(date(2026, 10, 1), 0, 0, 0, 0)]


# ── 확정 뒤 결제 취소 조정만 있는 달 ───────────────────────────────────────────────
async def _revoked_creator_with_october_confirmed(db: AsyncSession, factory: Factory) -> tuple[User, Content, Player]:
    """9-01 승인, 11-01 승인 취소. E(9,900원·유료 3,300)가 10월에 600 을 써 10월이 81원으로 확정됐다."""
    creator, content = await _creator(db)
    await _application(db, creator.id, accrual_start_at=kst(9, 1), revoked_at=kst(11, 1))
    player = await _player(db)
    await _use(db, player, content, 600, kst(10, 15))
    await run_monthly(factory, now=kst(11, 3))
    assert [row.amount_krw for row in await _monthly_rows(db, creator)][-1] == 81
    return creator, content, player


async def test_revoked_creator_gets_an_adjustment_only_row_when_a_confirmed_payment_is_cancelled(
    db_session: AsyncSession, factory: Factory
) -> None:
    """11-10 콘솔 부분 취소 8,910원 → 계수 0.55. 11월 확정은 적립 구간이 없어도 45 − 81.8181… = −36.8… → −36원 행을 낸다."""
    creator, _, player = await _revoked_creator_with_october_confirmed(db_session, factory)
    await _console_cancel(db_session, player.payment, 8_910, kst(11, 10))

    await run_monthly(factory, now=kst(12, 3))

    november = (await _monthly_rows(db_session, creator))[-1]
    assert (november.period_month, november.gross_units, november.amount_krw) == (date(2026, 11, 1), 0, -36)
    assert (november.window_start, november.window_end) == month_bounds(date(2026, 11, 1))


async def test_revoked_creator_is_adjusted_again_in_a_month_without_cancellation(
    db_session: AsyncSession, factory: Factory
) -> None:
    """11-10 취소(계수 0.55) → 11-20 10월 사용 중 100 이 늦게 환급(순사용 500, 계수 0.66): 11월 조정 54 − 81.8… = −27.8…
    → −27원. 12월에는 취소가 없지만 E 가 돌려받은 100 을 다른 작가 작품에서 다시 써 계수가 0.55 로 내려간다 → 그 결제가
    여전히 조정 대상이라 12월 조정 45 − 54 = −9원 행이 생긴다."""
    creator, _, player = await _revoked_creator_with_october_confirmed(db_session, factory)
    october_spend = await db_session.scalar(
        select(CloverSpendUsage.spend_ledger_id).where(CloverSpendUsage.content_owner_user_id == creator.id)
    )
    assert october_spend is not None
    await _console_cancel(db_session, player.payment, 8_910, kst(11, 10))
    await _refund(db_session, player, october_spend, 100, kst(11, 20))
    await run_monthly(factory, now=kst(12, 3))

    _, other_content = await _creator(db_session)
    await _use(db_session, player, other_content, 100, kst(12, 15))
    await run_monthly(factory, now=kst(1, 3, year=2027))

    rows = await _monthly_rows(db_session, creator)
    assert [(row.period_month, row.gross_units, row.amount_krw) for row in rows[-2:]] == [
        (date(2026, 11, 1), 0, -27),
        (date(2026, 12, 1), 0, -9),
    ]


async def test_revoked_creator_without_cancelled_payments_gets_no_row(
    db_session: AsyncSession, factory: Factory
) -> None:
    creator, _, _ = await _revoked_creator_with_october_confirmed(db_session, factory)

    results = await run_monthly(factory, now=kst(12, 3))

    assert [row.period_month for row in await _monthly_rows(db_session, creator)][-1] == date(2026, 10, 1)
    assert results == [MonthResult(date(2026, 11, 1), 0, 0, 0, 0)]


# ── 감시 수 ──────────────────────────────────────────────────────────────────
async def test_run_record_counts_unattributed_spends_and_refunds_without_records(
    db_session: AsyncSession, factory: Factory
) -> None:
    """10월의 사용처 없는 채팅·소설 차감 2건(11월 것·이미지·사용처 있는 차감은 세지 않는다)과, 환급 행 없이 환급 합만
    오른 유료 배분 1건."""
    creator, content = await _creator(db_session)
    await _application(db_session, creator.id, accrual_start_at=kst(10, 1))
    player = await _player(db_session)
    attributed = await _use(db_session, player, content, 22, kst(10, 15))
    await _use(db_session, player, None, 30, kst(10, 15), usage="image")
    unattributed: dict[uuid.UUID, datetime] = {}
    spends: list[tuple[CloverKind, datetime]] = [
        ("chat_spend", kst(10, 3)),
        ("novelize_spend", kst(10, 31, 23)),
        ("chat_spend", kst(11, 1)),
    ]
    for kind, at in spends:
        spent = await spend(db_session, user_id=player.user.id, amount=10, kind=kind)
        assert spent is not None
        unattributed[spent.ledger_id] = at
    for ledger_id, at in unattributed.items():
        await db_session.execute(update(CloverLedger).where(CloverLedger.id == ledger_id).values(created_at=at))
    await db_session.execute(
        update(CloverSpendAllocation)
        .where(CloverSpendAllocation.spend_ledger_id == attributed)
        .values(refunded_amount=CloverSpendAllocation.refunded_amount + 5)
    )

    results = await run_monthly(factory, now=kst(11, 3))

    assert isinstance(results, list)
    assert (results[0].unattributed_spend_count, results[0].refund_event_mismatch_count) == (2, 1)
    run = await db_session.get(CreatorPayoutBatchRun, date(2026, 10, 1))
    assert run is not None
    assert (run.creator_count, run.total_amount_krw, run.unattributed_spend_count, run.refund_event_mismatch_count) == (
        1,
        3,
        2,
        1,
    )


# ── 진입점 ───────────────────────────────────────────────────────────────────
async def test_entry_prints_the_summary_as_the_last_line(
    db_session: AsyncSession, factory: Factory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    disposed: list[bool] = []

    async def _dispose() -> None:
        disposed.append(True)

    monkeypatch.setattr(monthly, "async_session_factory", factory)
    monkeypatch.setattr(monthly, "engine", SimpleNamespace(dispose=_dispose))

    await monthly._main()

    assert capsys.readouterr().out.splitlines()[-1] == "크리에이터 정산 확정할 달 없음"
    assert disposed == [True]


def test_failure_is_reported_and_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[BaseException | None, str]] = []

    def _run(coroutine: object) -> None:
        coroutine.close()  # type: ignore[attr-defined]
        raise RuntimeError("db down")

    monkeypatch.setattr(monthly, "asyncio", SimpleNamespace(run=_run))
    monkeypatch.setattr(
        monthly,
        "capture_dependency_failure",
        lambda exc=None, *, dependency: captured.append((exc, dependency)),
    )

    assert monthly.main() == 1
    assert [(type(exc), dependency) for exc, dependency in captured] == [(RuntimeError, "creator_payout")]


# ── 확정 중 환급(독립 커넥션) ──────────────────────────────────────────────────
@pytest_asyncio.fixture
async def committed(db_engine: AsyncEngine) -> AsyncIterator[tuple[Factory, list[uuid.UUID]]]:
    """진짜로 커밋하는 세션 팩토리와, 지울 회원 id 목록. 끝나면 정산·클로버·결제·작품·회원 순(FK 역순)으로 지운다."""
    commit_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user_ids: list[uuid.UUID] = []
    yield commit_factory, user_ids
    async with commit_factory() as cleanup:
        ledger_ids = select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
        allocation_ids = select(CloverSpendAllocation.id).where(CloverSpendAllocation.spend_ledger_id.in_(ledger_ids))
        confirmation_ids = select(CreatorPayoutConfirmation.id).where(CreatorPayoutConfirmation.user_id.in_(user_ids))
        await cleanup.execute(delete(CreatorPayoutBatchRun))
        await cleanup.execute(
            delete(CreatorPayoutConfirmationLine).where(
                CreatorPayoutConfirmationLine.confirmation_id.in_(confirmation_ids)
            )
        )
        await cleanup.execute(delete(CreatorPayoutConfirmation).where(CreatorPayoutConfirmation.user_id.in_(user_ids)))
        await cleanup.execute(delete(CreatorPayoutApplication).where(CreatorPayoutApplication.user_id.in_(user_ids)))
        await cleanup.execute(delete(CloverSpendRefund).where(CloverSpendRefund.allocation_id.in_(allocation_ids)))
        await cleanup.execute(delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(ledger_ids)))
        await cleanup.execute(delete(CloverSpendAllocation).where(CloverSpendAllocation.id.in_(allocation_ids)))
        await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
        await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
        await cleanup.execute(delete(Payment).where(Payment.user_id.in_(user_ids)))
        await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(user_ids)))
        await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def test_a_refund_in_progress_does_not_block_the_batch_and_lands_in_the_next_month(
    db_engine: AsyncEngine, committed: tuple[Factory, list[uuid.UUID]]
) -> None:
    """지난달에 44 를 쓴 배분을 다른 커넥션이 잠근 채(환급 진행 중) 배치가 지난달을 확정하고 끝난다(6원). 그 뒤 커밋된
    22 환급은 환급 시각(이번 달)에 속해 지난달 확정은 그대로이고 이번 달 확정에서 −3원으로 빠진다."""
    commit_factory, user_ids = committed
    now = datetime.now(UTC)
    this_month = month_bounds(monthly._month_of(now))
    last_month = month_bounds(monthly._month_of(this_month[0] - timedelta(days=1)))
    async with commit_factory() as setup:
        creator, content = await _creator(setup)
        player = await _player(setup)
        user_ids.extend([creator.id, player.user.id])
        await setup.commit()
        await _application(setup, creator.id, accrual_start_at=last_month[0])
        spent = await _use(setup, player, content, 44, last_month[0] + timedelta(days=14))
        await setup.commit()

    async with db_engine.connect() as locker:
        transaction = await locker.begin()
        await locker.execute(
            select(CloverSpendAllocation.id).where(CloverSpendAllocation.spend_ledger_id == spent).with_for_update()
        )
        confirmed = await asyncio.wait_for(
            run_monthly(commit_factory, now=this_month[0] + timedelta(days=2, hours=1)), timeout=10
        )
        refunding = AsyncSession(bind=locker, expire_on_commit=False)
        assert (
            await refund_spend(refunding, user_id=player.user.id, spend_ledger_id=spent, amount=22, kind="chat_refund")
            is not None
        )
        await refunding.flush()
        await transaction.commit()
        await refunding.close()

    assert isinstance(confirmed, list) and confirmed[-1].total_amount_krw == 6
    await run_monthly(commit_factory, now=this_month[1] + timedelta(days=2, hours=1))
    async with commit_factory() as check:
        rows = await _monthly_rows(check, creator)
    assert [(row.period_month, row.refunded_units, row.amount_krw) for row in rows] == [
        (last_month[0].date(), 0, 6),
        (this_month[0].date(), 22, -3),
    ]


# ── 마이그레이션 ──────────────────────────────────────────────────────────────
def _load_batch_runs_revision() -> ModuleType:
    (path,) = (Path(__file__).resolve().parents[1] / "migrations" / "versions").glob("204652ae3d92_*.py")
    spec = importlib.util.spec_from_file_location("_migration_204652ae3d92", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BATCH_RUNS_REVISION = _load_batch_runs_revision()


async def test_run_records_block_the_downgrade_before_any_change(ddl_engine: AsyncEngine) -> None:
    """실행 기록이 있으면 테이블을 지우지 않고 멈춘다 — 지우면 배치가 끝난 달을 다시 확정하려 든다."""

    def downgrade(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            _BATCH_RUNS_REVISION.downgrade()

    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    "INSERT INTO creator_payout_batch_runs (period_month, creator_count, total_amount_krw,"
                    " unattributed_spend_count, refund_event_mismatch_count) VALUES ('2026-10-01', 0, 0, 0, 0)"
                )
            )
            with pytest.raises(RuntimeError, match="배치가 끝난 달을 다시 확정"):
                await connection.run_sync(downgrade)
            still_there = await connection.scalar(text("SELECT count(*) FROM creator_payout_batch_runs"))
        finally:
            await transaction.rollback()

    assert still_there == 1


async def test_the_batch_lock_holds_after_the_first_creator_is_committed(
    committed: tuple[Factory, list[uuid.UUID]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """크리에이터별 커밋이 배치 잠금을 풀지 않는다 — 첫 크리에이터를 커밋한 직후에 들어온 두 번째 실행도 "다른 실행 중"이고,
    첫 배치는 두 사람을 다 확정한다. 진짜로 커밋되는 커넥션들이라 잠금이 어느 트랜잭션에 걸렸는지가 그대로 드러난다."""
    commit_factory, user_ids = committed
    now = datetime.now(UTC)
    last_month = month_bounds(monthly._month_of(month_bounds(monthly._month_of(now))[0] - timedelta(days=1)))
    batch_now = last_month[1] + timedelta(days=2, hours=1)
    async with commit_factory() as setup:
        player = await _player(setup)
        user_ids.append(player.user.id)
        creators = []
        for _ in range(2):
            creator, content = await _creator(setup)
            user_ids.append(creator.id)
            creators.append((creator, content))
        await setup.commit()
        for creator, content in creators:
            await _application(setup, creator.id, accrual_start_at=last_month[0])
            await _use(setup, player, content, 22, last_month[0] + timedelta(days=14))
        await setup.commit()

    settle = monthly._settle_creator
    overlapping: list[RunOutcome] = []

    async def settle_then_overlap(db: AsyncSession, creator_id: uuid.UUID, month: date) -> None:
        await settle(db, creator_id, month)
        # 처음 한 번만 겹친다. 두 번째 실행이 다시 이 훅을 타면 자기 자신과 회원 행 잠금을 기다리게 된다.
        if monthly._settle_creator is settle_then_overlap:
            monkeypatch.setattr(monthly, "_settle_creator", settle)
            overlapping.append(await run_monthly(commit_factory, now=batch_now))

    monkeypatch.setattr(monthly, "_settle_creator", settle_then_overlap)
    first = await run_monthly(commit_factory, now=batch_now)

    assert overlapping == ["busy"]
    assert isinstance(first, list) and [(r.period_month, r.creator_count) for r in first] == [(last_month[0].date(), 2)]
