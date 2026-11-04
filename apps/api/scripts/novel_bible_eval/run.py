"""측정 실행 — 화 순서대로 확정하고 워커 대신 `run_until_idle` 로 끝까지 돌린 뒤, 확정 상태·검사 결과·작업 제안·호출 기록을
모은다. 탐침은 기본 화 뒤에 한 화로 붙여 확정하고 결과를 남긴 뒤 묶음 삭제로 지운다(삭제가 정본 기억 행도 지우는지 함께 센다).

확정과 처리는 운영 워커와 같은 입구 함수(`api.novel_bible.entry`)를 부른다 — 등록부와 규칙 목록도 거기서 오므로, 슬롯·규칙이
들어오면 하네스를 고치지 않아도 그 작업과 검사 결과가 모인다.

재시도 대기 중인 작업은 대기 시각을 지금으로 당겨 바로 다시 돌린다 — 측정은 재시도 간격을 재지 않는다. 공급자 한도로 실패한
호출은 기다리지 않고 다시 부르므로 세 번 안에 실패로 끝날 수 있다(그 실패도 실패율에 든다)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import NovelChapter, NovelChapterRevision
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleFinding, NovelBibleJob
from api.novel_bible.core.confirm import Actor
from api.novel_bible.core.contracts import AdapterCallError, AdapterResolver, BibleModelAdapter, PromptSource
from api.novel_bible.core.jobs import SessionFactory
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.entry import confirm_chapter, run_until_idle
from api.novel_bible.ids import OperationKey, SlotId
from api.novelize.deletion import delete_batch
from memory_eval.ledger import BudgetExceededError, Ledger

from novel_bible_eval.seed import SeededChapter, add_chapter, seed_novel
from novel_bible_eval.spec import EvalSet

T = TypeVar("T", bound=BaseModel)
_ACTOR = Actor(kind="system")
# 재시도 대기를 당겨 다시 돌리는 바퀴 수 상한 — 작업 하나가 세 번 시도로 끝나므로 넉넉하다.
_DRAIN_ROUNDS = 20


class JobOutcome(BaseModel):
    slot: str
    status: str
    attempts: int
    failure_code: str | None
    proposal: dict[str, Any] | None
    calls: list[dict[str, Any]]


class ChapterOutcome(BaseModel):
    """확정 하나의 결과. 기본 화는 `probe` 가 None 이다. `block_ids` 는 개정의 블록 차례(문단 번호를 블록으로 푼다).
    `rows_left` 는 탐침 화를 지운 뒤 그 화에 남은 정본 기억 확정 수(0 이어야 한다)."""

    novel: str
    repeat: int
    ordinal: int
    probe: str | None
    status: str
    block_rules: list[str]
    warning_rules: list[str]
    block_ids: list[str]
    jobs: list[JobOutcome]
    rows_left: int = 0
    revision: str | None = None  # 확정한 화 개정 — 라벨 시트가 인용을 그 개정의 블록 글에서 잘라 낸다


class BudgetHalt(BaseException):
    """원장의 상한·멈춤 선에 닿았다. `Exception` 이 아닌 이유: 코어의 작업 실행은 어댑터의 모든 `Exception` 을 작업 실패로
    삼켜 재시도하므로, 멈춤 신호가 작업 실패로 기록되지 않고 하네스까지 올라오게 한다. 멈춘 작업은 실행 중으로 남는다 —
    격리 DB 의 그 소설은 버린다."""


@dataclass
class Meter:
    """어댑터 호출마다 시도 결과(성공은 None, 실패는 사유)를 세고, 원장이 있으면 견적으로 자리를 잡은 뒤 호출 기록 원소마다
    원가를 적는다. 판정 호출도 같은 해석기를 지나므로 함께 센다."""

    ledger: Ledger | None = None
    estimate_usd: float = 0.0
    attempts: list[tuple[str, str | None]] = field(default_factory=list)

    @contextmanager
    def reserved(self) -> Iterator[None]:
        if self.ledger is None:
            yield
            return
        try:
            with self.ledger.reserve(self.estimate_usd):
                yield
        except BudgetExceededError as error:
            raise BudgetHalt(str(error)) from error

    def charge(self, stage: str, records: list[dict[str, Any]]) -> None:
        """단가표에 없는 모델의 호출이면 멈춘다 — 원가를 모르는 유료 호출을 이어 부르지 않는다(그 호출 하나는 이미 나갔다)."""
        if self.ledger is None:
            return
        for record in records:
            try:
                self.ledger.append(
                    stage=stage, call_site=str(record.get("callSite")), model=str(record.get("model")),
                    input_tokens=int(record.get("promptTokens") or 0),
                    cached_tokens=int(record.get("cachedTokens") or 0),
                    cache_write_tokens=int(record.get("cacheWriteTokens") or 0),
                    output_tokens=int(record.get("outputTokens") or 0),
                    thoughts_tokens=int(record.get("thoughtsTokens") or 0),
                )
            except KeyError as error:
                raise BudgetHalt(f"원가를 모르는 호출이라 멈춘다 — {error}") from error

    def wrap(self, resolver: AdapterResolver) -> AdapterResolver:
        return lambda operation: _MeteredAdapter(resolver(operation), self)


class _MeteredAdapter:
    def __init__(self, inner: BibleModelAdapter, meter: Meter) -> None:
        self._inner = inner
        self._meter = meter
        self.id = inner.id
        self.capabilities = inner.capabilities

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        return await self._inner.prompt_source(session)

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        # 멈춤 검사가 자리 잡기를 감싸므로 멈추면 부르지 않는다. 기록은 호출이 끝난 뒤(실패해도) 그 호출이 더한 원소만 적는다.
        with self._meter.reserved():
            start = len(records)
            try:
                output = await self._inner.structured(prompt, schema, records=records, stage=stage)
            except AdapterCallError as error:
                self._meter.attempts.append((stage, error.code))
                raise
            finally:
                self._meter.charge(stage, records[start:])
            self._meter.attempts.append((stage, None))
            return output


async def _drain(factory: SessionFactory, resolver: AdapterResolver, novel_id: uuid.UUID) -> None:
    for _ in range(_DRAIN_ROUNDS):
        await run_until_idle(factory, resolver, novel_id=novel_id)
        async with factory() as session, session.begin():
            pulled = await session.execute(
                update(NovelBibleJob)
                .where(
                    NovelBibleJob.novel_id == novel_id, NovelBibleJob.status == "queued",
                    NovelBibleJob.commit_id.in_(
                        select(NovelBibleCommit.id).where(NovelBibleCommit.status.in_(("pending", "extracting")))
                    ),
                )
                .values(available_at=func.now())
            )
        if not pulled.rowcount:  # type: ignore[attr-defined]  # UPDATE 결과는 CursorResult 다
            return
    raise RuntimeError(f"소설 {novel_id} 의 정본 기억 작업이 {_DRAIN_ROUNDS} 바퀴 안에 끝나지 않는다")


async def _collect(
    session: AsyncSession, commit_id: uuid.UUID, *, novel: str, repeat: int, chapter: SeededChapter,
    probe: str | None,
) -> ChapterOutcome:
    status = await session.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    findings = (
        await session.execute(
            select(NovelBibleFinding.severity, NovelBibleFinding.rule)
            .where(NovelBibleFinding.commit_id == commit_id)
            .order_by(NovelBibleFinding.rule)
        )
    ).all()
    jobs = (
        await session.execute(
            select(NovelBibleJob).where(NovelBibleJob.commit_id == commit_id).order_by(NovelBibleJob.slot)
        )
    ).scalars()
    return ChapterOutcome(
        novel=novel, repeat=repeat, ordinal=chapter.ordinal, probe=probe, status=str(status),
        block_rules=[row.rule for row in findings if row.severity == "block"],
        warning_rules=[row.rule for row in findings if row.severity == "warning"],
        block_ids=[str(block) for block in chapter.block_ids],
        revision=str(chapter.revision_id),
        jobs=[
            JobOutcome(
                slot=job.slot, status=job.status, attempts=job.attempts, failure_code=job.failure_code,
                proposal=job.proposal, calls=list(job.llm_calls),
            )
            for job in jobs
        ],
    )


async def _confirm(
    factory: SessionFactory, resolver: AdapterResolver, novel_id: uuid.UUID, chapter: SeededChapter,
    slots: frozenset[SlotId] | None,
) -> uuid.UUID:
    async with factory() as session, session.begin():
        result = await confirm_chapter(
            session, novel_id=novel_id, chapter_id=chapter.chapter_id, revision_id=chapter.revision_id,
            actor=_ACTOR, slots=slots, resolver=resolver,
        )
    await _drain(factory, resolver, novel_id)
    return result.commit_id


async def run_set(
    factory: SessionFactory, resolver: AdapterResolver, eval_set: EvalSet, *, repeats: int = 1,
    slots: frozenset[SlotId] | None = None, outcomes: list[ChapterOutcome] | None = None,
) -> list[ChapterOutcome]:
    """반복마다 소설을 새로 심어 기본 화를 순서대로 확정하고, 첫 반복의 소설에만 탐침을 붙인다. 결과는 `outcomes` 에 하나씩
    더한다 — 원장 멈춤(`BudgetHalt`)으로 중간에 끊겨도 그때까지 모은 결과가 남는다."""
    collected = outcomes if outcomes is not None else []
    for repeat in range(1, repeats + 1):
        for spec in eval_set.novels:
            async with factory() as session, session.begin():
                seeded = await seed_novel(session, spec)
            for chapter in seeded.chapters:
                commit_id = await _confirm(factory, resolver, seeded.novel_id, chapter, slots)
                async with factory() as session:
                    collected.append(
                        await _collect(session, commit_id, novel=spec.key, repeat=repeat, chapter=chapter, probe=None)
                    )
            if repeat != 1:
                continue
            for probe in spec.probes:
                async with factory() as session, session.begin():
                    attached = await add_chapter(session, seeded.novel_id, len(spec.chapters) + 1, probe.chapter)
                commit_id = await _confirm(factory, resolver, seeded.novel_id, attached, slots)
                async with factory() as session:
                    outcome = await _collect(
                        session, commit_id, novel=spec.key, repeat=repeat, chapter=attached, probe=probe.key
                    )
                assert attached.batch_id is not None  # 하네스가 붙인 화는 늘 제 묶음에 든다
                async with factory() as session, session.begin():
                    await delete_batch(session, novel_id=seeded.novel_id, batch_id=attached.batch_id,
                                       freed_storage_keys=[])
                async with factory() as session:
                    left = await session.scalar(
                        select(func.count()).where(NovelBibleCommit.chapter_id == attached.chapter_id)
                    )
                collected.append(outcome.model_copy(update={"rows_left": int(left or 0)}))
    return collected


async def extract_chapters(
    factory: SessionFactory, resolver: AdapterResolver, novel_id: uuid.UUID, *, count: int,
    slots: frozenset[SlotId] | None = None,
) -> list[ChapterOutcome]:
    """이미 있는 소설(사람 라벨용 사본)의 앞 `count` 화를 화마다 최신 개정으로 차례로 확정한다. 차단이 나도 다음 화로 간다 —
    라벨은 확정 항목이 아니라 작업의 추출 제안을 대상으로 한다."""
    async with factory() as session:
        rows = (
            await session.execute(
                select(NovelChapter.id, NovelChapter.ordinal, NovelChapter.batch_id)
                .where(NovelChapter.novel_id == novel_id)
                .order_by(NovelChapter.ordinal)
                .limit(count)
            )
        ).all()
        chapters = []
        for row in rows:
            revision = await session.scalar(
                select(NovelChapterRevision)
                .where(NovelChapterRevision.chapter_id == row.id)
                .order_by(NovelChapterRevision.revision_no.desc())
                .limit(1)
            )
            assert revision is not None  # 화는 첫 개정과 함께 만들어진다
            chapters.append(
                SeededChapter(row.ordinal, row.id, row.batch_id, revision.id, tuple(revision.block_ids))
            )
    outcomes = []
    for chapter in chapters:
        commit_id = await _confirm(factory, resolver, novel_id, chapter, slots)
        async with factory() as session:
            outcomes.append(
                await _collect(session, commit_id, novel=str(novel_id), repeat=1, chapter=chapter, probe=None)
            )
    return outcomes
