"""구성 흐름 작업(전체 구성안·장면 구성안·원고)의 과금 — 금액, 선차감·단일 환불, 진행 1건, 원고의 하루 상한과 같은 화 두 번
쓰기 막기, 그리고 성공한 원고를 "첫 화 저장"으로 세는 두 자리(집필권 잠금 자가 보정·최근 모델).

라우트는 아직 없어 차감 함수(`create_charged_job`)와 판정 함수를 직접 부른다. 서비스가 거절할 때 스스로 롤백하므로
`test_novelize_billing.py` 와 같이 `db_session` 커넥션 위의 SAVEPOINT 세션에서 부른다 — 셋업은 남고 서비스가 쓴 것만 되돌아간다."""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.config import settings
from api.core.rate_limit import KST, seconds_until_kst_midnight
from api.db.models import Novel, NovelChapter, NovelJob, User
from api.db.models.clover import CloverLedger
from api.db.models.novel import NovelEpisodeOutline, NovelJobKind, NovelJobStatus, NovelOutline
from api.llm.chat_models import ChatModelId
from api.novelize import billing
from api.novelize.router import _last_chapter_model
from api.novelize.writing_lock import first_saved_chapter_at
from factories import _make_draft_content, _make_user_with_clover_lot

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_OUTLINE_KINDS: tuple[NovelJobKind, ...] = ("outline_generate", "episode_outline_generate", "outline_chapter_generate")


@pytest.fixture(autouse=True)
def _outline_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    """구성안 두 종의 임시 단가를 서로 다르고 화 단가와도 다른 값으로 둔다 — 분기가 엉뚱한 상수를 읽으면 금액이 갈린다."""
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST", 11)
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST_SONNET", 12)
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST_OPUS", 13)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST", 21)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST_SONNET", 22)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST_OPUS", 23)


def _detail(exc: HTTPException) -> object:
    return exc.detail


def _service_session(db_session: AsyncSession) -> AsyncSession:
    return AsyncSession(bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False)


async def _novel(db: AsyncSession, balance: int = 200) -> Novel:
    owner = await _make_user_with_clover_lot(db, clover_balance=balance)
    content = await _make_draft_content(db, creator_user_id=owner.id)
    novel = Novel(
        user_id=owner.id, content_id=content.id, content_type="character", content_title="원작", character_name="인물"
    )
    db.add(novel)
    await db.flush()
    return novel


def _job(
    novel: Novel,
    kind: NovelJobKind,
    *,
    model: ChatModelId = "gemini",
    episode_outline_id: uuid.UUID | None = None,
    episode_key: uuid.UUID | None = None,
) -> NovelJob:
    return NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind=kind,
        model=model,
        outline_id=uuid.uuid4(),
        outline_episode_key=episode_key or uuid.uuid4(),
        episode_outline_id=episode_outline_id or uuid.uuid4(),
    )


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await db.execute(
        select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.amount, CloverLedger.kind)
    )
    return [(kind, amount) for kind, amount in rows.all()]


async def _create(db_session: AsyncSession, job: NovelJob, cost: int, now: datetime | None = None) -> NovelJob:
    async with _service_session(db_session) as s:
        return await billing.create_charged_job(s, job=job, expected_cost=cost, now=now or datetime.now(UTC))


async def _refused(db_session: AsyncSession, job: NovelJob, cost: int, now: datetime | None = None) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        await _create(db_session, job, cost, now)
    return caught.value


# ── 금액 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("model", "outline", "episode_outline", "manuscript"),
    [
        pytest.param("gemini", 11, 21, 40, id="gemini"),
        pytest.param("sonnet", 12, 22, 105, id="sonnet"),
        pytest.param("opus", 13, 23, 170, id="opus"),
    ],
)
def test_outline_flow_jobs_are_priced_per_model_and_a_manuscript_is_one_episode(
    model: ChatModelId, outline: int, episode_outline: int, manuscript: int
) -> None:
    """구성안 두 종은 화 수와 무관한 모델별 고정가(각자의 상수)이고, 원고는 화 하나라 그 모델의 화 단가 한 번이다. 깨지는
    시나리오: 구성안이 화 단가로 차감되거나, 원고가 실린 화 수만큼 곱해진다."""
    assert [billing.job_price("outline_generate", model, n) for n in (1, 4)] == [outline, outline]
    assert [billing.job_price("episode_outline_generate", model, n) for n in (1, 4)] == [episode_outline] * 2
    assert [billing.job_price("outline_chapter_generate", model, n) for n in (1, 4)] == [manuscript, manuscript]


def test_the_outline_prices_are_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """단가를 바꾸면 다음 호출부터 바뀐 값이다 — 응답에 내린 금액과 차감액이 같은 함수에서 나와야 어긋나지 않는다."""
    monkeypatch.setattr(clover, "NOVELIZE_OUTLINE_COST_OPUS", 77)
    monkeypatch.setattr(clover, "NOVELIZE_EPISODE_OUTLINE_COST", 5)
    assert billing.job_price("outline_generate", "opus") == 77
    assert billing.job_price("episode_outline_generate", "gemini") == 5


# ── 선차감·단일 환불·진행 1건 ────────────────────────────────────────────────
@pytest.mark.parametrize("kind", _OUTLINE_KINDS)
async def test_an_outline_flow_job_is_charged_once_and_refunded_once(db_session: AsyncSession, kind: NovelJobKind) -> None:
    """선차감으로 진행 대기 작업이 되고, 실패 확정은 한 번만 전액을 돌려준다. 확인 금액이 다르면 차감 전 409 다. 깨지는
    시나리오: 새 종류가 다른 차감 길을 타 이중 차감·이중 환불이 나거나, 화면 금액과 다른 값을 깎는다."""
    novel = await _novel(db_session)
    price = billing.job_price(kind, "sonnet")

    stale = await _refused(db_session, _job(novel, kind, model="sonnet"), price + 1)
    job = await _create(db_session, _job(novel, kind, model="sonnet"), price)
    async with _service_session(db_session) as s:
        first = await billing.refund_job(s, job_id=job.id, failure_code="llm_error")
        await s.commit()
    async with _service_session(db_session) as s:
        second = await billing.refund_job(s, job_id=job.id, failure_code="llm_error")
        await s.commit()

    assert (stale.status_code, _detail(stale)) == (409, {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": price})
    assert (job.status, job.charged_amount) == ("queued", price)
    assert (first, second) == (price, None)
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -price), ("novelize_refund", price)]


@pytest.mark.parametrize("kind", _OUTLINE_KINDS)
async def test_an_outline_flow_job_while_another_job_runs_is_409_and_charges_nothing(
    db_session: AsyncSession, kind: NovelJobKind
) -> None:
    """소설당 진행 중 작업은 종류와 무관하게 하나다 — 구성안을 만드는 동안 원고나 옛 흐름 화 생성이 끼어들지 못한다. 깨지는
    시나리오: 이중 클릭이 작업 둘·차감 둘이 된다."""
    novel = await _novel(db_session)
    db_session.add(NovelJob(novel_id=novel.id, user_id=novel.user_id, kind="ai_edit", status="running", charged_amount=20))
    await db_session.flush()

    refused = await _refused(db_session, _job(novel, kind), billing.job_price(kind))

    assert (refused.status_code, _detail(refused)) == (409, {"code": "NOVEL_JOB_IN_PROGRESS"})
    assert await _ledger(db_session, novel.user_id) == []


# ── 하루 상한 ───────────────────────────────────────────────────────────────
async def test_the_manuscript_daily_limit_counts_todays_live_attempts_of_the_same_scene_outline_revision(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """원고의 하루 상한은 같은 장면 구성안 리비전의 오늘 원고 중 진행 중·성공만 센다(실패·어제·다른 리비전·옛 흐름 화 생성은
    세지 않는다). 상한 2 면 이미 1 건일 때 통과하고 2 건일 때 429 다. 깨지는 시나리오: 원고가 상한 밖이라 같은 장면 구성안으로
    끝없이 다시 사거나, 시작 메시지가 비어 있는 원고끼리 한 키로 묶여 엉뚱한 화가 막힌다."""
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 2)
    novel = await _novel(db_session)
    revision = uuid.uuid4()
    now = datetime.now(UTC)
    today_start = datetime.combine(now.astimezone(KST).date(), time.min, tzinfo=KST)

    def done(status: NovelJobStatus, *, kind: NovelJobKind = "outline_chapter_generate", same: bool = True) -> NovelJob:
        job = _job(novel, kind, episode_outline_id=revision if same else uuid.uuid4())
        job.status = status
        job.charged_amount = 40
        return job

    yesterday = done("succeeded")
    yesterday.created_at = today_start - timedelta(seconds=1)
    db_session.add_all(
        [
            done("succeeded"),
            yesterday,
            done("failed"),
            done("succeeded", same=False),
            done("succeeded", kind="outline_generate"),
        ]
    )
    await db_session.flush()

    created = await _create(db_session, _job(novel, "outline_chapter_generate", episode_outline_id=revision), 40, now)
    await db_session.execute(update(NovelJob).where(NovelJob.id == created.id).values(status="succeeded"))
    refused = await _refused(db_session, _job(novel, "outline_chapter_generate", episode_outline_id=revision), 40, now)
    other = await _create(db_session, _job(novel, "outline_chapter_generate"), 40, now)

    assert refused.status_code == 429
    assert _detail(refused) == {
        "code": "USER_LIMIT",
        "retryAfterSeconds": seconds_until_kst_midnight(now),
        "window": "novelize",
    }
    assert other.status == "queued"
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -40), ("novelize_spend", -40)]


@pytest.mark.parametrize("kind", ["outline_generate", "episode_outline_generate"])
async def test_outlines_are_outside_the_daily_limit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, kind: NovelJobKind
) -> None:
    """구성안은 하루 상한에 세지 않는다 — 유료라 남용 제동은 과금 자체다. 깨지는 시나리오: 구성안이 화 생성 상한을 나눠
    써서 원고를 못 만든다."""
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 0)
    novel = await _novel(db_session)

    job = await _create(db_session, _job(novel, kind), billing.job_price(kind))

    assert job.status == "queued"


# ── 같은 화 두 번 쓰기 ──────────────────────────────────────────────────────
async def _written_episode(db: AsyncSession, novel: Novel) -> tuple[uuid.UUID, uuid.UUID]:
    """구성안 한 판, 그 화 하나의 장면 구성안 두 리비전, 첫 리비전으로 쓴 화 하나. (화 키, 둘째 장면 구성안 리비전 id)."""
    key = uuid.uuid4()
    outline = NovelOutline(novel_id=novel.id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[])
    db.add(outline)
    await db.flush()
    first, second = (
        NovelEpisodeOutline(
            novel_id=novel.id, outline_id=outline.id, episode_key=key, revision=n, source="generate", scenes=[]
        )
        for n in (1, 2)
    )
    db.add_all([first, second])
    await db.flush()
    now = datetime.now(UTC)
    db.add(
        NovelChapter(
            novel_id=novel.id,
            ordinal=1,
            start_message_id=uuid.uuid4(),
            start_message_created_at=now,
            end_message_id=uuid.uuid4(),
            end_message_created_at=now,
            assistant_message_count=1,
            source_hash="0" * 64,
            episode_outline_id=first.id,
        )
    )
    await db.flush()
    return key, second.id


async def test_a_manuscript_for_an_episode_already_written_is_409_even_from_a_newer_scene_outline_revision(
    db_session: AsyncSession,
) -> None:
    """같은 구성안 화를 가리키는 화가 지금 있으면 원고는 차감 전 409 다 — 장면 구성안을 고쳐 새 리비전을 만들어도 같은 화
    키라 막힌다. 다른 화 키는 통과한다. 깨지는 시나리오: 낡은 탭이 같은 화를 다시 사서 같은 내용의 화가 끝에 하나 더 붙는다."""
    novel = await _novel(db_session)
    key, newer = await _written_episode(db_session, novel)

    refused = await _refused(
        db_session, _job(novel, "outline_chapter_generate", episode_outline_id=newer, episode_key=key), 40
    )
    other = await _create(db_session, _job(novel, "outline_chapter_generate"), 40)

    assert (refused.status_code, _detail(refused)) == (409, {"code": "NOVEL_OUTLINE_EPISODE_WRITTEN"})
    assert other.status == "queued"
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -40)]


# ── 첫 화 저장으로 세는 자리 ────────────────────────────────────────────────
async def _finished(db: AsyncSession, novel: Novel, kind: NovelJobKind, *, model: ChatModelId, at: datetime) -> None:
    job = _job(novel, kind, model=model)
    job.status = "succeeded"
    job.charged_amount = 40
    job.finished_at = at
    job.created_at = at
    db.add(job)
    await db.flush()


async def test_a_succeeded_manuscript_counts_as_a_saved_first_chapter_and_an_outline_does_not(
    db_session: AsyncSession,
) -> None:
    """집필권 잠금의 자가 보정은 "성공한 화 작업"을 첫 화 저장의 기록으로 본다 — 원고는 화를 저장하므로 세고, 구성안은 화를
    저장하지 않아 세지 않는다. 깨지는 시나리오: 구성 흐름으로만 화를 쓴 소설이 잠금 없이 남아, 원작 권한이 바뀌면 이어 쓰기가
    막힌다(또는 구성안만 산 소설이 잠긴다)."""
    novel = await _novel(db_session)
    at = datetime(2026, 10, 20, tzinfo=UTC)
    await _finished(db_session, novel, "outline_generate", model="gemini", at=at - timedelta(hours=2))
    await _finished(db_session, novel, "episode_outline_generate", model="gemini", at=at - timedelta(hours=1))

    before = await first_saved_chapter_at(db_session, novel.id)
    await _finished(db_session, novel, "outline_chapter_generate", model="gemini", at=at)

    assert before is None
    assert await first_saved_chapter_at(db_session, novel.id) == at


async def test_the_last_chapter_model_reads_a_succeeded_manuscript_but_not_an_outline(db_session: AsyncSession) -> None:
    """화면의 기본 모델은 가장 최근에 성공한 화 작업의 모델이다 — 원고는 화를 쓰므로 세고, 그 뒤의 구성안은 세지 않는다.
    깨지는 시나리오: Opus 로 원고를 쓴 뒤 다음 화 기본 모델이 Gemini 로 돌아가거나, Sonnet 구성안이 원고 모델을 덮는다."""
    novel = await _novel(db_session)
    at = datetime(2026, 10, 20, tzinfo=UTC)
    await _finished(db_session, novel, "chapter_generate", model="gemini", at=at - timedelta(hours=2))
    await _finished(db_session, novel, "outline_chapter_generate", model="opus", at=at - timedelta(hours=1))
    await _finished(db_session, novel, "episode_outline_generate", model="sonnet", at=at)

    assert await _last_chapter_model(db_session, novel.id, allowed=True) == "opus"


async def test_users_are_untouched_by_a_refused_outline_job(db_session: AsyncSession) -> None:
    """거절된 구성 흐름 요청은 잔액을 바꾸지 않는다(사용자 행 잠금만 잡고 롤백)."""
    novel = await _novel(db_session, balance=5)

    refused = await _refused(db_session, _job(novel, "outline_generate"), 11)
    balance = await db_session.scalar(select(User.clover_balance).where(User.id == novel.user_id))

    assert (refused.status_code, _detail(refused)["code"]) == (429, "CLOVER_REQUIRED")  # type: ignore[index]
    assert balance == 5
