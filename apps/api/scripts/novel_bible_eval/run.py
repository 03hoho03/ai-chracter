"""측정 실행 — 화 순서대로 확정하고 워커 대신 `run_until_idle` 로 끝까지 돌린 뒤, 확정 상태·검사 결과·작업 제안·호출 기록을
모은다. 탐침은 기본 화 뒤에 한 화로 붙여 확정하고 결과를 남긴 뒤 묶음 삭제로 지운다(삭제가 정본 기억 행도 지우는지 표마다 센다).
닫힌 값 불변 속성 모순 차단은 무엇과 무엇이 부딪쳤는지(갈래와 두 값)를 탐침 화를 지우기 전에 읽어 둔다.

확정과 처리는 운영 워커와 같은 입구 함수(`api.novel_bible.entry`)를 부른다 — 등록부와 규칙 목록도 거기서 오므로, 슬롯·규칙이
들어오면 하네스를 고치지 않아도 그 작업과 검사 결과가 모인다.

재시도 대기 중인 작업은 대기 시각을 지금으로 당겨 바로 다시 돌린다 — 측정은 재시도 간격을 재지 않는다. 공급자 한도로 실패한
호출은 기다리지 않고 다시 부르므로 세 번 안에 실패로 끝날 수 있다(그 실패도 실패율에 든다)."""

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import NovelChapter, NovelChapterRevision
from api.db.models.novel_bible import (
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvidence,
    NovelBibleFinding,
    NovelBibleJob,
    NovelBibleRevision,
)
from api.db.models.novel_bible_events import NovelBibleEvent, NovelBibleEventRelation
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.novel_bible.core.confirm import Actor
from api.novel_bible.core.contracts import AdapterCallError, AdapterResolver, BibleModelAdapter, PromptSource
from api.novel_bible.core.jobs import SessionFactory
from api.novel_bible.core.keys import normalize_name, predicate_norm
from api.novel_bible.core.types import Proposal, RenderedPrompt
from api.novel_bible.entry import confirm_chapter, run_until_idle
from api.novel_bible.ids import OperationKey, SlotId
from api.novel_bible.rules.blocking import closed_value
from api.novelize.deletion import delete_batch
from memory_eval.ledger import BudgetExceededError, Ledger

from novel_bible_eval.seed import SeededChapter, SeededNovel, add_chapter, seed_novel
from novel_bible_eval.spec import EvalSet

T = TypeVar("T", bound=BaseModel)
_ACTOR = Actor(kind="system")
# 재시도 대기를 당겨 다시 돌리는 바퀴 수 상한 — 작업 하나가 세 번 시도로 끝나므로 넉넉하다.
_DRAIN_ROUNDS = 20
_CLOSED_RULE = "immutable_attribute_mismatch"
# 탐침 화를 지운 뒤 그 화 몫이 남았는지 세는 정본 기억 표.
BIBLE_TABLES = (
    "commits", "revisions", "jobs", "findings", "evidence", "adaptation_candidates", "events", "event_relations", "facts",
    "knowledge",
)


class JobOutcome(BaseModel):
    slot: str
    status: str
    attempts: int
    failure_code: str | None
    proposal: dict[str, Any] | None
    calls: list[dict[str, Any]]


class ClosedClash(BaseModel):
    """닫힌 값 불변 속성 모순 차단 하나가 견준 갈래와 값 — 갈래는 규칙의 닫힌 값 판정(`closed_value`)이 내는 꼴(`number:단위`·
    `enum:범주`), 값은 그 판정의 비교 값(사전 값은 정규 값, 숫자는 수) 글자를 정렬한 것. 값을 읽지 못하면 갈래가 `unresolved`
    다 — 그 차단을 범주 집계에서 조용히 빠뜨리지 않으려는 것이다."""

    category: str
    values: list[str]


class ChapterOutcome(BaseModel):
    """확정 하나의 결과. 기본 화는 `probe` 가 None 이다. `block_ids` 는 개정의 블록 차례(문단 번호를 블록으로 푼다).
    `rows_left` 는 탐침 화를 지운 뒤 그 화 몫으로 남은 정본 기억 행 수(표마다, 모두 0 이어야 한다). `closed` 는 닫힌 값 불변
    속성 모순 차단마다 견준 갈래와 값이다. `play_rows`·`notes` 는 심기가 명세의 플레이 행·키워드 노트 차례마다 심은 행 id 라,
    각색 후보의 근거를 명세의 행·글로 되짚는다."""

    novel: str
    repeat: int
    ordinal: int
    probe: str | None
    status: str
    block_rules: list[str]
    warning_rules: list[str]
    block_ids: list[str]
    jobs: list[JobOutcome]
    rows_left: dict[str, int] = {}
    closed: list[ClosedClash] = []
    play_rows: list[str] = []
    notes: list[str] = []
    revision: str | None = None  # 확정한 화 개정 — 라벨 시트가 인용을 그 개정의 블록 글에서 잘라 낸다


class BudgetHalt(BaseException):
    """원장의 상한·멈춤 선에 닿았다. `Exception` 이 아닌 이유: 코어의 작업 실행은 어댑터의 모든 `Exception` 을 작업 실패로
    삼켜 재시도하므로, 멈춤 신호가 작업 실패로 기록되지 않고 하네스까지 올라오게 한다. 멈춘 작업은 실행 중으로 남는다 —
    격리 DB 의 그 소설은 버린다."""


@dataclass
class Meter:
    """어댑터 호출마다 시도 결과(성공은 None, 실패는 사유)를 세고, 원장이 있으면 견적으로 자리를 잡은 뒤 호출 기록 원소마다
    원가를 적는다. 이 해석기로 나가는 모델 호출은 추출과 모호 후보 판정이다 — 입구(`entry.run_until_idle`)가 넘겨받은 해석기로
    판정 함수를 만들므로, 감싼 해석기(`wrap`)를 넘기면 판정 호출도 원장에 들고 멈춤 선을 지킨다."""

    ledger: Ledger | None = None
    estimate_usd: float = 0.0
    attempts: list[tuple[str, str | None]] = field(default_factory=list)
    # 해석기를 지난 호출 기록 원소 전부 — 판정 호출의 기록은 작업 행에 남지 않으므로 보고서의 실제 모델·단계별 원가는 이것을 센다.
    calls: list[dict[str, Any]] = field(default_factory=list)

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
        """원장에 적지 못하면 무엇 때문이든 멈춘다 — 단가표에 없는 모델, 원장 파일 쓰기 실패, 토큰 칸 꼴 오류 모두. 원장에 적히지
        않은 유료 호출을 이어 부르지 않는다(그 호출 하나는 이미 나갔다). `Exception` 으로 올리면 코어의 작업 실행이 작업 실패로
        삼켜 다시 부르고, 그 호출들은 원장에 적히지 않아 멈춤 선에 다가가지 않는다."""
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
            except Exception as error:
                raise BudgetHalt(f"원장에 적지 못한 호출이라 멈춘다 — {type(error).__name__}: {error}") from error

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
                self._meter.calls.extend(records[start:])
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


# 닫힌 값을 견줄 속성 하나 — (주어 종류, 주어 정규 이름, 술어, 정규 값).
_Attribute = tuple[str, str, str, str]


def _clash(attributes: Sequence[_Attribute]) -> ClosedClash | None:
    """같은 주어·술어 속성들 중 같은 갈래의 서로 다른 닫힌 값. 다름은 앱처럼 닫힌 값으로 본다 — `180cm` 와 `180.0cm` 는 한 값이다."""
    read = [found for *_, value in attributes if (found := closed_value(value)) is not None]
    for category in dict.fromkeys(category for category, _ in read):
        values = sorted(str(value) for value in {value for kind, value in read if kind == category})
        if len(values) >= 2:
            return ClosedClash(category=category, values=values)
    return None


async def _closed_clashes(
    session: AsyncSession, commit_id: uuid.UUID, jobs: Sequence[JobOutcome]
) -> list[ClosedClash]:
    """닫힌 값 불변 속성 모순 차단마다 갈래와 두 값. 검사 결과는 항목 id 만 싣는다 — 앞선 정본 항목은 사실 행에서 읽고, 이번
    확정의 항목은 막힌 확정이라 행이 없으므로 이 확정의 사실 제안 중 같은 주어·술어의 불변 속성에서 읽는다(둘 다 이번 항목이면
    제안 안의 같은 주어·술어 속성끼리)."""
    findings = (
        await session.scalars(
            select(NovelBibleFinding.payload).where(
                NovelBibleFinding.commit_id == commit_id, NovelBibleFinding.severity == "block",
                NovelBibleFinding.rule == _CLOSED_RULE,
            )
        )
    ).all()
    drafts: list[_Attribute] = []
    for job in jobs:
        if job.slot != "facts" or job.proposal is None:
            continue
        for item in Proposal.model_validate(job.proposal).items:
            prop = item.proposition
            if item.table == "fact" and prop is not None and prop.kind == "attribute" and item.fields.get("immutable"):
                drafts.append((prop.subject_kind, normalize_name(prop.subject), predicate_norm("attribute", prop.attribute),
                               normalize_name(prop.value)))
    clashes = []
    for payload in findings:
        stored: list[_Attribute] = [
            (row.kind, row.name_norm, row.predicate_norm, row.value_norm)
            for row in await session.execute(
                select(NovelBibleEntity.kind, NovelBibleEntity.name_norm, NovelBibleFact.predicate_norm,
                       NovelBibleFact.value_norm)
                .join(NovelBibleEntity, NovelBibleEntity.id == NovelBibleFact.subject_entity_id)
                .where(NovelBibleFact.id.in_([uuid.UUID(item) for item in payload["items"]]))
            )
        ]
        heads = dict.fromkeys(attribute[:3] for attribute in stored or drafts)
        found = (_clash([a for a in (*stored, *drafts) if a[:3] == head]) for head in heads)
        clashes.append(next((clash for clash in found if clash is not None), ClosedClash(category="unresolved", values=[])))
    return clashes


async def _collect(
    session: AsyncSession, commit_id: uuid.UUID, *, novel: str, repeat: int, chapter: SeededChapter,
    probe: str | None, seeded: SeededNovel | None = None,
) -> ChapterOutcome:
    status = await session.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    findings = (
        await session.execute(
            select(NovelBibleFinding.severity, NovelBibleFinding.rule)
            .where(NovelBibleFinding.commit_id == commit_id)
            .order_by(NovelBibleFinding.rule)
        )
    ).all()
    jobs = [
        JobOutcome(
            slot=job.slot, status=job.status, attempts=job.attempts, failure_code=job.failure_code,
            proposal=job.proposal, calls=list(job.llm_calls),
        )
        for job in await session.scalars(
            select(NovelBibleJob).where(NovelBibleJob.commit_id == commit_id).order_by(NovelBibleJob.slot)
        )
    ]
    return ChapterOutcome(
        novel=novel, repeat=repeat, ordinal=chapter.ordinal, probe=probe, status=str(status),
        block_rules=[row.rule for row in findings if row.severity == "block"],
        warning_rules=[row.rule for row in findings if row.severity == "warning"],
        block_ids=[str(block) for block in chapter.block_ids],
        revision=str(chapter.revision_id),
        jobs=jobs,
        closed=await _closed_clashes(session, commit_id, jobs),
        play_rows=[str(row) for row in seeded.play_row_ids] if seeded is not None else [],
        notes=[str(note) for note in seeded.note_ids] if seeded is not None else [],
    )


async def _rows_left(
    session: AsyncSession, chapter_id: uuid.UUID, commits: Sequence[uuid.UUID], revisions: Sequence[uuid.UUID]
) -> dict[str, int]:
    """지운 화 몫으로 남은 정본 기억 행 — 확정은 그 화, 리비전·작업·검사 결과는 그 화 확정, 근거는 그 확정의 리비전, 항목·각색
    후보는 그 화를 가리키는 행."""
    where: dict[str, tuple[Any, ColumnElement[bool]]] = {
        "commits": (NovelBibleCommit, NovelBibleCommit.chapter_id == chapter_id),
        "revisions": (NovelBibleRevision, NovelBibleRevision.commit_id.in_(commits)),
        "jobs": (NovelBibleJob, NovelBibleJob.commit_id.in_(commits)),
        "findings": (NovelBibleFinding, NovelBibleFinding.commit_id.in_(commits)),
        "evidence": (NovelBibleEvidence, NovelBibleEvidence.created_revision_id.in_(revisions)),
        "adaptation_candidates": (NovelBibleAdaptationCandidate, NovelBibleAdaptationCandidate.chapter_id == chapter_id),
        "events": (NovelBibleEvent, NovelBibleEvent.chapter_id == chapter_id),
        "event_relations": (NovelBibleEventRelation, NovelBibleEventRelation.chapter_id == chapter_id),
        "facts": (NovelBibleFact, NovelBibleFact.chapter_id == chapter_id),
        "knowledge": (NovelBibleKnowledge, NovelBibleKnowledge.chapter_id == chapter_id),
    }
    return {
        table: int(await session.scalar(select(func.count()).select_from(model).where(clause)) or 0)
        for table, (model, clause) in where.items()
    }


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
                        await _collect(session, commit_id, novel=spec.key, repeat=repeat, chapter=chapter, probe=None,
                                       seeded=seeded)
                    )
            if repeat != 1:
                continue
            for probe in spec.probes:
                async with factory() as session, session.begin():
                    attached = await add_chapter(session, seeded.novel_id, len(spec.chapters) + 1, probe.chapter)
                commit_id = await _confirm(factory, resolver, seeded.novel_id, attached, slots)
                async with factory() as session:
                    outcome = await _collect(
                        session, commit_id, novel=spec.key, repeat=repeat, chapter=attached, probe=probe.key,
                        seeded=seeded,
                    )
                    commits = list(
                        await session.scalars(
                            select(NovelBibleCommit.id).where(NovelBibleCommit.chapter_id == attached.chapter_id)
                        )
                    )
                    revisions = list(
                        await session.scalars(select(NovelBibleRevision.id).where(NovelBibleRevision.commit_id.in_(commits)))
                    )
                assert attached.batch_id is not None  # 하네스가 붙인 화는 늘 제 묶음에 든다
                async with factory() as session, session.begin():
                    await delete_batch(session, novel_id=seeded.novel_id, batch_id=attached.batch_id,
                                       freed_storage_keys=[])
                async with factory() as session:
                    left = await _rows_left(session, attached.chapter_id, commits, revisions)
                collected.append(outcome.model_copy(update={"rows_left": left}))
    return collected


async def extract_chapters(
    factory: SessionFactory, resolver: AdapterResolver, novel_id: uuid.UUID, *, count: int,
    slots: frozenset[SlotId] | None = None, outcomes: list[ChapterOutcome] | None = None,
) -> list[ChapterOutcome]:
    """이미 있는 소설(사람 라벨용 사본)의 앞 `count` 화를 화마다 최신 개정으로 차례로 확정한다. 차단이 나도 다음 화로 간다 —
    라벨은 확정 항목이 아니라 작업의 추출 제안을 대상으로 한다. 결과는 `outcomes` 에 화마다 더한다 — 중간에 멈춰도 끝난 화의
    결과가 남는다."""
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
    collected = outcomes if outcomes is not None else []
    for chapter in chapters:
        commit_id = await _confirm(factory, resolver, novel_id, chapter, slots)
        async with factory() as session:
            collected.append(
                await _collect(session, commit_id, novel=str(novel_id), repeat=1, chapter=chapter, probe=None)
            )
    return collected
