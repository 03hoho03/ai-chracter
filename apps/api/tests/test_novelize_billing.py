"""소설화 과금 — 작업 생성과 함께 하는 선차감, 단일 환불, 조건부 상태 전이.

앞 절은 `db_session` 커넥션 위에 SAVEPOINT 세션(`_service_session`)을 열어 서비스 함수를 부른다. 서비스가 거절할
때 스스로 롤백하는데, 테스트 셋업과 같은 세션이면 그 롤백이 셋업까지 지운다 — SAVEPOINT 세션이면 셋업은 남고
서비스가 쓴 것만 되돌아간다.

마지막 절(경쟁)은 롤백되지 않는 독립 커넥션 둘을 쓴다. 한 커넥션 위에서는 두 트랜잭션이 락을 다툴 수 없어
"한 번만"이 순차 실행으로도 성립해 버린다. 그래서 경쟁 테스트는 상대 트랜잭션에 실제로 막히는 것(`_assert_blocked`)을
먼저 단언한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core import clover
from api.core.config import settings
from api.core.rate_limit import KST, seconds_until_kst_midnight
from api.db.models import Content, Novel, NovelChapter, NovelChapterRevision, NovelJob, User
from api.db.models.novel import NovelBatch
from api.db.models.novel import NovelJobKind, NovelJobStatus
from api.db.models.clover import (
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
)
from api.llm.chat_models import ChatModelId
from api.novelize import billing, runner
from api.novelize.inputs import ChapterInput
from api.novelize.output import ParsedBatch, ParsedEpisode
from api.novelize.prompts import NovelizePrompt
from api.novelize.batches import ensure_batches
from api.novelize.deletion import delete_batch, delete_novels
from api.novelize.router import delete_last_novel_chapter, delete_novel
from factories import _assert_blocked, _clover_lots, _make_draft_content, _make_user_with_clover_lot

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")


def _detail(exc: HTTPException) -> object:
    """`HTTPException.detail` 은 `str` 로 선언돼 있어 dict 와 비교하면 mypy 가 막는다 — 실제로는 dict 를 싣는다."""
    return exc.detail


def _service_session(db_session: AsyncSession) -> AsyncSession:
    return AsyncSession(bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False)


async def _make_novel(db: AsyncSession, user_id: uuid.UUID) -> Novel:
    """`user_id` 의 소설 한 권. 원작은 그 사람의 초안이다 — 차감이 사용처에 원작 소유자를 적으므로 작품 행이 있어야 한다."""
    content = await _make_draft_content(db, creator_user_id=user_id)
    novel = Novel(
        user_id=user_id, content_id=content.id, content_type="character", content_title="원작", character_name="인물"
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


async def _batch(db: AsyncSession, novel: Novel, *, episodes: int, turns: int = 1) -> list[NovelChapter]:
    """화 `episodes` 개짜리 묶음 하나(원문 턴 `turns` 개)를 flush 하고 그 화들을 돌려준다."""
    now = datetime.now(UTC)
    segment = {
        "start_message_id": uuid.uuid4(),
        "start_message_created_at": now,
        "end_message_id": uuid.uuid4(),
        "end_message_created_at": now,
        "assistant_message_count": turns,
        "source_hash": "0" * 64,
    }
    ordinal = int(await db.scalar(select(func.count()).select_from(NovelBatch).where(NovelBatch.novel_id == novel.id)) or 0)
    batch = NovelBatch(novel_id=novel.id, ordinal=ordinal + 1, target_episode_count=episodes, **segment)
    db.add(batch)
    await db.flush()
    first = int(await db.scalar(select(func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel.id)) or 0)
    chapters = [
        NovelChapter(novel_id=novel.id, ordinal=first + i + 1, batch_id=batch.id, episode_index=i, **segment)
        for i in range(episodes)
    ]
    db.add_all(chapters)
    await db.flush()
    return chapters


def _regenerate_job(novel: Novel, chapter: NovelChapter, model: str = "gemini") -> NovelJob:
    job = _chapter_job(novel, kind="chapter_regenerate", start_message_id=chapter.start_message_id)
    job.chapter_id = chapter.id
    job.model = model
    return job


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
    assert billing.job_price("chapter_generate") == 40
    assert billing.job_price("chapter_regenerate") == 40
    assert billing.job_price("ai_edit") == 20
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 33)
    assert billing.job_price("chapter_regenerate") == 33


@pytest.mark.parametrize(
    ("model", "unit"),
    [pytest.param("gemini", 40, id="gemini"), pytest.param("sonnet", 105, id="sonnet"), pytest.param("opus", 170, id="opus")],
)
def test_job_price_is_the_models_episode_price_times_the_episode_count(model: ChatModelId, unit: int) -> None:
    """생성·다시 만들기는 화 수만큼 낸다. AI 수정은 화 하나의 문단을 고치므로 화 수와 모델에 매이지 않는다."""
    for kind in ("chapter_generate", "chapter_regenerate"):
        assert [billing.job_price(kind, model, n) for n in (1, 3)] == [unit, 3 * unit]
    assert billing.job_price("ai_edit", model, 3) == 20


def test_chain_price_takes_the_models_episode_cap_for_every_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """묶음 경계를 아직 모르므로 묶음마다 그 모델이 낼 수 있는 가장 많은 화를 받는다."""
    monkeypatch.setattr(settings, "novelize_k_max_gemini", 3)
    monkeypatch.setattr(settings, "novelize_k_max_opus", 2)
    assert [billing.chain_price("gemini", n) for n in (1, 5)] == [120, 600]
    assert [billing.chain_price("opus", n) for n in (1, 5)] == [340, 1700]
    with pytest.raises(ValueError):
        billing.job_price("chain_generate")


@pytest.mark.parametrize(
    ("charged", "target", "delivered", "refund"),
    [
        pytest.param(120, 3, 3, 0, id="exactly-the-target"),
        pytest.param(120, 3, 2, 40, id="one-short"),
        pytest.param(120, 3, 1, 80, id="two-short"),
        pytest.param(120, 3, 5, 0, id="more-is-accepted-free"),
        pytest.param(340, 2, 1, 170, id="opus-one-short"),
        pytest.param(0, 3, 1, 0, id="chain-child-charged-nothing"),
    ],
)
def test_shortfall_refund_returns_only_the_missing_episodes(charged: int, target: int, delivered: int, refund: int) -> None:
    assert billing.shortfall_refund(charged_amount=charged, target=target, delivered=delivered) == refund


# ── 차감 + 작업 생성 ────────────────────────────────────────────────────────
async def test_create_charges_and_inserts_a_queued_job(db_session: AsyncSession) -> None:
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)

    async with _service_session(db_session) as s:
        job = await billing.create_charged_job(
            s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=40, now=datetime.now(UTC)
        )

    stored = await db_session.get(NovelJob, job.id)
    assert stored is not None
    assert (stored.status, stored.charged_amount, stored.refunded_at) == ("queued", 40, None)
    assert stored.heartbeat_at is not None
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40)]
    assert await _balance(db_session, owner.id) == 60
    assert await _lot_sum(db_session, owner.id) == 60


async def test_create_charges_an_exempt_account_too(db_session: AsyncSession) -> None:
    """채팅·이미지 상한을 면제받는 계정도 소설화는 똑같이 낸다 — 면제 분기가 섞이면 차감이 0 이 된다."""
    owner = await _owner(db_session, rate_limit_exempt=True)
    novel = await _make_novel(db_session, owner.id)

    async with _service_session(db_session) as s:
        await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC))

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20)]
    assert await _balance(db_session, owner.id) == 80


async def test_create_rejects_a_stale_expected_cost_before_charging(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_COST", 25)

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=40, now=datetime.now(UTC)
            )

    assert caught.value.status_code == 409
    assert _detail(caught.value) == {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": 25}
    assert await _job_count(db_session, novel.id) == 0
    assert await _ledger(db_session, owner.id) == []


async def test_generate_is_charged_for_its_target_episode_count(db_session: AsyncSession) -> None:
    owner = await _owner(db_session, balance=200)
    novel = await _make_novel(db_session, owner.id)
    job = _chapter_job(novel, start_message_id=uuid.uuid4())
    job.episode_count_target = 3

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(s, job=job, expected_cost=40, now=datetime.now(UTC))
    async with _service_session(db_session) as s:
        stored = await billing.create_charged_job(s, job=job, expected_cost=120, now=datetime.now(UTC))

    assert _detail(caught.value) == {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": 120}
    assert (stored.charged_amount, stored.episode_count_target) == (120, 3)
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -120)]


async def test_regenerate_is_charged_for_the_whole_batch_and_records_it(db_session: AsyncSession) -> None:
    """화 하나를 골라 다시 만들어도 그 화가 든 묶음 전체를 다시 쓴다 — 금액은 묶음의 화 수 × 화 단가이고, 작업에 그
    묶음과 화 수를 싣는다. 화면이 화 하나 값으로 확인했으면 409 가 묶음 금액을 알려 준다."""
    owner = await _owner(db_session, balance=200)
    novel = await _make_novel(db_session, owner.id)
    chapters = await _batch(db_session, novel, episodes=3)

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_regenerate_job(novel, chapters[1]), expected_cost=40, now=datetime.now(UTC)
            )
    async with _service_session(db_session) as s:
        job = await billing.create_charged_job(
            s, job=_regenerate_job(novel, chapters[1]), expected_cost=120, now=datetime.now(UTC)
        )

    assert _detail(caught.value) == {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": 120}
    stored = await db_session.get_one(NovelJob, job.id)
    assert (stored.batch_id, stored.episode_count_target, stored.charged_amount) == (chapters[1].batch_id, 3, 120)
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -120)]


@pytest.mark.parametrize(
    ("model", "episodes", "turns", "reason"),
    [
        pytest.param("opus", 2, 10, "too_many_episodes", id="opus-two-episodes"),
        pytest.param("sonnet", 1, 21, "too_many_turns", id="sonnet-21-turns"),
        pytest.param("opus", 1, 21, "too_many_turns", id="opus-21-turns"),
    ],
)
async def test_regenerating_with_a_model_that_cannot_hold_the_batch_is_409_before_charging(
    db_session: AsyncSession, model: str, episodes: int, turns: int, reason: str
) -> None:
    """다시 만들기는 화 수를 바꿀 수 없으므로, 고른 모델의 화 수·턴 상한을 넘는 묶음은 차감 전에 거절한다."""
    owner = await _owner(db_session, balance=1000)
    novel = await _make_novel(db_session, owner.id)
    chapters = await _batch(db_session, novel, episodes=episodes, turns=turns)

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_regenerate_job(novel, chapters[0], model), expected_cost=170 * episodes, now=datetime.now(UTC)
            )

    assert caught.value.status_code == 409
    assert _detail(caught.value) == {"code": "NOVEL_MODEL_INELIGIBLE", "reason": reason}
    assert await _job_count(db_session, novel.id) == 0
    assert await _ledger(db_session, owner.id) == []


async def test_regenerating_a_batch_with_no_episodes_is_refused_before_charging(db_session: AsyncSession) -> None:
    """화가 없는 묶음(옛 판 코드가 화만 지운 경우)을 다시 만들면 0 클로버 작업이 묶음 전체를 다시 쓰려 든다 — 없는
    묶음과 같은 404 다."""
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)
    (chapter,) = await _batch(db_session, novel, episodes=1)
    batch_id = chapter.batch_id
    await db_session.execute(delete(NovelChapter).where(NovelChapter.id == chapter.id))
    job = _chapter_job(novel, kind="chapter_regenerate", start_message_id=uuid.uuid4())
    job.batch_id = batch_id

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(s, job=job, expected_cost=0, now=datetime.now(UTC))

    assert (caught.value.status_code, _detail(caught.value)) == (404, {"code": "NOVEL_BATCH_NOT_FOUND"})
    assert await _ledger(db_session, owner.id) == []


async def test_a_model_at_both_caps_can_regenerate_the_batch(db_session: AsyncSession) -> None:
    owner = await _owner(db_session, balance=1000)
    novel = await _make_novel(db_session, owner.id)
    (chapter,) = await _batch(db_session, novel, episodes=1, turns=20)

    async with _service_session(db_session) as s:
        await billing.create_charged_job(
            s, job=_regenerate_job(novel, chapter, "opus"), expected_cost=170, now=datetime.now(UTC)
        )

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -170)]


async def test_create_without_enough_clover_is_429_and_leaves_nothing(db_session: AsyncSession) -> None:
    owner = await _owner(db_session, balance=19)
    novel = await _make_novel(db_session, owner.id)
    now = datetime.now(UTC)

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(
                s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=40, now=now
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
    db_session.add(NovelJob(novel_id=novel.id, user_id=owner.id, kind="ai_edit", status="running", charged_amount=20))
    await db_session.flush()

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC))

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
        job.charged_amount = 40
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

    (chapter,) = await _batch(db_session, novel, episodes=1)

    def regenerate() -> NovelJob:
        job = _chapter_job(novel, kind="chapter_regenerate", start_message_id=start)
        job.chapter_id = chapter.id
        return job

    async def attempt() -> None:
        async with _service_session(db_session) as s:
            job = await billing.create_charged_job(s, job=regenerate(), expected_cost=40, now=now)
        await db_session.execute(update(NovelJob).where(NovelJob.id == job.id).values(status="succeeded"))

    await attempt()  # 1 건 있음 → 통과
    await attempt()  # 2 건 있음 → 통과

    async with _service_session(db_session) as s:
        with pytest.raises(HTTPException) as caught:
            await billing.create_charged_job(s, job=regenerate(), expected_cost=40, now=now)

    assert caught.value.status_code == 429
    assert _detail(caught.value) == {
        "code": "USER_LIMIT",
        "retryAfterSeconds": seconds_until_kst_midnight(now),
        "window": "novelize",
    }
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40), ("novelize_spend", -40)]


async def test_ai_edit_is_outside_the_daily_chapter_limit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 0)
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)

    async with _service_session(db_session) as s:
        await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC))

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -20)]


# ── 단일 환불 ───────────────────────────────────────────────────────────────
async def _charged_job(db_session: AsyncSession, balance: int = 100) -> tuple[User, NovelJob]:
    owner = await _owner(db_session, balance=balance)
    novel = await _make_novel(db_session, owner.id)
    async with _service_session(db_session) as s:
        job = await billing.create_charged_job(
            s, job=_chapter_job(novel, start_message_id=uuid.uuid4()), expected_cost=40, now=datetime.now(UTC)
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

    assert (first, second) == (40, None)
    stored = await db_session.get(NovelJob, job.id, populate_existing=True)
    assert stored is not None
    assert (stored.status, stored.failure_code) == ("failed", "llm_error")
    assert stored.refunded_at is not None and stored.finished_at is not None
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40), ("novelize_refund", 40)]
    # 원장 합 = 잔액 = 로트 잔여 합.
    assert await _balance(db_session, owner.id) == 100 == await _lot_sum(db_session, owner.id)


async def test_refund_returns_only_what_a_chain_parent_has_not_used(db_session: AsyncSession) -> None:
    """연쇄 부모는 성공한 묶음 몫을 이미 썼다 — 실패하면 쓰지 않은 몫만 돌려주고 그 금액을 행에 적는다."""
    owner, job = await _charged_job(db_session)
    await db_session.execute(update(NovelJob).where(NovelJob.id == job.id).values(consumed_amount=15))
    await db_session.commit()

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="llm_error") == 25
        await s.commit()

    stored = await db_session.get_one(NovelJob, job.id, populate_existing=True)
    assert (stored.status, stored.refunded_amount, stored.refunded_at is not None) == ("failed", 25, True)
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40), ("novelize_refund", 25)]
    assert await _balance(db_session, owner.id) == 85 == await _lot_sum(db_session, owner.id)
    # 쓰지 않은 몫은 깎은 그 로트로 돌아간다(환급 종류의 새 로트가 생기지 않는다).
    assert await _clover_lots(db_session, owner.id) == [("legacy_balance", 85)]


async def test_refund_of_nothing_left_fails_the_job_without_a_refund_record(db_session: AsyncSession) -> None:
    """돌려줄 몫이 0 이면(차감 0 인 연쇄 자식) 실패로만 끝낸다 — 환불 시각을 찍으면 화면이 "환불됨"으로 읽고, 0 원
    원장 행은 내역을 어지럽힌다."""
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)
    child = _chapter_job(novel, start_message_id=uuid.uuid4())
    child.status = "running"
    child.charged_amount = 0
    child.parent_job_id = uuid.uuid4()
    db_session.add(child)
    await db_session.commit()

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=child.id, failure_code="llm_error") == 0
        await s.commit()

    stored = await db_session.get_one(NovelJob, child.id, populate_existing=True)
    assert (stored.status, stored.failure_code, stored.refunded_at, stored.refunded_amount) == (
        "failed",
        "llm_error",
        None,
        None,
    )
    assert await _ledger(db_session, owner.id) == []


async def test_refund_after_success_does_nothing(db_session: AsyncSession) -> None:
    owner, job = await _charged_job(db_session)
    async with _service_session(db_session) as s:
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        moved = await billing.transition_job(s, job_id=job.id, expected=("running",), values={"status": "succeeded"})
        assert moved is not None and moved.charged_amount == 40
        await s.commit()

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") is None
        await s.commit()

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40)]


async def test_success_after_refund_does_nothing(db_session: AsyncSession) -> None:
    _, job = await _charged_job(db_session)
    async with _service_session(db_session) as s:
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") == 40
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
        assert await billing.refund_job(s, job_id=job.id, failure_code="llm_error") == 40
        await s.rollback()  # 커밋 실패 대신

    stored = await db_session.get(NovelJob, job.id, populate_existing=True)
    assert stored is not None and stored.status == "queued"

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") == 40
        await s.commit()

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40), ("novelize_refund", 40)]


async def test_refund_of_a_job_erased_with_its_novel_is_harmless(db_session: AsyncSession) -> None:
    """탈퇴·소설 삭제로 작업 행이 먼저 사라졌으면 뒤늦은 환불(백그라운드 실행의 실패 처리)은 아무것도 하지 않는다."""
    owner, job = await _charged_job(db_session)
    await delete_novels(db_session, [job.novel_id])
    await db_session.flush()

    async with _service_session(db_session) as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="llm_error") is None
        await s.commit()

    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40)]


async def test_refund_active_jobs_before_deleting_a_novel_refunds_once(db_session: AsyncSession) -> None:
    owner, job = await _charged_job(db_session)

    async with _service_session(db_session) as s:
        assert await billing.refund_active_jobs(s, novel_id=job.novel_id, failure_code="internal") == 40
        assert await billing.refund_active_jobs(s, novel_id=job.novel_id, failure_code="internal") == 0
        await delete_novels(s, [job.novel_id])
        await s.commit()

    assert await _job_count(db_session, job.novel_id) == 0
    assert await _ledger(db_session, owner.id) == [("novelize_spend", -40), ("novelize_refund", 40)]
    assert await _balance(db_session, owner.id) == 100


async def test_refund_before_deleting_a_novel_empties_an_ai_edit_instruction(db_session: AsyncSession) -> None:
    """환불한 AI 수정은 지시문·결과 본문을 같은 전이에서 비운다(행은 남긴다) — 소설 삭제 직전의 환불도 같은 함수다."""
    owner = await _owner(db_session)
    novel = await _make_novel(db_session, owner.id)
    edit = _ai_edit_job(novel)
    edit.instruction = "더 쓸쓸하게"
    async with _service_session(db_session) as s:
        job = await billing.create_charged_job(s, job=edit, expected_cost=20, now=datetime.now(UTC))

    async with _service_session(db_session) as s:
        assert await billing.refund_active_jobs(s, novel_id=novel.id, failure_code="internal") == 20
        await s.commit()

    stored = await db_session.get(NovelJob, job.id, populate_existing=True)
    assert stored is not None
    assert (stored.status, stored.instruction, stored.result_text) == ("failed", None, None)


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
            # 환급 행이 배분·원장을, 사용처가 원장을, 배분이 원장·로트를 FK 로 잡으므로 이 순서로 원장보다 먼저 지운다.
            # 작업 행(원장을 가리키는 칸)은 `delete_novels` 가 이미 지웠다.
            spend_ledger_ids = select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
            await cleanup.execute(
                delete(CloverSpendRefund).where(
                    CloverSpendRefund.allocation_id.in_(
                        select(CloverSpendAllocation.id).where(
                            CloverSpendAllocation.spend_ledger_id.in_(spend_ledger_ids)
                        )
                    )
                )
            )
            await cleanup.execute(
                delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(spend_ledger_ids))
            )
            await cleanup.execute(
                delete(CloverSpendAllocation).where(
                    CloverSpendAllocation.spend_ledger_id.in_(
                        select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
                    )
                )
            )
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            # 소설의 원작 초안. 사용처가 FK 로 잡으므로 사용처보다 뒤, 작가보다 앞이다.
            await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


async def _seed(factory: async_sessionmaker[AsyncSession], balance: int = 100) -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as s:
        owner = await _make_user_with_clover_lot(
            s, clover_balance=balance, email=f"nv-{uuid.uuid4()}@{_MARKER_DOMAIN}"
        )
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
        first.add(NovelJob(novel_id=novel_id, user_id=user_id, kind="ai_edit", status="queued", charged_amount=20))
        await first.flush()

        async def second_request() -> object:
            async with independent_factory() as s:
                novel = await s.get(Novel, novel_id)
                assert novel is not None
                try:
                    return await billing.create_charged_job(
                        s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC)
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
        job = await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC))
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        await s.commit()

    winner = independent_factory()
    try:
        moved = await billing.transition_job(
            winner, job_id=job.id, expected=("running",), values={"status": "succeeded"}
        )
        assert moved is not None and moved.charged_amount == 20

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

    assert await _independent_ledger(independent_factory, user_id) == [("novelize_spend", -20)]


async def test_two_concurrent_refunds_of_one_job_refund_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """정리 경로와 실행 경로의 실패 처리가 겹쳐도 환불은 한 번이다 — 뒤 호출은 사용자 행에서 기다렸다가 이미 실패로
    바뀐 작업을 보고 물러난다."""
    user_id, novel_id = await _seed(independent_factory)
    async with independent_factory() as s:
        novel = await s.get(Novel, novel_id)
        assert novel is not None
        job = await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC))

    first = independent_factory()
    try:
        assert await billing.refund_job(first, job_id=job.id, failure_code="llm_error") == 20

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

    assert await _independent_ledger(independent_factory, user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]


async def test_refund_waits_for_a_withdrawal_holding_the_user_instead_of_deadlocking(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """탈퇴는 사용자 행을 잡은 뒤 작업 행을 지운다. 환불이 사용자 행을 먼저 잡지 않고 작업 행부터 바꾸면, 탈퇴는
    작업 행을, 환불은 지급하려는 사용자 행을 서로 기다리는 교착이 되어 한쪽이 교착 오류로 끊긴다. 사용자 행을 먼저
    잡으면 환불이 줄을 서서 기다리고, 탈퇴가 지운 뒤에는 환불할 행이 없어 아무것도 하지 않는다."""
    user_id, novel_id = await _seed(independent_factory)
    async with independent_factory() as s:
        novel = await s.get(Novel, novel_id)
        assert novel is not None
        job = await billing.create_charged_job(s, job=_ai_edit_job(novel), expected_cost=20, now=datetime.now(UTC))

    withdrawal = independent_factory()
    try:
        await withdrawal.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))

        async def refund() -> int | None:
            async with independent_factory() as s:
                refunded = await billing.refund_job(s, job_id=job.id, failure_code="expired")
                await s.commit()
                return refunded

        task = asyncio.ensure_future(refund())
        await _assert_blocked(task)
        await delete_novels(withdrawal, [novel_id])
        await withdrawal.commit()
        assert await task is None
    finally:
        await withdrawal.close()

    assert await _independent_ledger(independent_factory, user_id) == [("novelize_spend", -20)]


async def _running_generate(
    factory: async_sessionmaker[AsyncSession], novel_id: uuid.UUID, *, episodes: int
) -> NovelJob:
    async with factory() as s:
        novel = await s.get_one(Novel, novel_id)
        job = _chapter_job(novel, start_message_id=uuid.uuid4())
        job.episode_count_target = episodes
        job = await billing.create_charged_job(s, job=job, expected_cost=40 * episodes, now=datetime.now(UTC))
        await billing.transition_job(s, job_id=job.id, expected=("queued",), values={"status": "running"})
        await s.commit()
    return job


def _save_two_of_three(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> "asyncio.Task[None]":
    """목표 3화에 2화를 낸 결과 저장을 띄운다 — 모자란 1화를 돌려주므로 사용자 행을 고친다."""
    chapter_input = ChapterInput(
        prompt=NovelizePrompt(system_instruction="", prompt=""),
        room_id=uuid.uuid4(),
        assistant_count=1,
        source_hash="0" * 64,
        episode_count=3,
        writes_novel_title=True,
    )
    episodes = tuple(
        ParsedEpisode(title=f"제목 {n}", summary=f"요약 {n}", characters=("서진",), body=f"본문 {n}") for n in (1, 2)
    )
    return asyncio.create_task(
        runner._save_batch(factory, job_id, chapter_input, ParsedBatch(novel_title="제목", episodes=episodes))
    )


async def _chapter_count(factory: async_sessionmaker[AsyncSession], novel_id: uuid.UUID) -> int:
    async with factory() as s:
        return int(
            await s.scalar(select(func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel_id))
            or 0
        )


async def test_success_save_waits_for_a_withdrawal_holding_the_user_instead_of_deadlocking(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """모자란 화를 돌려주는 성공 저장은 사용자 행을 고친다. 작업 행부터 잡고 사용자 행을 나중에 잡으면, 사용자 행을 쥔
    채 작업 행을 지우는 탈퇴와 서로를 기다려 한쪽이 교착 오류로 끊긴다. 사용자 행을 먼저 잡으면 저장이 줄을 서서
    기다리고, 탈퇴가 지운 뒤에는 저장할 작업이 없어 아무것도 하지 않는다."""
    user_id, novel_id = await _seed(independent_factory, balance=200)
    job = await _running_generate(independent_factory, novel_id, episodes=3)

    withdrawal = independent_factory()
    try:
        await withdrawal.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
        task = _save_two_of_three(independent_factory, job.id)
        await _assert_blocked(task)
        await delete_novels(withdrawal, [novel_id])
        await withdrawal.commit()
        await task
    finally:
        await withdrawal.close()

    assert await _independent_ledger(independent_factory, user_id) == [("novelize_spend", -120)]
    assert await _chapter_count(independent_factory, novel_id) == 0


async def test_success_save_after_expiry_already_refunded_the_job_saves_and_refunds_nothing(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """만료 정리가 사용자 행을 잡고 작업을 실패·환불하는 중이면 성공 저장은 사용자 행에서 기다린다. 정리가 커밋된 뒤
    에는 작업이 이미 실패라 전이가 행을 받지 못하고, 화도 모자란 화 환불도 남기지 않는다 — 환불은 한 번이다."""
    user_id, novel_id = await _seed(independent_factory, balance=200)
    job = await _running_generate(independent_factory, novel_id, episodes=3)

    cleanup = independent_factory()
    try:
        assert await billing.refund_job(cleanup, job_id=job.id, failure_code="expired") == 120
        task = _save_two_of_three(independent_factory, job.id)
        await _assert_blocked(task)
        await cleanup.commit()
        await task
    finally:
        await cleanup.close()

    assert await _independent_ledger(independent_factory, user_id) == [
        ("novelize_spend", -120),
        ("novelize_refund", 120),
    ]
    assert await _chapter_count(independent_factory, novel_id) == 0
    async with independent_factory() as s:
        assert await _balance(s, user_id) == 200 == await _lot_sum(s, user_id)


async def test_expiry_after_a_success_with_a_shortfall_refund_does_nothing_more(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """반대 순서: 모자란 화를 돌려준 성공이 커밋된 뒤의 만료 정리는 작업이 이미 성공이라 아무것도 하지 않는다. 원장은
    차감 하나와 차액 환불 하나뿐이고 잔액과 로트 합이 같다."""
    user_id, novel_id = await _seed(independent_factory, balance=200)
    job = await _running_generate(independent_factory, novel_id, episodes=3)

    await _save_two_of_three(independent_factory, job.id)
    async with independent_factory() as s:
        assert await billing.refund_job(s, job_id=job.id, failure_code="expired") is None
        await s.commit()

    assert await _independent_ledger(independent_factory, user_id) == [
        ("novelize_spend", -120),
        ("novelize_refund", 40),
    ]
    assert await _chapter_count(independent_factory, novel_id) == 2
    async with independent_factory() as s:
        assert await _balance(s, user_id) == 120 == await _lot_sum(s, user_id)


async def test_novel_deletion_waits_for_an_edit_holding_the_chapter_and_removes_its_new_revision(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """직접 수정은 장 행을 잠근 채 새 개정을 넣는다. 삭제가 장을 먼저 잠그지 않으면 개정 DELETE 가 아직 커밋되지 않은
    새 개정을 못 보고 지나가고, 장 DELETE 가 편집 커밋을 기다렸다가 그 개정의 FK 에 걸려 실패한다(삭제 요청 500).
    장을 먼저 잠그면 편집이 끝나기를 기다린 뒤 새 개정까지 지운다."""
    _user_id, novel_id = await _seed(independent_factory)
    now = datetime.now(UTC)
    async with independent_factory() as s:
        chapter = NovelChapter(
            novel_id=novel_id,
            ordinal=1,
            start_message_id=uuid.uuid4(),
            start_message_created_at=now,
            end_message_id=uuid.uuid4(),
            end_message_created_at=now,
            assistant_message_count=1,
            source_hash="0" * 64,
        )
        s.add(chapter)
        await s.flush()
        s.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body="첫 본문", source="generate"))
        await s.commit()

    editor = independent_factory()
    try:
        await editor.execute(select(NovelChapter.id).where(NovelChapter.id == chapter.id).with_for_update(key_share=True))
        editor.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=2, body="고침", source="manual_edit"))
        await editor.flush()

        async def delete_novel() -> None:
            async with independent_factory() as s:
                await delete_novels(s, [novel_id])
                await s.commit()

        task = asyncio.ensure_future(delete_novel())
        await _assert_blocked(task)
        await editor.commit()
        await task
    finally:
        await editor.close()

    async with independent_factory() as s:
        left = await s.scalar(
            select(func.count()).select_from(NovelChapterRevision).where(NovelChapterRevision.chapter_id == chapter.id)
        )
        assert left == 0
        assert await s.get(Novel, novel_id) is None


def _create_after_deleter(
    factory: async_sessionmaker[AsyncSession], novel_id: uuid.UUID, make_job: Callable[[Novel], NovelJob]
) -> "asyncio.Task[object]":
    """작업 생성 요청 하나를 띄운다. 라우트처럼 소설을 잠금 없이 먼저 읽고(그래서 아직 있는 소설을 본다) 차감으로
    들어간다. 거절은 예외 대신 결과로 돌려준다."""

    async def request() -> object:
        async with factory() as s:
            novel = await s.get(Novel, novel_id)
            assert novel is not None
            job = make_job(novel)
            try:
                return await billing.create_charged_job(
                    s, job=job, expected_cost=billing.job_price(job.kind), now=datetime.now(UTC)
                )
            except HTTPException as exc:
                return exc

    return asyncio.create_task(request())


async def test_job_creation_waiting_on_a_novel_deletion_is_404_and_charges_nothing(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """소설 삭제는 사용자 행을 쥔 채 소설을 지운다. 그 사이 장 생성이 소설을 읽고 차감에 들어와 사용자 행에서
    기다리다가, 삭제가 커밋된 뒤 이미 없는 소설에 작업을 넣으려 하면 FK 위반(500)이다. 잠금을 얻은 뒤 소설을 다시
    보면 404 로 거절하고 원장에는 아무것도 남지 않는다."""
    user_id, novel_id = await _seed(independent_factory)
    deleter = independent_factory()
    try:
        novel = await deleter.get(Novel, novel_id)
        assert novel is not None
        await billing._lock_user(deleter, user_id)

        task = _create_after_deleter(
            independent_factory, novel_id, lambda n: _chapter_job(n, start_message_id=uuid.uuid4())
        )
        await _assert_blocked(task)
        await delete_novel(novel=novel, db=deleter)
        result = await task
    finally:
        await deleter.close()

    assert isinstance(result, HTTPException)
    assert (result.status_code, _detail(result)) == (404, {"code": "NOVEL_NOT_FOUND"})
    assert await _independent_ledger(independent_factory, user_id) == []


async def test_regeneration_waiting_on_a_last_chapter_deletion_is_404_and_charges_nothing(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """마지막 장 삭제도 사용자 행을 먼저 잡는다. 그 장을 다시 만드는 요청이 그 뒤에서 기다렸다가 지워진 장을 가리키는
    작업을 넣으면 FK 위반(500)이다. 잠금을 얻은 뒤 장을 다시 보면 404 로 거절하고 원장에는 아무것도 남지 않는다."""
    user_id, novel_id = await _seed(independent_factory)
    now = datetime.now(UTC)
    async with independent_factory() as s:
        chapter = NovelChapter(
            novel_id=novel_id,
            ordinal=1,
            start_message_id=uuid.uuid4(),
            start_message_created_at=now,
            end_message_id=uuid.uuid4(),
            end_message_created_at=now,
            assistant_message_count=1,
            source_hash="0" * 64,
        )
        s.add(chapter)
        await s.flush()
        s.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body="첫 본문", source="generate"))
        await s.commit()

    def regenerate(novel: Novel) -> NovelJob:
        job = _chapter_job(novel, kind="chapter_regenerate", start_message_id=chapter.start_message_id)
        job.chapter_id = chapter.id
        return job

    deleter = independent_factory()
    try:
        novel = await deleter.get(Novel, novel_id)
        assert novel is not None
        await billing._lock_user(deleter, user_id)

        task = _create_after_deleter(independent_factory, novel_id, regenerate)
        await _assert_blocked(task)
        await delete_last_novel_chapter(chapter_id=chapter.id, novel=novel, db=deleter)
        result = await task
    finally:
        await deleter.close()

    assert isinstance(result, HTTPException)
    assert (result.status_code, _detail(result)) == (404, {"code": "NOVEL_CHAPTER_NOT_FOUND"})
    assert await _independent_ledger(independent_factory, user_id) == []
    async with independent_factory() as s:
        assert await s.get(Novel, novel_id) is not None


async def test_chapter_whose_start_was_taken_by_a_chapter_saved_while_waiting_is_409_and_charges_nothing(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """장 생성은 다음 장 시작을 사용자 잠금 전에 정한다. 그 사이 앞 작업이 같은 구간으로 장을 저장하면, 잠금 뒤 다시
    보지 않는 한 같은 구간이 두 장이 되고 차감도 두 번이다. 잠금을 얻은 뒤 마지막 장 끝이 이 작업 시작보다 앞인지
    다시 보면 409 로 거절하고 원장에는 아무것도 남지 않는다."""
    user_id, novel_id = await _seed(independent_factory)
    start_at = datetime.now(UTC) - timedelta(minutes=5)
    start_id = uuid.uuid4()

    def from_the_old_start(novel: Novel) -> NovelJob:
        job = _chapter_job(novel, start_message_id=start_id)
        job.start_message_created_at = start_at
        return job

    saver = independent_factory()
    try:
        await billing._lock_user(saver, user_id)
        task = _create_after_deleter(independent_factory, novel_id, from_the_old_start)
        await _assert_blocked(task)
        # 앞 작업의 결과 저장: 같은 시작부터 그 뒤 메시지까지를 장 1로 넣는다.
        saver.add(
            NovelChapter(
                novel_id=novel_id,
                ordinal=1,
                start_message_id=start_id,
                start_message_created_at=start_at,
                end_message_id=uuid.uuid4(),
                end_message_created_at=start_at + timedelta(minutes=1),
                assistant_message_count=1,
                source_hash="0" * 64,
            )
        )
        await saver.commit()
        result = await task
    finally:
        await saver.close()

    assert isinstance(result, HTTPException)
    assert (result.status_code, _detail(result)) == (409, {"code": "NOVEL_NOTHING_NEW"})
    assert await _independent_ledger(independent_factory, user_id) == []


async def test_last_batch_delete_lets_an_edit_holding_the_job_finish_instead_of_deadlocking(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AI 수정 적용은 작업 행을 잠근 뒤 화 행을 잠근다. 묶음 삭제가 화를 먼저 잠그고 작업 행을 고치면 둘이 서로를 기다려
    한쪽이 교착 오류로 끊긴다(삭제든 적용이든 500). 삭제도 작업 행 → 화 순서면 삭제가 적용 커밋을 기다린다."""
    user_id, novel_id = await _seed(independent_factory)
    async with independent_factory() as s:
        novel = await s.get_one(Novel, novel_id)
        (chapter,) = await _batch(s, novel, episodes=1)
        revision = NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body="본문", source="generate")
        s.add(revision)
        await s.flush()
        edit = NovelJob(
            novel_id=novel_id,
            user_id=user_id,
            kind="ai_edit",
            status="succeeded",
            chapter_id=chapter.id,
            base_revision_id=revision.id,
            instruction="고쳐",
            result_text="고친 본문",
            charged_amount=20,
        )
        s.add(edit)
        await s.commit()
        batch_id = chapter.batch_id
        assert batch_id is not None

    applier = independent_factory()
    try:
        # 적용이 하는 일 그대로: 작업 행 잠금 → (삭제가 끼어든 뒤) 화 행 잠금.
        await applier.execute(select(NovelJob.id).where(NovelJob.id == edit.id).with_for_update(key_share=True))

        async def delete_last_batch() -> None:
            async with independent_factory() as s:
                await billing._lock_user(s, user_id)
                await delete_batch(s, novel_id=novel_id, batch_id=batch_id)
                await s.commit()

        task = asyncio.ensure_future(delete_last_batch())
        await _assert_blocked(task)
        async with asyncio.timeout(5):
            await applier.execute(
                select(NovelChapter.id).where(NovelChapter.id == chapter.id).with_for_update(key_share=True)
            )
        await applier.commit()
        await task
    finally:
        await applier.close()

    async with independent_factory() as s:
        assert await s.get(NovelBatch, batch_id) is None
        kept = await s.get_one(NovelJob, edit.id)
        assert (kept.chapter_id, kept.result_text) == (None, None)


async def test_two_concurrent_batch_fills_give_each_chapter_one_batch_without_a_duplicate_number(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """상세 두 개가 동시에 같은 묶음 없는 화를 채우면 같은 묶음 번호를 두 번 쓰려다 유니크 위반(500)이 날 수 있다. 사용자
    행에서 줄을 서므로 뒤 요청은 앞 요청이 채운 결과를 보고 아무것도 하지 않는다."""
    _user_id, novel_id = await _seed(independent_factory)
    async with independent_factory() as s:
        novel = await s.get_one(Novel, novel_id)
        await _batch(s, novel, episodes=1)
        await s.execute(update(NovelChapter).where(NovelChapter.novel_id == novel_id).values(batch_id=None))
        await s.execute(delete(NovelBatch).where(NovelBatch.novel_id == novel_id))
        await s.commit()

    async def fill() -> bool:
        async with independent_factory() as s:
            changed = await ensure_batches(s, novel_id)
            await asyncio.sleep(0.2)  # 커밋 전에 잠시 쥐고 있어 다른 요청이 같은 순간에 들어오게 한다
            await s.commit()
            return changed

    results = await asyncio.gather(fill(), fill())

    assert sorted(results) == [False, True]
    async with independent_factory() as s:
        ordinals = (await s.scalars(select(NovelBatch.ordinal).where(NovelBatch.novel_id == novel_id))).all()
        unbatched = await s.scalar(
            select(func.count())
            .select_from(NovelChapter)
            .where(NovelChapter.novel_id == novel_id, NovelChapter.batch_id.is_(None))
        )
    assert (list(ordinals), unbatched) == ([1], 0)
