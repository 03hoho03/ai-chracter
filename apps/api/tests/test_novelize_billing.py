"""소설화 과금 — 작업 생성과 함께 하는 선차감, 단일 환불, 조건부 상태 전이.

앞 절은 `db_session` 커넥션 위에 SAVEPOINT 세션(`_service_session`)을 열어 서비스 함수를 부른다. 서비스가 거절할
때 스스로 롤백하는데, 테스트 셋업과 같은 세션이면 그 롤백이 셋업까지 지운다 — SAVEPOINT 세션이면 셋업은 남고
서비스가 쓴 것만 되돌아간다.

마지막 절(경쟁)은 롤백되지 않는 독립 커넥션 둘을 쓴다. 한 커넥션 위에서는 두 트랜잭션이 락을 다툴 수 없어
"한 번만"이 순차 실행으로도 성립해 버린다. 그래서 경쟁 테스트는 상대 트랜잭션에 실제로 막히는 것(`_assert_blocked`)을
먼저 단언한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.core.rate_limit import KST, seconds_until_kst_midnight
from api.db.models import Novel, NovelJob, User
from api.db.models.novel import NovelJobKind, NovelJobStatus
from api.db.models.clover import CloverLedger, CloverLot
from api.novelize import billing
from api.novelize.deletion import delete_novels
from factories import _assert_blocked, _make_user_with_clover_lot


def _detail(exc: HTTPException) -> object:
    """`HTTPException.detail` 은 `str` 로 선언돼 있어 dict 와 비교하면 mypy 가 막는다 — 실제로는 dict 를 싣는다."""
    return exc.detail


def _service_session(db_session: AsyncSession) -> AsyncSession:
    return AsyncSession(bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False)


async def _make_novel(db: AsyncSession, user_id: uuid.UUID) -> Novel:
    novel = Novel(
        user_id=user_id, content_id=uuid.uuid4(), content_type="character", content_title="원작", character_name="인물"
    )
    db.add(novel)
    await db.flush()
    return novel


def _chapter_job(novel: Novel, *, kind: NovelJobKind = "chapter_generate", start_message_id: uuid.UUID) -> NovelJob:
    now = datetime.now(UTC)
    return NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind=kind,
        start_message_id=start_message_id,
        start_message_created_at=now,
        end_message_id=uuid.uuid4(),
        end_message_created_at=now,
    )


def _ai_edit_job(novel: Novel) -> NovelJob:
    return NovelJob(novel_id=novel.id, user_id=novel.user_id, kind="ai_edit", paragraph_start=0, paragraph_end=1)


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    """금액 오름차순(차감 먼저) — 한 트랜잭션 안의 행은 `created_at` 이 같아 시각으로는 순서가 서지 않는다."""
    rows = await db.execute(
        select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.amount, CloverLedger.kind)
    )
    return [(kind, amount) for kind, amount in rows.all()]


async def _balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db.scalar(select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


async def _lot_sum(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await db.scalar(select(func.coalesce(func.sum(CloverLot.remaining), 0)).where(CloverLot.user_id == user_id))
        or 0
    )


async def _job_count(db: AsyncSession, novel_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(NovelJob).where(NovelJob.novel_id == novel_id)) or 0)


async def _owner(db_session: AsyncSession, balance: int = 100, **overrides: object) -> User:
    return await _make_user_with_clover_lot(db_session, clover_balance=balance, **overrides)


# ── 단가 ────────────────────────────────────────────────────────────────────
def test_job_price_reads_the_constant_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """단가가 바뀌면 다음 호출부터 바로 바뀐 값을 낸다 — 정의 시점에 값을 붙잡아 두면 바꿔도 옛 값이 나간다."""
    assert billing.job_price("chapter_generate") == 20
    assert billing.job_price("chapter_regenerate") == 20
    assert billing.job_price("ai_edit") == 5
    monkeypatch.setattr(clover, "NOVELIZE_CHAPTER_REGENERATE_COST", 33)
    assert billing.job_price("chapter_regenerate") == 33


# ── 차감 + 작업 생성 ────────────────────────────────────────────────────────
async def test_create_charges_and_inserts_a_queued_job(db_session: AsyncSession) -> None:
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)

    async with _service_session(db_session) as s:
        job = await billing.create_charged_job(
            s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=20, now=datetime.now(UTC)
        )

    stored = await db_session.get(NovelJob, job.id)
    assert stored is not None
    assert (stored.status, stored.charged_amount, stored.refunded_at) == ("queued", 20, None)
    assert stored.heartbeat_at is not None
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20)]
    assert await _balance(db_session, owner.id) == 80
    assert await _lot_sum(db_session, owner.id) == 80


async def test_create_charges_an_exempt_account_too(db_session: AsyncSession) -> None:
    """채팅·이미지 상한을 면제받는 계정도 소설화는 똑같이 낸다 — 면제 분기가 섞이면 차감이 0 이 된다."""
    owner = await _owner(db_session, rate_limit_exempt=True)
    novel = await _make_novel(db_session, owner.id)

    async with _service_session(db_session) as s:
        await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=5, now=datetime.now(UTC))

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -5)]
    assert await _balance(db_session, owner.id) == 95


async def test_create_rejects_a_stale_expected_cost_before_charging(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)
    monkeypatch.setattr(clover, "NOVELIZE_CHAPTER_GENERATE_COST", 25)

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=20, now=datetime.now(UTC)
            )

    assert caught.value.status_code == 409
    assert _detail(caught.value) == {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": 25}
    assert await _job_count(db_session, novel.id) == 0
    assert await _ledger(db_session, owner.id) == []


async def test_create_without_enough_clover_is_429_and_leaves_nothing(db_session: AsyncSession) -> None:
    owner = await _owner(db_session, balance=19)
    novel = await _make_novel(db_session, owner.id)
    now = datetime.now(UTC)

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=20, now=now
            )

    assert caught.value.status_code == 429
    assert _detail(caught.value) == {
        "code": "CLOVER_REQUIRED",
        "retryAfterSeconds": seconds_until_kst_midnight(now),
        "window": "novelize",
    }
    assert await _job_count(db_session, novel.id) == 0
    assert await _ledger(db_session, owner.id) == []
    assert await _balance(db_session, owner.id) == 19


async def test_create_while_a_job_is_active_is_409_and_charges_nothing(db_session: AsyncSession) -> None:
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)
    db_session.add(NovelJob(novel_id=novel.id, user_id=owner.id, kind="ai_edit", status="running", charged_amount=5))
    await db_session.flush()

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=5, now=datetime.now(UTC))

    assert caught.value.status_code == 409
    assert _detail(caught.value) == {"code": "NOVEL_JOB_IN_PROGRESS"}
    assert await _ledger(db_session, owner.id) == []
    assert await _balance(db_session, owner.id) == 100


async def test_daily_chapter_limit_counts_only_todays_live_attempts_at_the_same_start(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 시작 메시지의 오늘 장 생성·재생성 중 진행 중·성공만 센다. 실패(환불된 것)·어제 것·다른 시작 메시지는
    세지 않는다. 상한 3 이면 이미 2 건일 때 통과하고 3 건일 때 거절한다."""
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 3)
    owner = await _owner(db_session, balance=200)
    novel = await _make_novel(db_session, owner.id)
    start = uuid.uuid4()
    now = datetime.now(UTC)
    today_start = datetime.combine(now.astimezone(KST).date(), time.min, tzinfo=KST)

    def done(
        status: NovelJobStatus, *, kind: NovelJobKind = "chapter_regenerate", start_message_id: uuid.UUID = start
    ) -> NovelJob:
        job = _chapter_job(novel, kind=kind, start_message_id=start_message_id)
        job.status = status
        job.charged_amount = 20
        return job

    yesterday = done("succeeded")
    yesterday.created_at = today_start - timedelta(seconds=1)
    failed = done("failed")
    db_session.add_all(
        [
            done("succeeded", kind="chapter_generate"),
            yesterday,
            failed,
            done("succeeded", start_message_id=uuid.uuid4()),
        ]
    )
    await db_session.flush()

    async def attempt() -> None:
        async with _service_session(db_session) as s:
            job = await billing.create_charged_job(
                s, job=_chapter_job(novel, kind="chapter_regenerate", start_message_id=start), expected_cost=20, now=now
            )
        await db_session.execute(update(NovelJob).where(NovelJob.id == job.id).values(status="succeeded"))

    await attempt()  # 1 건 있음 → 통과
    await attempt()  # 2 건 있음 → 통과

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_chapter_job(novel, kind="chapter_regenerate", start_message_id=start), expected_cost=20, now=now
            )

    assert caught.value.status_code == 429
    assert _detail(caught.value) == {
        "code": "USER_LIMIT",
        "retryAfterSeconds": seconds_until_kst_midnight(now),
        "window": "novelize",
    }
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20), ("novelize_spend", -20)]


async def test_ai_edit_is_outside_the_daily_chapter_limit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 0)
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)

    async with _service_session(db_session) as s:
        await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=5, now=datetime.now(UTC))

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -5)]


# ── 단일 환불 ───────────────────────────────────────────────────────────────
async def _charged_job(db_session: AsyncSession, balance: int = 100) -> tuple[User, NovelJob]:
    owner = await _owner(db_session, balance=balance)
    novel = await _make_novel(db_session, owner.id)
    async with _service_session(db_session) as s:
        job = await billing.create_charged_job(
            s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=20, now=datetime.now(UTC)
        )
    return owner, job


async def test_refund_fails_the_job_and_returns_the_charge_once(db_session: AsyncSession) -> None:
    owner, job = await _charged_job(db_session)

    async with _service_session(db_session) as s:
        first = await billing.refund_job(s, job_id=job.id, failure_code="llm_error")
        await s.commit()
    async with _service_session(db_session) as s:
        second = await billing.refund_job(s, job_id=job.id, failure_code="expired")
        await s.commit()

    assert (first, second) == (20, None)
    stored = await db_session.get(NovelJob, job.id, populate_existing=True)
    assert stored is not None
    assert (stored.status, stored.failure_code) == ("failed", "llm_error")
    assert stored.refunded_at is not None and stored.finished_at is not None
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20), ("novelize_refund", 20)]
    # 원장 합 = 잔액 = 로트 잔여 합.
    assert await _balance(db_session, owner.id) == 100 == await _lot_sum(db_session, owner.id)


async def test_refund_after_success_does_nothing(db_session: AsyncSession) -> None:
    owner, job = await _charged_job(db_session)
    async with _service_session(db_session) as s:
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        assert (
            await billing.transition_job(s, job_id=job.id, expected=("running",), values={"status": "succeeded"}) == 20
        )
        await s.commit()

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") is None
        await s.commit()

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20)]


async def test_success_after_refund_does_nothing(db_session: AsyncSession) -> None:
    _, job = await _charged_job(db_session)
    async with _service_session(db_session) as s:
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") == 20
        assert (
            await billing.transition_job(s, job_id=job.id, expected=("running",), values={"status": "succeeded"})
            is None
        )
        await s.commit()

    stored = await db_session.get(NovelJob, job.id, populate_existing=True)
    assert stored is not None and stored.status == "failed"


async def test_refund_whose_commit_failed_is_retried_once_by_the_next_caller(db_session: AsyncSession) -> None:
    """환불 트랜잭션이 커밋되지 못하면 작업은 진행 중으로 남고, 다음에 같은 함수를 부른 쪽(만료 정리)이 한 번 환불한다."""
    owner, job = await _charged_job(db_session)

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="llm_error") == 20
        await s.rollback()  # 커밋 실패 대신

    stored = await db_session.get(NovelJob, job.id, populate_existing=True)
    assert stored is not None and stored.status == "queued"

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") == 20
        await s.commit()

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20), ("novelize_refund", 20)]


async def test_refund_of_a_job_erased_with_its_novel_is_harmless(db_session: AsyncSession) -> None:
    """탈퇴·소설 삭제로 작업 행이 먼저 사라졌으면 뒤늦은 환불(백그라운드 실행의 실패 처리)은 아무것도 하지 않는다."""
    owner, job = await _charged_job(db_session)
    await delete_novels(db_session, [job.novel_id])
    await db_session.flush()

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="llm_error") is None
        await s.commit()

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20)]


async def test_refund_active_jobs_before_deleting_a_novel_refunds_once(db_session: AsyncSession) -> None:
    owner, job = await _charged_job(db_session)

    async with _service_session(db_session) as s:
        assert await billing.refund_active_jobs(s, novel_id=job.novel_id, failure_code="internal") == 20
        assert await billing.refund_active_jobs(s, novel_id=job.novel_id, failure_code="internal") == 0
        await delete_novels(s, [job.novel_id])
        await s.commit()

    assert await _job_count(db_session, job.novel_id) == 0
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20), ("novelize_refund", 20)]
    assert await _balance(db_session, owner.id) == 100


# ── 경쟁 (독립 커넥션) ──────────────────────────────────────────────────────
_MARKER_DOMAIN = "novelize-billing-independent.test"


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """커밋되는 독립 커넥션 세션 팩토리. 여기서 쓴 행은 롤백되지 않으므로 이 표지 도메인의 유저와 그 아래 행을 끝에서
    직접 지운다(`test_clover_concurrency.py` 의 같은 이름 픽스처와 같은 방식)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await delete_novels(cleanup, novel_ids)
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as s:
        owner = await _make_user_with_clover_lot(s, clover_balance=100, email=f"nv-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        novel = await _make_novel(s, owner.id)
        await s.commit()
    return owner.id, novel.id


async def _independent_ledger(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> list[tuple[str, int]]:
    async with factory() as s:
        return await _ledger(s, user_id)


async def test_concurrent_create_for_the_same_novel_waits_on_the_user_and_charges_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """같은 소설에 두 요청이 겹치면 뒤 요청은 사용자 행에서 기다렸다가, 앞 요청이 커밋한 진행 중 작업을 보고 409 다.
    사용자 행을 먼저 잠그지 않으면 뒤 요청이 진행 중 작업을 못 본 채 INSERT 해 부분 유니크 위반(500)이 된다."""
    user_id, novel_id = await _seed(independent_factory)
    first = independent_factory()
    try:
        # 앞 요청이 하는 일을 그대로: 사용자 잠금 → 진행 중 작업 INSERT, 아직 커밋 전.
        await first.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
        first.add(NovelJob(novel_id=novel_id, user_id=user_id, kind="ai_edit", status="queued", charged_amount=5))
        await first.flush()

        async def second_request() -> object:
            async with independent_factory() as s:
                novel = await s.get(Novel, novel_id)
                assert novel is not None
                try:
                    return await billing.create_charged_job(
                        s, job=_ai_edit_job(novel), expected_cost=5, now=datetime.now(UTC)
                    )
                except HTTPException as exc:
                    return exc

        task = asyncio.ensure_future(second_request())
        await _assert_blocked(task)
        await first.commit()
        result = await task
    finally:
        await first.close()

    assert isinstance(result, HTTPException)
    assert (result.status_code, _detail(result)) == (409, {"code": "NOVEL_JOB_IN_PROGRESS"})
    assert await _independent_ledger(independent_factory, user_id) == []


async def test_refund_racing_a_success_loses_and_does_not_refund(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """성공 전이가 작업 행을 잡은 채 커밋 전이면 환불은 그 행에서 기다리고, 커밋 뒤에는 조건(진행 중)이 맞지 않아
    아무것도 하지 않는다. 조건 없이 덮어쓰면 성공한 작업이 실패로 바뀌고 환불까지 나간다."""
    user_id, novel_id = await _seed(independent_factory)
    async with independent_factory() as s:
        novel = await s.get(Novel, novel_id)
        assert novel is not None
        job = await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=5, now=datetime.now(UTC))
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        await s.commit()

    winner = independent_factory()
    try:
        assert (
            await billing.transition_job(winner, job_id=job.id, expected=("running",), values={"status": "succeeded"})
            == 5
        )

        async def late_refund() -> int | None:
            async with independent_factory() as s:
                refunded = await billing.refund_job(s, job_id=job.id, failure_code="expired")
                await s.commit()
                return refunded

        task = asyncio.ensure_future(late_refund())
        await _assert_blocked(task)
        await winner.commit()
        assert await task is None
    finally:
        await winner.close()

    assert await _independent_ledger(independent_factory, user_id) == [("novelize_spend", -5)]


async def test_two_concurrent_refunds_of_one_job_refund_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """정리 경로와 실행 경로의 실패 처리가 겹쳐도 환불은 한 번이다 — 뒤 호출은 사용자 행에서 기다렸다가 이미 실패로
    바뀐 작업을 보고 물러난다."""
    user_id, novel_id = await _seed(independent_factory)
    async with independent_factory() as s:
        novel = await s.get(Novel, novel_id)
        assert novel is not None
        job = await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=5, now=datetime.now(UTC))

    first = independent_factory()
    try:
        assert await billing.refund_job(first, job_id=job.id, failure_code="llm_error") == 5

        async def second_refund() -> int | None:
            async with independent_factory() as s:
                refunded = await billing.refund_job(s, job_id=job.id, failure_code="expired")
                await s.commit()
                return refunded

        task = asyncio.ensure_future(second_refund())
        await _assert_blocked(task)
        await first.commit()
        assert await task is None
    finally:
        await first.close()

    assert await _independent_ledger(independent_factory, user_id) == [("novelize_spend", -5), ("novelize_refund", 5)]
