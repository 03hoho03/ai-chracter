"""소설화 워커 — 대기 작업 고르기, 폴링 루프(동시 상한·정지·주기 만료 정리·살아 있음 파일), 신호 처리, 그리고 워커
스위치에 따른 작업 띄우기 분기.

루프가 작업을 실제로 돌리는 시험은 커밋되는 독립 커넥션을 쓴다. 테스트 커넥션 하나에 묶인 세션 팩토리로는 두 루프나
여러 작업이 동시에 DB 를 쓰지 못한다(한 커넥션에 문장 둘이 겹친다). 돌리는 작업은 AI 수정이고, 입력 조립만 바꿔 끼워
원작 문안을 읽지 않게 한다 — 받기(조건부 전이)·모델 호출·성공 저장·환불은 실제 경로 그대로다."""

import asyncio
import os
import signal
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core.config import settings
from api.db.models import Content, User
from api.db.models.clover import (
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
)
from api.db.models.novel import Novel, NovelJob, NovelJobKind
from api.llm.client import LLMCallContext, LLMClient, T
from api.novelize import billing, runner, worker
from api.novelize import router as novelize_router
from api.novelize.deletion import delete_novels
from api.novelize.inputs import ReviseInput
from api.novelize.prompts import NovelizePrompt
from factories import _assert_blocked, _make_draft_content, _make_novel_tree, _make_user_with_clover_lot

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_MARKER_DOMAIN = "novelize-worker.test"
_AI_EDIT_COST = 20  # `novel_prices_for_flow_tests` 의 AI 수정 단가


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_worker_poll_interval_seconds", 0.01)
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)


@pytest.fixture
def plain_revise_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """AI 수정 입력 조립을 원작 문안 없이 끝나게 바꾼다. 범위는 첫 문단 하나다."""

    async def build(_db: AsyncSession, _job: NovelJob, _novel: Novel) -> ReviseInput:
        return ReviseInput(
            prompt=NovelizePrompt(system_instruction="지시", prompt="본문"),
            paragraphs=["첫 본문"],
            first_index=0,
            last_index=0,
        )

    monkeypatch.setattr(runner, "build_revise_input", build)


@pytest_asyncio.fixture
async def independent_factory(db_engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """커밋되는 독립 커넥션 세션 팩토리. 여기서 쓴 행은 롤백되지 않으므로 이 표지 도메인의 사용자와 그 아래 행을 끝에서
    직접 지운다(`test_novelize_block_edit_races.py` 의 같은 이름 픽스처와 같은 순서)."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory
    async with factory() as cleanup:
        user_ids = (await cleanup.scalars(select(User.id).where(User.email.like(f"%@{_MARKER_DOMAIN}")))).all()
        if user_ids:
            novel_ids = (await cleanup.scalars(select(Novel.id).where(Novel.user_id.in_(user_ids)))).all()
            await delete_novels(cleanup, novel_ids, freed_storage_keys=[])
            spend_ledger_ids = select(CloverLedger.id).where(CloverLedger.user_id.in_(user_ids))
            allocation_ids = select(CloverSpendAllocation.id).where(
                CloverSpendAllocation.spend_ledger_id.in_(spend_ledger_ids)
            )
            await cleanup.execute(delete(CloverSpendRefund).where(CloverSpendRefund.allocation_id.in_(allocation_ids)))
            await cleanup.execute(
                delete(CloverSpendUsage).where(CloverSpendUsage.spend_ledger_id.in_(spend_ledger_ids))
            )
            await cleanup.execute(
                delete(CloverSpendAllocation).where(CloverSpendAllocation.spend_ledger_id.in_(spend_ledger_ids))
            )
            await cleanup.execute(delete(CloverLedger).where(CloverLedger.user_id.in_(user_ids)))
            await cleanup.execute(delete(CloverLot).where(CloverLot.user_id.in_(user_ids)))
            await cleanup.execute(delete(Content).where(Content.creator_user_id.in_(user_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(user_ids)))
        await cleanup.commit()


class _GateLLM(LLMClient):
    """AI 수정 페이크. 부를 때마다 문이 하나 생기고, 그 문을 열 때까지 기다렸다가 고친 문단을 돌려준다 — 동시에 몇 개가
    모델을 부르고 있는지, 어느 것을 먼저 끝낼지를 테스트가 정한다. `open_all` 이면 기다리지 않는다."""

    def __init__(self, *, open_all: bool = False) -> None:
        self.open_all = open_all
        self.gates: list[asyncio.Event] = []
        self.in_flight = 0
        self.peak = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("AI 수정은 스트리밍 호출을 쓰지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        gate = asyncio.Event()
        if self.open_all:
            gate.set()
        self.gates.append(gate)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await gate.wait()
        finally:
            self.in_flight -= 1
        return response_schema.model_validate({"paragraphs": ["고친 문단."]})


async def _eventually(check: Callable[[], Awaitable[bool]], *, within: float = 10.0) -> None:
    """`check` 가 참이 될 때까지 0.01초 간격으로 본다. `within` 초 안에 참이 안 되면 실패다."""
    for _ in range(int(within / 0.01)):
        if await check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{within}초 안에 조건이 서지 않았다")


async def _seed_jobs(factory: async_sessionmaker[AsyncSession], count: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """잔액 100 인 작가와, 소설마다 하나씩 대기 중인 AI 수정 작업 `count` 개(차감 포함)를 커밋한다. 작가 id 와 작업 id 를
    만든 순서대로 돌려준다."""
    async with factory() as s:
        owner = await _make_user_with_clover_lot(s, clover_balance=100, email=f"w-{uuid.uuid4()}@{_MARKER_DOMAIN}")
        content = await _make_draft_content(s, creator_user_id=owner.id)
        trees = []
        for _ in range(count):
            tree = await _make_novel_tree(s, owner.id)
            await s.delete(tree.active_job)
            # 차감이 사용처에 원작 소유자를 적으므로 원작 행이 있어야 한다.
            tree.novel.content_id = content.id
            trees.append(tree)
        await s.commit()
        owner_id = owner.id
    job_ids = []
    for tree in trees:
        async with factory() as s:
            job = NovelJob(
                novel_id=tree.novel.id,
                user_id=owner_id,
                kind="ai_edit",
                chapter_id=tree.chapter.id,
                base_revision_id=tree.reverting_revision.id,
                paragraph_start=0,
                paragraph_end=0,
                instruction="더 쓸쓸하게",
            )
            stored = await billing.create_charged_job(s, job=job, expected_cost=_AI_EDIT_COST, now=datetime.now(UTC))
            job_ids.append(stored.id)
    return owner_id, job_ids


async def _status(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> tuple[str, str | None]:
    async with factory() as s:
        row = (await s.execute(select(NovelJob.status, NovelJob.failure_code).where(NovelJob.id == job_id))).one()
        return row.status, row.failure_code


async def _ledger(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> list[tuple[str, int]]:
    async with factory() as s:
        rows = await s.execute(
            select(CloverLedger.kind, CloverLedger.amount)
            .where(CloverLedger.user_id == user_id)
            .order_by(CloverLedger.amount, CloverLedger.kind)
        )
        return [(kind, amount) for kind, amount in rows.all()]


# ── 고르기 ─────────────────────────────────────────────────────────────────


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _job_row(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: NovelJobKind,
    *,
    status: str = "queued",
    parent_job_id: uuid.UUID | None = None,
    created_at: datetime,
) -> uuid.UUID:
    """소설 하나에 작업 행 하나를 넣는다(진행 중 작업은 소설마다 하나라서). 종류마다 CHECK 가 요구하는 대상 칸을 채운다."""
    novel = Novel(
        user_id=user_id, content_id=uuid.uuid4(), content_type="character", content_title="원작", character_name="인물"
    )
    db.add(novel)
    await db.flush()
    job = NovelJob(
        novel_id=novel.id,
        user_id=user_id,
        kind=kind,
        status=status,
        charged_amount=0,
        parent_job_id=parent_job_id,
        created_at=created_at,
        heartbeat_at=created_at,
    )
    if kind == "episode_outline_generate":
        job.outline_id, job.outline_episode_key = uuid.uuid4(), uuid.uuid4()
    if kind == "outline_chapter_generate":
        job.episode_outline_id, job.outline_episode_key = uuid.uuid4(), uuid.uuid4()
    if kind == "chain_generate":
        job.planned_batches, job.batch_k_max, job.unit_price = 1, 1, 1
    db.add(job)
    await db.flush()
    return job.id


async def test_claim_picks_only_queued_top_level_jobs_of_known_kinds_oldest_first(db_session: AsyncSession) -> None:
    """대기 중이고 연쇄 자식이 아니며 워커가 아는 여섯 종류인 작업만, 오래된 순으로 빈 칸 수만큼 고른다. 깨지는 시나리오:
    이미 실행 중이거나 끝난 작업을 다시 집거나, 부모가 직접 돌리는 연쇄 자식을 집어 두 곳에서 돌리거나, 인프로세스로 남는
    연쇄 부모를 단일 작업 경로로 돌린다."""
    owner = await _make_user_with_clover_lot(db_session, clover_balance=0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    known: list[NovelJobKind] = [
        "outline_generate",
        "chapter_generate",
        "ai_edit",
        "episode_outline_generate",
        "chapter_regenerate",
        "outline_chapter_generate",
    ]
    # 넣는 순서를 시각 순서와 다르게 해 정렬이 실제로 시각을 본다는 것을 드러낸다.
    expected: list[uuid.UUID] = []
    for offset, kind in sorted(enumerate(known), key=lambda pair: -pair[0]):
        expected.append(await _job_row(db_session, owner.id, kind, created_at=base + timedelta(minutes=offset)))
    expected.reverse()
    early = base - timedelta(hours=1)  # 거르지 않으면 맨 앞에 서도록 더 이르게
    await _job_row(db_session, owner.id, "chain_generate", created_at=early)
    parent = await _job_row(db_session, owner.id, "chain_generate", status="running", created_at=early)
    await _job_row(db_session, owner.id, "chapter_generate", parent_job_id=parent, created_at=early)
    for status in ("running", "succeeded", "failed"):
        await _job_row(db_session, owner.id, "ai_edit", status=status, created_at=early)

    factory = _factory(db_session)
    assert await worker.claim_candidates(factory, 10) == expected
    assert await worker.claim_candidates(factory, 2) == expected[:2]


async def test_claim_leaves_a_kind_this_worker_does_not_know_queued(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """아는 종류 목록에 없는 종류의 대기 작업은 집지 않는다 — 아는 목록을 한 종류 줄여, 새 종류를 모르는 옛 워커를 흉내
    낸다. 깨지는 시나리오: 배포 겹침 동안 새 api 가 만든 새 종류 작업을 옛 워커가 집어, 종류를 가리지 않는 실행 경로의
    마지막 분기(장 생성)로 돌려 과금된 엉뚱한 결과를 저장한다."""
    owner = await _make_user_with_clover_lot(db_session, clover_balance=0)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    known = await _job_row(db_session, owner.id, "ai_edit", created_at=base)
    await _job_row(db_session, owner.id, "outline_chapter_generate", created_at=base - timedelta(minutes=1))
    monkeypatch.setattr(
        worker, "WORKER_JOB_KINDS", tuple(k for k in worker.WORKER_JOB_KINDS if k != "outline_chapter_generate")
    )

    assert await worker.claim_candidates(_factory(db_session), 10) == [known]


def test_known_kinds_are_every_job_kind_but_the_chain_parent() -> None:
    """워커가 아는 종류 = 작업 종류 전체 − 연쇄 부모. 깨지는 시나리오: 작업 종류를 하나 더하면서 워커 쪽 처리를 정하지 않아,
    그 종류가 영영 집히지 않거나(목록에 안 넣음) 연쇄 부모가 워커로 새어 나간다(목록에 넣음). 종류를 더하면 이 테스트가
    깨져 목록을 의식적으로 고치게 한다."""
    assert len(worker.WORKER_JOB_KINDS) == len(set(worker.WORKER_JOB_KINDS))
    assert set(worker.WORKER_JOB_KINDS) == set(get_args(NovelJobKind)) - {"chain_generate"}


# ── 폴링 루프 ──────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("plain_revise_input")
async def test_two_loops_claiming_the_same_job_run_it_once(
    independent_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """교체 구간처럼 두 워커 루프가 같은 대기 작업을 함께 골라도 실행은 한 번이다 — 모델 호출 1, 차감 1, 성공. 깨지는
    시나리오: 고르기와 받기 사이에 잠금이 없어 두 루프가 같은 작업을 둘 다 돌려 모델 원가를 두 번 쓰고 결과를 두 번 저장한다."""
    owner_id, [job_id] = await _seed_jobs(independent_factory, 1)
    llm = _GateLLM(open_all=True)
    original = worker.claim_candidates
    first_claims: list[list[uuid.UUID]] = []
    both_claimed = asyncio.Barrier(2)

    async def claim_together(factory: async_sessionmaker[AsyncSession], limit: int) -> list[uuid.UUID]:
        ids = await original(factory, limit)
        if len(first_claims) < 2:
            first_claims.append(ids)
            await both_claimed.wait()  # 두 루프가 모두 고른 뒤에야 어느 쪽이든 받으러 간다
        return ids

    monkeypatch.setattr(worker, "claim_candidates", claim_together)
    stop = asyncio.Event()
    loops = [
        asyncio.create_task(worker.run_worker(independent_factory, llm, stop, alive_file=tmp_path / f"alive-{n}"))
        for n in range(2)
    ]
    try:
        await _eventually(lambda: _done(independent_factory, job_id))
    finally:
        stop.set()
        await asyncio.gather(*loops)

    assert first_claims == [[job_id], [job_id]]
    assert len(llm.gates) == 1
    assert await _status(independent_factory, job_id) == ("succeeded", None)
    assert await _ledger(independent_factory, owner_id) == [("novelize_spend", -_AI_EDIT_COST)]


async def _all_done(factory: async_sessionmaker[AsyncSession], job_ids: list[uuid.UUID]) -> bool:
    return all([await _done(factory, job_id) for job_id in job_ids])


async def _done(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> bool:
    return (await _status(factory, job_id))[0] in ("succeeded", "failed")


@pytest.mark.usefixtures("plain_revise_input")
async def test_stop_finishes_running_jobs_and_claims_nothing_new(
    independent_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """정지 신호 뒤에는 새 작업을 집지 않고, 돌던 작업은 취소하지 않고 끝까지 기다려 성공시킨 뒤 루프가 끝난다. 기다리는
    동안에도 살아 있음 파일을 만진다. 깨지는 시나리오: 정지가 돌던 작업을 취소해 결과를 버리고 만료 환불로 넘기거나, 정지
    뒤에도 새 작업을 집어 정지 유예를 넘기거나, 비우는 동안 살아 있음이 끊겨 죽은 워커로 보인다."""
    _, [running_id, later_id] = await _seed_jobs(independent_factory, 2)
    # 둘째 작업은 정지 뒤에 들어온 것처럼 — 고르기에서 빠지게 실행 중으로 숨겨 두었다가 정지 뒤 대기로 되돌린다.
    async with independent_factory() as s:
        await s.execute(update(NovelJob).where(NovelJob.id == later_id).values(status="running"))
        await s.commit()
    llm = _GateLLM()
    stop = asyncio.Event()
    alive = tmp_path / "alive"
    loop = asyncio.create_task(worker.run_worker(independent_factory, llm, stop, alive_file=alive))
    await _eventually(lambda: _true(len(llm.gates) == 1))

    stop.set()
    async with independent_factory() as s:
        await s.execute(update(NovelJob).where(NovelJob.id == later_id).values(status="queued"))
        await s.commit()
    os.utime(alive, (0, 0))
    await _eventually(lambda: _true(alive.stat().st_mtime > 0))  # 비우는 동안 만진다
    assert not loop.done()
    llm.gates[0].set()
    await asyncio.wait_for(loop, 10)

    assert await _status(independent_factory, running_id) == ("succeeded", None)
    assert await _status(independent_factory, later_id) == ("queued", None)
    assert len(llm.gates) == 1


async def _true(value: bool) -> bool:
    return value


@pytest.mark.usefixtures("plain_revise_input")
async def test_a_job_cut_off_past_the_grace_period_is_refunded_once_by_the_expiry_sweep(
    independent_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """정지 유예를 넘겨 강제로 끝난 워커(루프 태스크 취소로 흉내)는 실패·환불을 쓰지 못하고 작업을 실행 중으로 남긴다. heartbeat
    가 만료된 뒤 만료 정리가 그 작업을 실패(만료)로 끝내고 한 번 환불한다. 깨지는 시나리오: 잘린 작업이 실행 중으로 영영 남아
    차감액이 묶이고 그 소설의 새 작업이 계속 막힌다."""
    owner_id, [job_id] = await _seed_jobs(independent_factory, 1)
    llm = _GateLLM()
    loop = asyncio.create_task(worker.run_worker(independent_factory, llm, asyncio.Event(), alive_file=tmp_path / "a"))
    await _eventually(lambda: _true(len(llm.gates) == 1))

    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop
    assert await _status(independent_factory, job_id) == ("running", None)
    assert await _ledger(independent_factory, owner_id) == [("novelize_spend", -_AI_EDIT_COST)]

    async with independent_factory() as s:
        await s.execute(
            update(NovelJob).where(NovelJob.id == job_id).values(heartbeat_at=func.now() - timedelta(minutes=5))
        )
        await s.commit()
    await runner.expire_all_stale_jobs(independent_factory)

    assert await _status(independent_factory, job_id) == ("failed", "expired")
    assert await _ledger(independent_factory, owner_id) == [
        ("novelize_spend", -_AI_EDIT_COST),
        ("novelize_refund", _AI_EDIT_COST),
    ]


@pytest.mark.usefixtures("plain_revise_input")
async def test_the_loop_never_runs_more_jobs_than_the_cap_at_once(
    independent_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """상한 2 에 대기 작업 3 이면 둘만 돌고, 하나가 끝나야 셋째를 집는다. 깨지는 시나리오: 상한을 안 지켜 대기 작업을 한꺼번에
    다 띄워 DB 풀·모델 쿼터를 한 번에 쓰거나, 끝난 작업의 칸을 돌려받지 못해 셋째가 영영 대기로 남는다."""
    monkeypatch.setattr(settings, "novelize_worker_max_concurrent_jobs", 2)
    _, job_ids = await _seed_jobs(independent_factory, 3)
    llm = _GateLLM()
    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_worker(independent_factory, llm, stop, alive_file=tmp_path / "alive"))
    try:
        await _eventually(lambda: _true(len(llm.gates) == 2))
        await asyncio.sleep(0.2)  # 폴링 스무 바퀴 — 칸이 있으면 셋째를 집었을 시간
        assert len(llm.gates) == 2
        assert await _status(independent_factory, job_ids[2]) == ("queued", None)

        llm.gates[0].set()
        await _eventually(lambda: _true(len(llm.gates) == 3))
        for gate in llm.gates:
            gate.set()
        await _eventually(lambda: _all_done(independent_factory, job_ids))
    finally:
        stop.set()
        await asyncio.wait_for(loop, 10)

    assert llm.peak == 2
    assert [await _status(independent_factory, job_id) for job_id in job_ids] == [("succeeded", None)] * 3


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


async def test_periodic_sweep_starts_after_expiry_plus_margin_repeats_every_minute_and_stops_while_draining(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """만료 정리는 기동 + heartbeat 만료 + 10초에 처음 돌고 그 뒤 60초마다 돈다. 정지 신호 뒤(돌던 작업을 기다리는 동안)에는
    돌지 않는다. 깨지는 시나리오: 기동 직후 바로 돌아 직전 프로세스가 막 민 heartbeat 를 아직 못 보고 놓치거나, 한 번만 돌아
    옛 워커가 유예를 넘겨 남긴 작업이 사용자가 돌아올 때까지 환불되지 않거나, 비우는 워커가 계속 정리한다."""
    clock = _Clock(1000.0)
    sweeps: list[float] = []
    claims: list[int] = []
    finish = asyncio.Event()
    handed_out = False

    async def sweep(_factory: Any) -> int:
        sweeps.append(clock.now)
        return 0

    async def claim(_factory: Any, limit: int) -> list[uuid.UUID]:
        nonlocal handed_out
        claims.append(limit)
        if clock.now >= 2000 and not handed_out:
            handed_out = True
            return [uuid.uuid4()]
        return []

    async def run(_factory: Any, _llm: Any, _job_id: uuid.UUID) -> None:
        await finish.wait()

    monkeypatch.setattr(worker, "expire_all_stale_jobs", sweep)
    monkeypatch.setattr(worker, "claim_candidates", claim)
    monkeypatch.setattr(worker, "run_job", run)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    stop = asyncio.Event()

    async def polls(count: int) -> None:
        seen = len(claims)
        await _eventually(lambda: _true(len(claims) >= seen + count))

    loop = asyncio.create_task(
        worker.run_worker(_factory(db_session), _GateLLM(), stop, alive_file=tmp_path / "alive", clock=clock)
    )
    try:
        await polls(2)
        clock.now = 1069.9
        await polls(2)
        assert sweeps == []
        clock.now = 1070.0
        await polls(2)
        assert sweeps == [1070.0]
        clock.now = 1129.9
        await polls(2)
        assert sweeps == [1070.0]
        clock.now = 1130.0
        await polls(2)
        assert sweeps == [1070.0, 1130.0]

        clock.now = 2000.0  # 한 바퀴 정리하고 작업 하나를 받는다
        await _eventually(lambda: _true(handed_out))
        stop.set()
        clock.now = 9000.0
        await asyncio.sleep(0.1)
        assert not loop.done()
        assert sweeps == [1070.0, 1130.0, 2000.0]
    finally:
        finish.set()
        stop.set()
        await asyncio.wait_for(loop, 10)


async def test_alive_file_is_touched_only_after_a_successful_poll(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """살아 있음 파일은 고르기 조회가 성공한 바퀴에만 만진다. 조회가 실패하면 루프는 다음 바퀴로 가지만 파일은 그대로다.
    깨지는 시나리오: DB 가 계속 안 되는데도 파일을 만져 헬스체크가 healthy 로 남아, 아무 일도 못 하는 워커가 교체 판정과 감시를
    통과한다. 또는 조회 실패 한 번에 루프가 죽는다."""
    failing = True
    calls = 0

    async def claim(_factory: Any, _limit: int) -> list[uuid.UUID]:
        nonlocal calls
        calls += 1
        if failing:
            raise ConnectionRefusedError("DB 가 잠깐 안 된다")
        return []

    monkeypatch.setattr(worker, "claim_candidates", claim)
    alive = tmp_path / "alive"
    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_worker(_factory(db_session), _GateLLM(), stop, alive_file=alive))
    try:
        await _eventually(lambda: _true(calls >= 3))
        assert not alive.exists()
        failing = False
        await _eventually(lambda: _true(alive.exists()))
        os.utime(alive, (0, 0))
        await _eventually(lambda: _true(alive.stat().st_mtime > 0))
    finally:
        stop.set()
        await asyncio.wait_for(loop, 10)


async def test_sigterm_stops_the_worker(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SIGTERM 을 받으면 루프를 멈추고 돌아온다. 컨테이너에서 이 프로세스는 PID 1 이라 처리기가 없으면 신호를 무시한다.
    깨지는 시나리오: 처리기를 달지 않아 `docker stop` 이 정지 유예를 다 기다린 뒤 SIGKILL 로 끝내고, 돌던 작업이 모두 만료
    환불로 넘어간다."""

    async def claim(_factory: Any, _limit: int) -> list[uuid.UUID]:
        return []

    monkeypatch.setattr(worker, "claim_candidates", claim)
    alive = tmp_path / "alive"
    serving = asyncio.create_task(worker.serve(_factory(db_session), _GateLLM(), alive_file=alive))
    await _eventually(lambda: _true(alive.exists()))

    os.kill(os.getpid(), signal.SIGTERM)

    await asyncio.wait_for(serving, 10)


async def test_sweep_and_on_demand_expiry_seeing_the_same_dead_job_refund_it_once(
    independent_factory: async_sessionmaker[AsyncSession],
) -> None:
    """워커의 주기 정리와 사용자 폴링의 지연 정리가 같은 만료 작업을 동시에 봐도 환불은 한 행이다. 둘 다 사용자 행에서 줄을
    서고(막혀 있는 것을 먼저 확인한다), 뒤에 선 쪽은 이미 실패한 작업을 받지 못한다. 깨지는 시나리오: 정리가 둘이 되면서 같은
    작업을 두 번 환불해 클로버가 늘어난다."""
    owner_id, [job_id] = await _seed_jobs(independent_factory, 1)
    async with independent_factory() as s:
        novel_id = (await s.execute(select(NovelJob.novel_id).where(NovelJob.id == job_id))).scalar_one()
        await s.execute(
            update(NovelJob)
            .where(NovelJob.id == job_id)
            .values(status="running", heartbeat_at=func.now() - timedelta(minutes=5))
        )
        await s.commit()

    async def on_demand() -> object:
        async with independent_factory() as s:
            expired = await runner.expire_stale_jobs(s, novel_id=novel_id)
            await s.commit()
            return expired

    holder = independent_factory()
    try:
        await holder.execute(select(User.id).where(User.id == owner_id).with_for_update())
        swept: asyncio.Task[object] = asyncio.ensure_future(runner.expire_all_stale_jobs(independent_factory))
        polled: asyncio.Task[object] = asyncio.ensure_future(on_demand())
        await _assert_blocked(swept)
        await _assert_blocked(polled)
        await holder.commit()
        results = await asyncio.gather(swept, polled)
    finally:
        await holder.close()

    assert sorted(int(str(r)) for r in results) == [0, 1]
    assert await _status(independent_factory, job_id) == ("failed", "expired")
    assert await _ledger(independent_factory, owner_id) == [
        ("novelize_spend", -_AI_EDIT_COST),
        ("novelize_refund", _AI_EDIT_COST),
    ]


# ── 작업 띄우기 분기 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("worker_enabled", [False, True])
@pytest.mark.parametrize("kind", get_args(NovelJobKind))
async def test_start_job_hands_jobs_to_the_worker_only_when_switched_on(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, kind: NovelJobKind, worker_enabled: bool
) -> None:
    """워커 스위치가 꺼져 있으면 지금처럼 모든 작업을 이 프로세스에서 띄운다(연쇄 부모는 연쇄 경로, 나머지는 단일 작업 경로).
    켜져 있으면 여섯 종류는 띄우지 않고 대기 행만 남기며(워커가 집는다), 연쇄 부모는 여전히 이 프로세스에서 띄운다. 깨지는
    시나리오: 꺼진 스위치에서 작업이 안 띄워져 운영 소설화가 모두 만료 환불로 끝나거나, 켠 스위치에서 api 와 워커가 같은
    작업을 둘 다 돌리거나, 워커가 다루지 않는 연쇄 부모가 아무도 안 돌린 채 남는다."""
    monkeypatch.setattr(settings, "novelize_worker_enabled", worker_enabled)
    single: list[uuid.UUID] = []
    chain: list[uuid.UUID] = []

    async def record_single(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        single.append(job_id)

    async def record_chain(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        chain.append(job_id)

    async def insert_as_charged(db: AsyncSession, *, job: NovelJob, expected_cost: int, now: datetime) -> NovelJob:
        job.status, job.charged_amount, job.heartbeat_at = "queued", 0, now
        db.add(job)
        await db.commit()
        return job

    monkeypatch.setattr(novelize_router, "enqueue_job", record_single)
    monkeypatch.setattr(novelize_router, "enqueue_chain_job", record_chain)
    monkeypatch.setattr(novelize_router, "create_charged_job", insert_as_charged)
    owner = await _make_user_with_clover_lot(db_session, clover_balance=0)
    novel = Novel(
        user_id=owner.id, content_id=uuid.uuid4(), content_type="character", content_title="원작", character_name="인물"
    )
    db_session.add(novel)
    await db_session.flush()
    job = NovelJob(novel_id=novel.id, user_id=owner.id, kind=kind)
    if kind == "episode_outline_generate":
        job.outline_id, job.outline_episode_key = uuid.uuid4(), uuid.uuid4()
    if kind == "outline_chapter_generate":
        job.episode_outline_id, job.outline_episode_key = uuid.uuid4(), uuid.uuid4()
    if kind == "chain_generate":
        job.planned_batches, job.batch_k_max, job.unit_price = 1, 1, 1

    response = await novelize_router._start_job(db_session, job, 0, _factory(db_session), _GateLLM())

    assert response.id == job.id
    if kind == "chain_generate":
        assert (single, chain) == ([], [job.id])
    elif worker_enabled:
        assert (single, chain) == ([], [])
        assert (await db_session.get_one(NovelJob, job.id, populate_existing=True)).status == "queued"
    else:
        assert (single, chain) == ([job.id], [])
