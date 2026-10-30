"""소설화 워커 안의 정본 기억 처리 — 스위치가 꺼지면 정본 기억 표를 읽지 않고, 켜지면 소설 작업과 따로 센 동시 상한으로 확정·
작업을 돌리며, 정지·취소·만료 정리·살아 있음 판정에서 소설 작업과 어떻게 함께 다뤄지는지.

루프를 실제로 돌리는 시험은 커밋되는 독립 엔진을 쓴다(루프와 작업이 동시에 DB 를 쓴다). 소설 작업 쪽은 고르기·실행을 가짜로
바꿔 끼운다 — 소설 작업 문장이 그대로인지는 `test_novelize_worker.py` 의 문장 열 특성화가 본다. 정본 기억 쪽은 가짜 슬롯 하나와
문을 열 때까지 기다리는 가짜 어댑터로 실제 받기·저장·연결·커밋 경로를 돈다."""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.core.config import settings
from api.db.models.clover import CloverLedger
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleJob, NovelBibleRevision
from api.llm.client import LLMClient
from api.novel_bible import entry
from api.novel_bible.core import pipeline
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import PromptSource, Registry
from api.novel_bible.core.sweep import expire_stale_work
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import OperationKey
from api.novelize import worker
from factories import _Clock, _committed_engine, _eventually, _true
from novel_bible_fakes import (
    COMMITTED_DOMAIN,
    FakeAdapter,
    add_chapter,
    delete_committed_novels,
    facts_slot,
    fake_registry,
    make_novel,
    savepoint_factory,
)

T = TypeVar("T", bound=BaseModel)
SessionFactory = async_sessionmaker[AsyncSession]

BODY = "사실: 하나|life|-|alive|참"
SYSTEM = Actor(kind="system")


@dataclass
class _GateAdapter(FakeAdapter):
    """부를 때마다 `gate` 가 열릴 때까지 기다리는 가짜 어댑터 — 몇 개가 동시에 모델을 부르고 있는지를 테스트가 본다."""

    gate: asyncio.Event = field(default_factory=asyncio.Event)
    in_flight: int = 0
    peak: int = 0

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await self.gate.wait()
        finally:
            self.in_flight -= 1
        return await super().structured(prompt, schema, records=records, stage=stage)


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_worker_poll_interval_seconds", 0.01)


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    engine = _committed_engine(db_engine)
    try:
        yield engine
    finally:
        await delete_committed_novels(engine)
        await engine.dispose()


@pytest.fixture
def adapter() -> _GateAdapter:
    return _GateAdapter()


@pytest.fixture
def registry() -> Registry:
    return fake_registry(facts_slot())


@pytest.fixture
def bible_on(monkeypatch: pytest.MonkeyPatch, adapter: _GateAdapter, registry: Registry) -> None:
    """정본 기억 스위치를 켜고, 워커가 쓰는 등록부·어댑터를 가짜 슬롯 하나와 문 달린 가짜 어댑터로 바꾼다."""
    monkeypatch.setattr(settings, "novel_bible_enabled", True)
    monkeypatch.setattr(settings, "novel_bible_worker_max_concurrent", 1)
    monkeypatch.setattr(entry, "REGISTRY", registry)
    monkeypatch.setattr(entry, "build_resolver", lambda llm_client=None: adapter.resolver())


@dataclass
class _NovelSide:
    """소설 작업 쪽 가짜 — 고르기 호출마다 받은 빈 칸 수를 남기고, `offer` 가 참이 된 뒤 처음 한 번만 작업 하나를 내준다. 그
    작업은 `finish` 가 설 때까지 돈다."""

    offer: Callable[[], bool] = lambda: False
    limits: list[int] = field(default_factory=list)
    running: int = 0
    handed: uuid.UUID | None = None
    finish: asyncio.Event = field(default_factory=asyncio.Event)

    async def claim(self, _factory: Any, limit: int) -> list[uuid.UUID]:
        self.limits.append(limit)
        if self.handed is None and self.offer():
            self.handed = uuid.uuid4()
            return [self.handed]
        return []

    async def run(self, _factory: Any, _llm: Any, _job_id: uuid.UUID) -> None:
        self.running += 1
        try:
            await self.finish.wait()
        finally:
            self.running -= 1


@pytest.fixture
def novel_side(monkeypatch: pytest.MonkeyPatch) -> _NovelSide:
    side = _NovelSide()
    monkeypatch.setattr(worker, "claim_candidates", side.claim)
    monkeypatch.setattr(worker, "run_job", side.run)
    return side


async def _confirm_chapters(
    engine: AsyncEngine, registry: Registry, count: int
) -> tuple[SessionFactory, uuid.UUID, list[uuid.UUID]]:
    """커밋되는 소설 하나에 화 `count` 개를 만들고 화마다 확정한다(가짜 슬롯 하나면 확정마다 대기 작업 하나). 소설 id 와 확정 id 를
    화 차례대로 돌려준다."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    commit_ids = []
    async with factory() as setup:
        novel = await make_novel(setup, email_domain=COMMITTED_DOMAIN)
        for ordinal in range(1, count + 1):
            chapter, revision = await add_chapter(setup, novel.id, ordinal, BODY)
            result = await confirm(
                setup, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
            )
            commit_ids.append(result.commit_id)
        await setup.commit()
        novel_id = novel.id
    return factory, novel_id, commit_ids


async def _job_states(factory: SessionFactory, novel_id: uuid.UUID) -> list[tuple[str, int]]:
    async with factory() as s:
        rows = await s.execute(
            select(NovelBibleJob.status, NovelBibleJob.attempts)
            .join(NovelBibleCommit, NovelBibleCommit.id == NovelBibleJob.commit_id)
            .where(NovelBibleJob.novel_id == novel_id)
            .order_by(NovelBibleCommit.created_at)
        )
        return [(status, attempts) for status, attempts in rows.all()]


async def _commit_states(factory: SessionFactory, commit_ids: list[uuid.UUID]) -> list[str]:
    async with factory() as s:
        statuses = dict((await s.execute(
            select(NovelBibleCommit.id, NovelBibleCommit.status).where(NovelBibleCommit.id.in_(commit_ids))
        )).tuples().all())
        return [statuses[commit_id] for commit_id in commit_ids]


# 소설 작업 실행과 정본 기억 어댑터가 모두 가짜라 모델 클라이언트를 쓰지 않는다.
_NO_LLM = cast(LLMClient, None)


def _loop(factory: SessionFactory, stop: asyncio.Event, alive: Path, **kwargs: Any) -> asyncio.Task[None]:
    return asyncio.create_task(worker.run_worker(factory, _NO_LLM, stop, alive_file=alive, **kwargs))


# ── 스위치 꺼짐 ────────────────────────────────────────────────────────────


async def test_worker_reads_no_bible_table_while_the_switch_is_off(
    committed_engine: AsyncEngine, registry: Registry, adapter: _GateAdapter, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """스위치가 꺼진 워커는 정본 기억 표를 읽는 문장을 하나도 내지 않는다 — 대기 작업, 작업 없이 준비된 확정, 만료된 실행 중
    작업이 표에 있어도, 만료 정리 바퀴를 지나도. 그 행들도 그대로다. 깨지는 시나리오: 꺼진 채 배포된 운영 워커가 정본 기억 표를
    고르거나 정리해, 내부 기능이 운영 DB 에 부하를 얹거나 행을 바꾼다."""
    monkeypatch.setattr(settings, "novel_bible_enabled", False)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    # 켜졌다면 실제로 돌 수 있게 등록부·어댑터는 가짜로 바꿔 둔다.
    adapter.gate.set()
    monkeypatch.setattr(entry, "REGISTRY", registry)
    monkeypatch.setattr(entry, "build_resolver", lambda llm_client=None: adapter.resolver())
    factory, novel_id, commit_ids = await _confirm_chapters(committed_engine, registry, 2)
    async with factory() as s:
        chapter, revision = await add_chapter(s, novel_id, 3, BODY)
        ready = await confirm(  # 슬롯이 없는 등록부로 확정하면 작업 없이 준비된 확정이 된다
            s, fake_registry(), novel_id=novel_id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
        )
        await s.execute(
            update(NovelBibleJob)
            .where(NovelBibleJob.commit_id == commit_ids[1])
            .values(status="running", attempts=1, claimed_at=func.now() - timedelta(hours=1))
        )
        await s.commit()
    commit_ids.append(ready.commit_id)
    before = (await _job_states(factory, novel_id), await _commit_states(factory, commit_ids))

    clock = _Clock(1000.0)
    stop = asyncio.Event()
    claims = 0
    original_claim = worker.claim_candidates

    async def claim(f: SessionFactory, limit: int) -> list[uuid.UUID]:
        nonlocal claims
        claims += 1
        if claims == 1:
            clock.now = 1070.0  # 둘째 바퀴가 만료 정리를 돈다
        if claims == 3:
            stop.set()
        return await original_claim(f, limit)

    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    monkeypatch.setattr(worker, "claim_candidates", claim)
    event.listen(committed_engine.sync_engine, "before_cursor_execute", record)
    try:
        await asyncio.wait_for(_loop(factory, stop, tmp_path / "alive", clock=clock), 30)
    finally:
        event.remove(committed_engine.sync_engine, "before_cursor_execute", record)

    assert claims == 3
    assert sum("FROM novel_jobs" in statement for statement in statements) == 4  # 고르기 셋 + 소설 만료 정리 하나
    assert [statement for statement in statements if "novel_bible_" in statement] == []
    assert (await _job_states(factory, novel_id), await _commit_states(factory, commit_ids)) == before


# ── 스위치 켜짐 ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("bible_on")
async def test_the_worker_carries_a_confirmed_chapter_to_a_committed_revision(
    committed_engine: AsyncEngine, registry: Registry, adapter: _GateAdapter, novel_side: _NovelSide,
    tmp_path: Path,
) -> None:
    """켜진 워커는 확정의 대기 작업을 돌리고, 작업이 모두 끝난 확정을 연결·검사·커밋해 리비전을 낸다. 깨지는 시나리오: 워커가
    작업만 돌리고 준비된 확정을 집지 않아, 확정이 추출 끝 상태에 영영 남는다."""
    adapter.gate.set()
    factory, novel_id, [commit_id] = await _confirm_chapters(committed_engine, registry, 1)
    stop = asyncio.Event()
    loop = _loop(factory, stop, tmp_path / "alive")
    try:
        await _eventually(lambda: _committed(factory, commit_id))
    finally:
        stop.set()
        await asyncio.wait_for(loop, 10)

    assert await _job_states(factory, novel_id) == [("succeeded", 1)]
    assert adapter.calls == ["facts.extract"]
    async with factory() as s:
        assert await s.scalar(
            select(func.count()).select_from(NovelBibleRevision).where(NovelBibleRevision.commit_id == commit_id)
        ) == 1


async def _committed(factory: SessionFactory, commit_id: uuid.UUID) -> bool:
    return (await _commit_states(factory, [commit_id])) == ["committed"]


@pytest.mark.usefixtures("bible_on")
async def test_novel_jobs_keep_their_free_slots_while_bible_work_runs(
    committed_engine: AsyncEngine, registry: Registry, adapter: _GateAdapter, novel_side: _NovelSide,
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """소설 상한 1·정본 기억 상한 1 에서 정본 기억 작업 셋이 기다리고 하나가 모델을 부르는 중이어도, 그 뒤에 들어온 소설 작업은
    소설 칸으로 집혀 함께 돈다. 정본 기억은 상한만큼만 돌고, 소설 고르기의 빈 칸은 소설 작업만 센다. 깨지는 시나리오: 정본 기억
    작업이 소설 칸을 함께 써서, 내부 기능이 도는 동안 사용자 소설 작업이 대기에 묶였다가 heartbeat 만료로 환불된다."""
    monkeypatch.setattr(settings, "novelize_worker_max_concurrent_jobs", 1)
    factory, novel_id, _ = await _confirm_chapters(committed_engine, registry, 3)
    novel_side.offer = lambda: adapter.in_flight == 1  # 정본 기억이 칸을 차지한 뒤에 소설 작업이 들어온다
    stop = asyncio.Event()
    loop = _loop(factory, stop, tmp_path / "alive")
    try:
        await _eventually(lambda: _true(novel_side.running == 1))
        await asyncio.sleep(0.2)  # 폴링 스무 바퀴 — 칸이 남았다면 정본 기억 작업을 더 집었을 시간
        assert (novel_side.running, adapter.in_flight) == (1, 1)
        assert sorted(await _job_states(factory, novel_id)) == [("queued", 0), ("queued", 0), ("running", 1)]
    finally:
        stop.set()
        adapter.gate.set()
        novel_side.finish.set()
        await asyncio.wait_for(loop, 10)

    assert adapter.peak == 1
    # 소설 작업이 도는 동안은 빈 칸이 없어 고르지 않는다 — 고르기는 늘 소설 상한 1 에서 소설 작업 수만 뺀 칸으로 불렸다.
    assert set(novel_side.limits) == {1}


@pytest.mark.usefixtures("bible_on")
async def test_drain_waits_for_bible_work(
    committed_engine: AsyncEngine, registry: Registry, adapter: _GateAdapter, novel_side: _NovelSide,
    tmp_path: Path,
) -> None:
    """정지 신호 뒤에는 도는 정본 기억 작업이 끝날 때까지 루프가 돌아오지 않고(취소하지 않는다), 기다리는 동안 살아 있음 파일을
    만지며, 새 작업을 집지 않는다. 깨지는 시나리오: 비우는 루프가 소설 작업만 기다리고 돌아와 정본 기억 작업이 프로세스와 함께
    잘리거나, 정지 뒤에도 정본 기억 작업을 새로 집는다."""
    factory, novel_id, _ = await _confirm_chapters(committed_engine, registry, 2)
    stop = asyncio.Event()
    alive = tmp_path / "alive"
    loop = _loop(factory, stop, alive)
    await _eventually(lambda: _true(adapter.in_flight == 1))

    stop.set()
    os.utime(alive, (0, 0))
    await _eventually(lambda: _true(alive.stat().st_mtime > 0))
    assert not loop.done()
    adapter.gate.set()
    await asyncio.wait_for(loop, 10)

    assert sorted(await _job_states(factory, novel_id)) == [("queued", 0), ("succeeded", 1)]
    assert adapter.calls == ["facts.extract"]


@pytest.mark.usefixtures("bible_on")
async def test_cancel_cancels_bible_work(
    committed_engine: AsyncEngine, registry: Registry, adapter: _GateAdapter, novel_side: _NovelSide,
    tmp_path: Path,
) -> None:
    """루프가 취소되면(정지 유예를 넘긴 강제 종료) 도는 정본 기억 작업도 취소되고, 그 작업은 실행 중으로 남아 만료 정리를
    기다린다. 깨지는 시나리오: 취소가 정본 기억 태스크에 전해지지 않아 프로세스가 끝난 뒤에도 매달린 태스크가 남는다."""
    factory, novel_id, _ = await _confirm_chapters(committed_engine, registry, 1)
    loop = _loop(factory, asyncio.Event(), tmp_path / "alive")
    await _eventually(lambda: _true(adapter.in_flight == 1))

    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop

    assert adapter.in_flight == 0
    assert await _job_states(factory, novel_id) == [("running", 1)]


@pytest.mark.usefixtures("bible_on")
async def test_a_failing_bible_poll_keeps_the_worker_alive(
    committed_engine: AsyncEngine, novel_side: _NovelSide, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """정본 기억 고르기가 계속 실패해도 루프는 살아 있고, 살아 있음 파일은 소설 고르기 성공으로 계속 갱신되며, 실패는 경고와
    의존성 실패 기록으로 남는다. 깨지는 시나리오: 꺼진 채 배포된 내부 기능의 조회 실패가 워커를 죽이거나 unhealthy 로 만들어,
    교체가 사용자 소설 워커를 되돌린다."""
    failures = 0
    captured: list[str] = []

    async def failing(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal failures
        failures += 1
        raise ConnectionRefusedError("정본 기억 표를 읽지 못한다")

    monkeypatch.setattr(pipeline, "process_ready_commit", failing)
    monkeypatch.setattr(entry, "capture_dependency_failure", lambda _exc=None, *, dependency: captured.append(dependency))
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    alive = tmp_path / "alive"
    stop = asyncio.Event()
    loop = _loop(factory, stop, alive)
    try:
        await _eventually(lambda: _true(failures >= 3 and alive.exists()))
        os.utime(alive, (0, 0))
        await _eventually(lambda: _true(alive.stat().st_mtime > 0))
        assert not loop.done()
    finally:
        stop.set()
        await asyncio.wait_for(loop, 10)

    assert set(captured) == {"novelize"}


@pytest.mark.parametrize("enabled", [False, True])
async def test_the_bible_sweep_runs_with_the_novel_sweep_only_while_switched_on(
    db_session: AsyncSession, novel_side: _NovelSide, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: bool,
    registry: Registry, adapter: _GateAdapter,
) -> None:
    """정본 기억 만료 정리는 스위치가 켜졌을 때만, 소설 만료 정리와 같은 바퀴에 돈다. 깨지는 시나리오: 켜진 워커가 정본 기억
    정리를 돌리지 않아 잘린 작업·연결이 실행 중으로 영영 남거나, 꺼진 워커가 정본 기억 표를 정리한다."""
    monkeypatch.setattr(settings, "novel_bible_enabled", enabled)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)
    monkeypatch.setattr(entry, "REGISTRY", registry)
    monkeypatch.setattr(entry, "build_resolver", lambda llm_client=None: adapter.resolver())
    clock = _Clock(1000.0)
    novel_sweeps: list[float] = []
    bible_sweeps: list[float] = []

    async def novel_sweep(_factory: Any) -> int:
        novel_sweeps.append(clock.now)
        return 0

    async def bible_sweep(_factory: Any) -> int:
        bible_sweeps.append(clock.now)
        return 0

    async def idle(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(worker, "expire_all_stale_jobs", novel_sweep)
    monkeypatch.setattr(entry, "expire_stale_work", bible_sweep)
    monkeypatch.setattr(pipeline, "process_ready_commit", idle)
    monkeypatch.setattr(entry, "run_next_job", idle)
    stop = asyncio.Event()

    async def polls(count: int) -> None:
        seen = len(novel_side.limits)
        await _eventually(lambda: _true(len(novel_side.limits) >= seen + count))

    loop = _loop(savepoint_factory(db_session), stop, tmp_path / "alive", clock=clock)
    try:
        await polls(2)  # 루프가 시작 시각(1000)을 읽은 뒤에 시계를 민다
        for now in (1069.9, 1070.0, 1129.9, 1130.0):
            clock.now = now
            await polls(2)
    finally:
        stop.set()
        await asyncio.wait_for(loop, 10)

    assert novel_sweeps == [1070.0, 1130.0]
    assert bible_sweeps == ([1070.0, 1130.0] if enabled else [])


# ── 기동 검증 ──────────────────────────────────────────────────────────────


async def test_bible_worker_starts_only_when_every_slot_has_its_prompt(
    db_session: AsyncSession, registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기동 때 배정된 어댑터의 문안 체인에 슬롯 채널이 없거나 그 검사가 실패하면 정본 기억만 끈다(None) — 오류 로그와 의존성
    실패 기록을 남기고, 소설 워커는 그대로 돈다. 채널이 다 있으면 정본 기억 처리기를 돌려준다. 깨지는 시나리오: 문안이 비었는데
    정본 기억을 켠 채 돌아 모든 작업이 문안 없음으로 실패하거나, 정본 기억 문안 결함이 소설 워커 기동까지 막는다."""
    captured: list[str] = []
    monkeypatch.setattr(entry, "capture_dependency_failure", lambda _exc=None, *, dependency: captured.append(dependency))
    monkeypatch.setattr(entry, "REGISTRY", registry)
    factory = savepoint_factory(db_session)

    monkeypatch.setattr(entry, "build_resolver", lambda llm_client=None: FakeAdapter().resolver())
    assert isinstance(await entry.BibleWorker.start(factory), entry.BibleWorker)
    assert captured == []

    @dataclass
    class _NoChannel(FakeAdapter):
        async def prompt_source(self, session: AsyncSession) -> PromptSource:
            return PromptSource(prompt_set_id=self.prompt_set_id, sections=[])

    monkeypatch.setattr(entry, "build_resolver", lambda llm_client=None: _NoChannel().resolver())
    assert await entry.BibleWorker.start(factory) is None

    @dataclass
    class _Broken(FakeAdapter):
        async def prompt_source(self, session: AsyncSession) -> PromptSource:
            raise ConnectionRefusedError("문안을 읽지 못한다")

    monkeypatch.setattr(entry, "build_resolver", lambda llm_client=None: _Broken().resolver())
    assert await entry.BibleWorker.start(factory) is None
    assert captured == ["novelize", "novelize"]


# ── 만료 정리 ──────────────────────────────────────────────────────────────


async def test_bible_sweep_requeues_expired_work_without_refund(
    db_session: AsyncSession, registry: Registry
) -> None:
    """만료 정리(작업·연결 상한 300초 + 60초를 넘겨 멈춘 것만): 실행 중으로 남은 작업은 시도가 남으면 대기(만료 사유, 재시도
    대기 시각), 다 썼으면 실패(만료). 연결·검사에 멈춘 확정은 추출 끝 상태로 되돌려 다음 바퀴에 다시 연결하게 하고(되돌린 횟수
    +1), 이미 세 번 되돌렸으면 실패(멈춤). 밀려난 확정의 대기 작업은 실패(취소). 기준보다 덜 멈춘 행은 그대로이고, 클로버 원장은
    한 행도 생기지 않는다. 깨지는 시나리오: 교체에서 잘린 워커가 남긴 작업·확정이 영영 실행 중으로 남아 그 화를 다시 확정해야만
    풀리거나, 유료 판정 단계가 시간 초과 → 되돌림을 끝없이 되풀이하거나, 살아 있는 작업을 빼앗아 두 번 돌린다."""
    factory = savepoint_factory(db_session)
    novel = await make_novel(db_session)
    empty = fake_registry()
    commits: list[uuid.UUID] = []
    for ordinal in range(1, 8):
        chapter, revision = await add_chapter(db_session, novel.id, ordinal, BODY)
        result = await confirm(
            db_session, registry if ordinal in (1, 2, 3, 7) else empty, novel_id=novel.id, chapter_id=chapter.id,
            revision_id=revision.id, actor=SYSTEM,
        )
        commits.append(result.commit_id)
    old, recent = func.now() - timedelta(seconds=361), func.now() - timedelta(seconds=330)
    for commit_id, attempts, claimed_at in ((commits[0], 1, old), (commits[1], 3, old), (commits[2], 1, recent)):
        await db_session.execute(
            update(NovelBibleJob).where(NovelBibleJob.commit_id == commit_id)
            .values(status="running", attempts=attempts, claimed_at=claimed_at)
        )
        await db_session.execute(
            update(NovelBibleCommit).where(NovelBibleCommit.id == commit_id).values(status="extracting")
        )
    for commit_id, status, restarts, started in (
        (commits[3], "linking", 0, old), (commits[4], "checking", 3, old), (commits[5], "linking", 0, recent)
    ):
        await db_session.execute(
            update(NovelBibleCommit).where(NovelBibleCommit.id == commit_id)
            .values(status=status, restarts=restarts, stage_started_at=started)
        )
    await db_session.execute(update(NovelBibleCommit).where(NovelBibleCommit.id == commits[6]).values(status="stale"))
    ledger_before = await db_session.scalar(select(func.count()).select_from(CloverLedger))

    await expire_stale_work(factory)

    jobs = (await db_session.execute(
        select(NovelBibleJob.commit_id, NovelBibleJob.status, NovelBibleJob.attempts, NovelBibleJob.failure_code,
               NovelBibleJob.available_at > func.now(), NovelBibleJob.finished_at.is_not(None))
        .where(NovelBibleJob.novel_id == novel.id)
    )).all()
    assert sorted((commits.index(commit_id), *rest) for commit_id, *rest in jobs) == [
        (0, "queued", 1, "expired", True, False),
        (1, "failed", 3, "expired", False, True),
        (2, "running", 1, None, False, False),
        (6, "failed", 0, "cancelled", False, True),
    ]
    rows = (await db_session.execute(
        select(NovelBibleCommit.id, NovelBibleCommit.status, NovelBibleCommit.failure_code, NovelBibleCommit.restarts)
        .where(NovelBibleCommit.id.in_(commits[3:6]))
    )).all()
    assert sorted((commits.index(commit_id), *rest) for commit_id, *rest in rows) == [
        (3, "extracting", None, 1),
        (4, "failed", "stalled", 3),
        (5, "linking", None, 0),
    ]
    assert await db_session.scalar(select(func.count()).select_from(CloverLedger)) == ledger_before
