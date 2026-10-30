"""정본 기억 확정의 처리 — 슬롯 작업 → 연결 → 검사 → 커밋(머리 비교).

슬롯은 가짜 셋(사건·사실·지식)과 가짜 원작이고 어댑터도 가짜다. 코어가 무엇을 언제 부르는지(호출 수), 무엇을 다시 쓰는지(추출
캐시·진 쪽의 저장된 제안), 정본이 어떻게 바뀌거나 그대로인지(리비전·항목·만료)를 본다. 경합은 커밋되는 독립 커넥션으로
일으키고 순서는 시간이 아니라 잠금 대기로 강제한다."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import Novel, NovelChapterPublication
from api.db.models.novel_bible import (
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvidence,
    NovelBibleFinding,
    NovelBibleJob,
    NovelBibleRevision,
)
from api.db.models.novel_bible_events import NovelBibleEvent
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.jobs import run_next_job
from api.novel_bible.core import pipeline
from api.novel_bible.core.pipeline import link_check_commit, start_linking
from api.novel_bible.core.types import BibleSnapshot
from api.novelize.deletion import delete_batch, strip_author_only_data
from factories import _committed_engine, _wait_until_a_lock_is_awaited
from novel_bible_fakes import (
    COMMITTED_DOMAIN,
    FakeAdapter,
    FakeRule,
    FakeSlot,
    FakeSource,
    SessionFactory,
    add_chapter,
    add_revision,
    delete_committed_novels,
    drain,
    events_slot,
    facts_slot,
    fake_registry,
    full_registry,
    knowledge_slot,
    make_novel,
    publish,
    savepoint_factory,
)

BODY = "사건: 둘이 정원에서 만난다\n\n사실: 하나|life|-|alive|참\n\n앎: 둘|knows|하나|life|-|alive"
SECOND_BODY = "사건: 셋이 시장에 간다\n\n사실: 셋|possession|-|검|참\n\n앎: 하나|believes|셋|possession|-|검"
SYSTEM = Actor(kind="system")


async def _confirm(db: AsyncSession, registry: Any, novel_id: uuid.UUID, chapter_id: uuid.UUID,
                   revision_id: uuid.UUID) -> uuid.UUID:
    result = await confirm(db, registry, novel_id=novel_id, chapter_id=chapter_id, revision_id=revision_id,
                           actor=SYSTEM)
    return result.commit_id


async def _commit_row(db: AsyncSession, commit_id: uuid.UUID) -> Any:
    return (
        await db.execute(
            select(NovelBibleCommit.status, NovelBibleCommit.failure_code, NovelBibleCommit.cas_losses).where(
                NovelBibleCommit.id == commit_id
            )
        )
    ).one_or_none()


async def _head(db: AsyncSession, novel_id: uuid.UUID) -> Any:
    return (
        await db.execute(
            select(NovelBibleRevision.id, NovelBibleRevision.revision_no, NovelBibleRevision.parent_revision_id)
            .where(NovelBibleRevision.novel_id == novel_id)
            .order_by(NovelBibleRevision.revision_no.desc())
            .limit(1)
        )
    ).one_or_none()


async def _count(db: AsyncSession, model: Any, novel_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(model.novel_id == novel_id)) or 0)


async def _run_jobs(factory: SessionFactory, registry: Any, adapter: FakeAdapter) -> None:
    while await run_next_job(factory, registry, adapter.resolver()):
        pass


async def test_a_confirmed_chapter_commits_items_linked_to_its_events(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    registry, adapter = full_registry(), FakeAdapter()

    commit_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(savepoint_factory(db_session), registry, adapter)

    assert (await _commit_row(db_session, commit_id)).status == "committed"
    head = await _head(db_session, novel.id)
    assert (head.revision_no, head.parent_revision_id) == (1, None)
    event = (await db_session.scalars(select(NovelBibleEvent).where(NovelBibleEvent.novel_id == novel.id))).one()
    fact = (await db_session.scalars(select(NovelBibleFact).where(NovelBibleFact.novel_id == novel.id))).one()
    knowledge = (
        await db_session.scalars(select(NovelBibleKnowledge).where(NovelBibleKnowledge.novel_id == novel.id))
    ).one()
    assert fact.valid_from_event_id == event.id and knowledge.known_since_event_id == event.id
    assert knowledge.fact_key == fact.fact_key
    assert event.created_revision_id == fact.created_revision_id == head.id
    names = set(await db_session.scalars(select(NovelBibleEntity.name).where(NovelBibleEntity.novel_id == novel.id)))
    assert names == {"하나", "둘"}
    evidence = (
        await db_session.execute(
            select(NovelBibleEvidence.item_id, NovelBibleEvidence.block_id).where(
                NovelBibleEvidence.novel_id == novel.id
            )
        )
    ).all()
    assert {row.item_id for row in evidence} == {event.id, fact.id, knowledge.id}
    assert {row.block_id for row in evidence} <= set(revision.block_ids)
    jobs = (await db_session.scalars(select(NovelBibleJob).where(NovelBibleJob.commit_id == commit_id))).all()
    assert {(job.slot, job.status, job.attempts, job.adapter_id) for job in jobs} == {
        ("events", "succeeded", 1, "fake"), ("facts", "succeeded", 1, "fake"), ("knowledge", "succeeded", 1, "fake")
    }
    assert all(job.llm_calls and job.prompt_set_id == adapter.prompt_set_id for job in jobs)
    assert sorted(adapter.calls) == ["events.extract", "facts.extract", "knowledge.extract"]


async def test_a_slot_that_exhausts_retries_fails_the_commit_but_caches_the_others(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    first_chapter, first_revision = await add_chapter(db_session, novel.id, 1, BODY)
    chapter, revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    await _confirm(db_session, registry, novel.id, first_chapter.id, first_revision.id)
    await drain(factory, registry, adapter)
    head_before = await _head(db_session, novel.id)
    facts_before = await _count(db_session, NovelBibleFact, novel.id)
    adapter.failing.add("facts.extract")

    failed_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)

    failed = await _commit_row(db_session, failed_id)
    assert (failed.status, failed.failure_code) == ("failed", "slot_failed")
    jobs = {
        job.slot: job
        for job in (await db_session.scalars(select(NovelBibleJob).where(NovelBibleJob.commit_id == failed_id)))
    }
    assert (jobs["facts"].status, jobs["facts"].attempts, jobs["facts"].failure_code) == ("failed", 3, "schema_invalid")
    assert jobs["events"].status == jobs["knowledge"].status == "succeeded"
    assert jobs["events"].proposal is not None and jobs["knowledge"].proposal is not None
    assert await _head(db_session, novel.id) == head_before
    assert await _count(db_session, NovelBibleFact, novel.id) == facts_before

    adapter.failing.clear()
    calls_before = len(adapter.calls)
    retry_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)

    assert (await _commit_row(db_session, retry_id)).status == "committed"
    assert adapter.calls[calls_before:] == ["facts.extract"]
    reused = dict(
        (await db_session.execute(
            select(NovelBibleJob.slot, NovelBibleJob.reused_from_job_id).where(NovelBibleJob.commit_id == retry_id)
        )).tuples().all()
    )
    assert reused == {"events": jobs["events"].id, "knowledge": jobs["knowledge"].id, "facts": None}


async def _entity_names(db: AsyncSession, novel_id: uuid.UUID) -> dict[uuid.UUID, tuple[str, str]]:
    rows = (
        await db.execute(
            select(NovelBibleEntity.id, NovelBibleEntity.kind, NovelBibleEntity.name_norm).where(
                NovelBibleEntity.novel_id == novel_id
            )
        )
    ).all()
    return {row.id: (row.kind, row.name_norm) for row in rows}


async def _comparable_items(db: AsyncSession, novel_id: uuid.UUID) -> dict[str, list[tuple[Any, ...]]]:
    """슬롯별 항목을 소설과 무관한 꼴로 — 개체 id 는 (종류, 정규 이름), 블록은 개수만. 연결 칸은 따로 본다."""
    names = await _entity_names(db, novel_id)
    events = (await db.scalars(select(NovelBibleEvent).where(NovelBibleEvent.novel_id == novel_id))).all()
    facts = (await db.scalars(select(NovelBibleFact).where(NovelBibleFact.novel_id == novel_id))).all()
    knowledge = (await db.scalars(select(NovelBibleKnowledge).where(NovelBibleKnowledge.novel_id == novel_id))).all()
    return {
        "events": sorted((e.ordinal, e.summary, e.actuality, len(e.anchor_block_ids)) for e in events),
        "facts": sorted(
            (f.fact_key, names[f.subject_entity_id], f.kind, f.predicate_norm, f.value_norm,
             names[f.value_entity_id] if f.value_entity_id else None, f.holds, f.scope)
            for f in facts
        ),
        "knowledge": sorted(
            (k.fact_key, names[k.knower_entity_id], k.kind, sorted(k.proposition.items())) for k in knowledge
        ),
    }


def _new_facts(snapshot: BibleSnapshot) -> tuple[uuid.UUID, ...]:
    return tuple(fact.id for fact in snapshot.facts or () if fact.id in snapshot.new_ids)


@pytest.mark.parametrize("dropped", ["events", "facts", "knowledge"])
async def test_dropping_a_slot_keeps_the_other_slots_rows_and_leaves_links_undetermined(
    db_session: AsyncSession, dropped: str
) -> None:
    body = BODY + "\n\n" + SECOND_BODY
    rules = [FakeRule(pick=_new_facts, severity="warning", rule="onset_unstated", slots=frozenset({"facts"}))]
    outcomes: dict[str, tuple[uuid.UUID, uuid.UUID]] = {}
    for label, slots in [
        ("full", [events_slot(), facts_slot(), knowledge_slot()]),
        ("partial", [slot for slot in (events_slot(), facts_slot(), knowledge_slot()) if slot.id != dropped]),
    ]:
        novel = await make_novel(db_session)
        chapter, revision = await add_chapter(db_session, novel.id, 1, body)
        registry = fake_registry(*slots)
        commit_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
        await drain(savepoint_factory(db_session), registry, FakeAdapter(), rules)
        assert (await _commit_row(db_session, commit_id)).status == "committed"
        outcomes[label] = (novel.id, commit_id)

    full = await _comparable_items(db_session, outcomes["full"][0])
    partial = await _comparable_items(db_session, outcomes["partial"][0])
    for slot_id in ("events", "facts", "knowledge"):
        assert partial[slot_id] == ([] if slot_id == dropped else full[slot_id])
    partial_novel, partial_commit = outcomes["partial"]
    assert await db_session.scalar(
        select(func.count()).select_from(NovelBibleJob).where(
            NovelBibleJob.commit_id == partial_commit, NovelBibleJob.slot == dropped
        )
    ) == 0
    valid_from = set(
        await db_session.scalars(select(NovelBibleFact.valid_from_event_id).where(NovelBibleFact.novel_id == partial_novel))
    )
    known_since = set(
        await db_session.scalars(
            select(NovelBibleKnowledge.known_since_event_id).where(NovelBibleKnowledge.novel_id == partial_novel)
        )
    )
    if dropped == "events":
        assert valid_from == {None} and known_since == {None}
    else:
        assert None not in valid_from | known_since
    findings = await _count(db_session, NovelBibleFinding, partial_novel)
    assert (findings == 0) == (dropped == "facts")


async def test_illustration_revision_reconfirm_reuses_extraction_after_other_chapters_commit(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    other, other_revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    first_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)
    # 2화가 커밋되며 개체("셋")가 늘어 1화 입력의 힌트(아는 개체 목록)가 바뀐다.
    await _confirm(db_session, registry, novel.id, other.id, other_revision.id)
    await drain(factory, registry, adapter)
    illustrated = await add_revision(db_session, chapter.id, BODY, block_ids=revision.block_ids, source="illustration")
    calls_before = len(adapter.calls)

    commit_id = await _confirm(db_session, registry, novel.id, chapter.id, illustrated.id)
    await drain(factory, registry, adapter)

    assert (await _commit_row(db_session, commit_id)).status == "committed"
    assert adapter.calls[calls_before:] == []
    first_jobs = dict(
        (await db_session.execute(
            select(NovelBibleJob.slot, NovelBibleJob.id).where(NovelBibleJob.commit_id == first_id)
        )).tuples().all()
    )
    reused = dict(
        (await db_session.execute(
            select(NovelBibleJob.slot, NovelBibleJob.reused_from_job_id).where(NovelBibleJob.commit_id == commit_id)
        )).tuples().all()
    )
    assert reused == first_jobs


async def _change_body(db: AsyncSession, chapter_id: uuid.UUID, block_ids: list[uuid.UUID], adapter: FakeAdapter,
                       source: FakeSource) -> uuid.UUID:
    return (await add_revision(db, chapter_id, BODY + "\n\n사건: 덧붙인 장면")).id


async def _change_block_ids(db: AsyncSession, chapter_id: uuid.UUID, block_ids: list[uuid.UUID],
                            adapter: FakeAdapter, source: FakeSource) -> uuid.UUID:
    return (await add_revision(db, chapter_id, BODY)).id


async def _change_prompt_set(db: AsyncSession, chapter_id: uuid.UUID, block_ids: list[uuid.UUID],
                             adapter: FakeAdapter, source: FakeSource) -> uuid.UUID:
    adapter.prompt_set_id = uuid.uuid4()
    return (await add_revision(db, chapter_id, BODY, block_ids=block_ids, source="illustration")).id


async def _change_source_note(db: AsyncSession, chapter_id: uuid.UUID, block_ids: list[uuid.UUID],
                              adapter: FakeAdapter, source: FakeSource) -> uuid.UUID:
    source.note = "원작 노트 둘"
    return (await add_revision(db, chapter_id, BODY, block_ids=block_ids, source="illustration")).id


Change = Callable[[AsyncSession, uuid.UUID, list[uuid.UUID], FakeAdapter, FakeSource], Awaitable[uuid.UUID]]


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_change_body, id="body"),
        pytest.param(_change_block_ids, id="block-ids-only"),
        pytest.param(_change_prompt_set, id="prompt-set"),
        pytest.param(_change_source_note, id="source-note"),
    ],
)
async def test_the_extraction_cache_misses_when_chapter_inputs_change(db_session: AsyncSession, change: Change) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    source = FakeSource(note="원작 노트 하나")
    registry, adapter = full_registry(source), FakeAdapter()
    factory = savepoint_factory(db_session)
    await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)
    calls_before = len(adapter.calls)

    changed = await change(db_session, chapter.id, list(revision.block_ids), adapter, source)
    commit_id = await _confirm(db_session, registry, novel.id, chapter.id, changed)
    await drain(factory, registry, adapter)

    assert (await _commit_row(db_session, commit_id)).status == "committed"
    assert sorted(adapter.calls[calls_before:]) == ["events.extract", "facts.extract", "knowledge.extract"]


async def test_a_blocking_finding_on_a_new_item_blocks_the_commit(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    registry = full_registry()

    commit_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(savepoint_factory(db_session), registry, FakeAdapter(), [FakeRule(pick=_new_facts)])

    assert (await _commit_row(db_session, commit_id)).status == "blocked"
    finding = (await db_session.scalars(select(NovelBibleFinding).where(NovelBibleFinding.commit_id == commit_id))).one()
    assert (finding.severity, finding.rule) == ("block", "exit_then_appearance")
    assert len(finding.payload["items"]) == 1
    assert await _head(db_session, novel.id) is None
    assert await _count(db_session, NovelBibleFact, novel.id) == 0


async def test_findings_that_touch_no_new_item_are_dropped(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    later, later_revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)
    old_only = FakeRule(pick=lambda snap: tuple(f.id for f in snap.facts or () if f.id not in snap.new_ids))

    commit_id = await _confirm(db_session, registry, novel.id, later.id, later_revision.id)
    await drain(factory, registry, adapter, [old_only])

    assert (await _commit_row(db_session, commit_id)).status == "committed"
    assert await _count(db_session, NovelBibleFinding, novel.id) == 0


async def test_a_blocking_finding_with_unverifiable_evidence_becomes_a_warning(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    later, later_revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)
    # 1화 사실의 근거 해시가 원고와 맞지 않게 된다 — 차단 후보의 항목 하나라도 근거를 다시 맞출 수 없으면 막지 않는다.
    await db_session.execute(
        update(NovelBibleEvidence).where(NovelBibleEvidence.novel_id == novel.id).values(quote_sha256="0" * 64)
    )
    every_fact = FakeRule(pick=lambda snap: tuple(f.id for f in snap.facts or ()))

    commit_id = await _confirm(db_session, registry, novel.id, later.id, later_revision.id)
    await drain(factory, registry, adapter, [every_fact])

    assert (await _commit_row(db_session, commit_id)).status == "committed"
    finding = (await db_session.scalars(select(NovelBibleFinding).where(NovelBibleFinding.commit_id == commit_id))).one()
    assert (finding.severity, finding.rule, finding.payload["rule"]) == (
        "warning", "evidence_unverified", "exit_then_appearance"
    )


async def test_an_exception_while_committing_leaves_the_previous_revision(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    later, later_revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    facts = facts_slot()
    registry, adapter = fake_registry(events_slot(), facts, knowledge_slot()), FakeAdapter()
    factory = savepoint_factory(db_session)
    await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await drain(factory, registry, adapter)
    head_before = await _head(db_session, novel.id)

    async def explode() -> None:
        raise RuntimeError("커밋 도중 실패")

    facts.before_apply = explode
    commit_id = await _confirm(db_session, registry, novel.id, later.id, later_revision.id)
    await drain(factory, registry, adapter)

    row = await _commit_row(db_session, commit_id)
    assert (row.status, row.failure_code) == ("failed", "internal")
    assert await _head(db_session, novel.id) == head_before
    assert await _count(db_session, NovelBibleEvent, novel.id) == 1
    assert await _count(db_session, NovelBibleRevision, novel.id) == 1


async def test_a_revision_number_reused_after_a_batch_delete_does_not_fool_the_head_comparison(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapters = [
        await add_chapter(db_session, novel.id, ordinal, body)
        for ordinal, body in enumerate([BODY, SECOND_BODY, BODY, SECOND_BODY], start=1)
    ]
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    for chapter, revision in chapters[:2]:
        await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
        await drain(factory, registry, adapter)
    third, third_revision = chapters[2]
    waiting_id = await _confirm(db_session, registry, novel.id, third.id, third_revision.id)
    await _run_jobs(factory, registry, adapter)
    async with factory() as session:
        assert await start_linking(session, waiting_id) == "linking"
        await session.commit()
    second_head = await _head(db_session, novel.id)
    assert second_head.revision_no == 2

    # 2화 묶음을 지우면 2번 리비전이 이력째 사라지고, 다른 화가 같은 번호 2 를 새로 얻는다.
    second_batch = chapters[1][0].batch_id
    assert second_batch is not None
    await delete_batch(db_session, novel_id=novel.id, batch_id=second_batch, freed_storage_keys=[])
    fourth, fourth_revision = chapters[3]
    await _confirm(db_session, registry, novel.id, fourth.id, fourth_revision.id)
    await drain(factory, registry, adapter)
    reused = await _head(db_session, novel.id)
    assert reused.revision_no == 2 and reused.id != second_head.id

    await link_check_commit(factory, registry, [], waiting_id)

    row = await _commit_row(db_session, waiting_id)
    assert (row.status, row.cas_losses) == ("committed", 1)
    head = await _head(db_session, novel.id)
    assert (head.revision_no, head.parent_revision_id) == (3, reused.id)
    # 멱등 판정도 번호가 아니라 그 화의 확정 이력으로 본다 — 1화의 현재 확정 개정은 그대로다.
    first, first_revision = chapters[0]
    again = await confirm(
        db_session, registry, novel_id=novel.id, chapter_id=first.id, revision_id=first_revision.id, actor=SYSTEM
    )
    assert again.created is False


async def test_cleaning_a_hidden_novel_during_linking_leaves_no_late_bible_rows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    # 공개된 화라 숨긴 소설 정리 뒤에도 화 행이 남는다 — 화가 남아도 늦은 쓰기를 막는지 본다.
    await publish(db_session, novel.id)
    db_session.add(NovelChapterPublication(chapter_id=chapter.id, novel_id=novel.id, ordinal=1, revision_id=revision.id))
    await db_session.flush()
    registry, adapter = full_registry(), FakeAdapter()
    factory = savepoint_factory(db_session)
    commit_id = await _confirm(db_session, registry, novel.id, chapter.id, revision.id)
    await _run_jobs(factory, registry, adapter)
    async with factory() as session:
        assert await start_linking(session, commit_id) == "linking"
        await session.commit()
    load = pipeline._load

    async def load_then_hide(*args: Any) -> Any:
        # 연결이 확정을 읽은 바로 뒤에 작가가 팔린 소설을 지워 숨긴 소설 정리가 커밋된다.
        loaded = await load(*args)
        await strip_author_only_data(db_session, [novel.id], freed_storage_keys=[])
        await db_session.execute(update(Novel).where(Novel.id == novel.id).values(hidden_at=func.now()))
        return loaded

    monkeypatch.setattr(pipeline, "_load", load_then_hide)
    await link_check_commit(factory, registry, [], commit_id)

    for model in (NovelBibleCommit, NovelBibleRevision, NovelBibleEntity, NovelBibleEvent, NovelBibleEvidence):
        assert await _count(db_session, model, novel.id) == 0


@pytest_asyncio.fixture
async def committed_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine, None]:
    engine = _committed_engine(db_engine)
    try:
        yield engine
    finally:
        await delete_committed_novels(engine)
        await engine.dispose()


async def _committed_novel(factory: SessionFactory, bodies: list[str]) -> tuple[uuid.UUID, list[Any]]:
    async with factory() as setup:
        novel = await make_novel(setup, email_domain=COMMITTED_DOMAIN)
        chapters = []
        for ordinal, body in enumerate(bodies, start=1):
            chapter, revision = await add_chapter(setup, novel.id, ordinal, body)
            chapters.append((chapter.batch_id, chapter.id, revision.id))
        await setup.commit()
    return novel.id, chapters


class _Gate:
    """첫 번째 `pause()` 만 멈춘다 — 커밋 트랜잭션 하나를 리비전을 넣은 뒤 항목을 쓰기 직전에 세워 둔다."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def pause(self) -> None:
        if self.entered.is_set():
            return
        self.entered.set()
        await self.release.wait()


async def test_only_one_link_start_wins(committed_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    novel_id, chapters = await _committed_novel(factory, [BODY])
    async with factory() as session:
        commit_id = await _confirm(session, fake_registry(), novel_id, chapters[0][1], chapters[0][2])
        await session.commit()

    async with factory() as first, factory() as second:
        winner = await start_linking(first, commit_id)
        loser_task = asyncio.create_task(start_linking(second, commit_id))
        await _wait_until_a_lock_is_awaited(committed_engine)
        await first.commit()
        loser = await loser_task
        await second.commit()

    assert (winner, loser) == ("linking", None)


async def test_a_commit_that_loses_the_race_relinks_without_reextracting(committed_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    novel_id, chapters = await _committed_novel(factory, [BODY, SECOND_BODY])
    gate = _Gate()
    facts = facts_slot()
    facts.before_apply = gate.pause
    registry, adapter = fake_registry(events_slot(), facts, knowledge_slot()), FakeAdapter()
    commit_ids = []
    for _, chapter_id, revision_id in chapters:
        async with factory() as session:
            commit_ids.append(await _confirm(session, registry, novel_id, chapter_id, revision_id))
            await session.commit()
    await _run_jobs(factory, registry, adapter)
    for commit_id in commit_ids:
        async with factory() as session:
            assert await start_linking(session, commit_id) == "linking"
            await session.commit()
    calls = len(adapter.calls)

    first_task = asyncio.create_task(link_check_commit(factory, registry, [], commit_ids[0]))
    await gate.entered.wait()
    second_task = asyncio.create_task(link_check_commit(factory, registry, [], commit_ids[1]))
    # 뒤 커밋은 같은 머리(없음) 위에서 1번 리비전을 넣으려다 앞 커밋의 아직 커밋되지 않은 1번을 기다린다.
    await _wait_until_a_lock_is_awaited(committed_engine)
    gate.release.set()
    await first_task
    await second_task

    async with factory() as check:
        first_row = await _commit_row(check, commit_ids[0])
        second_row = await _commit_row(check, commit_ids[1])
        revisions = (
            await check.execute(
                select(NovelBibleRevision.commit_id, NovelBibleRevision.revision_no).where(
                    NovelBibleRevision.novel_id == novel_id
                )
            )
        ).tuples().all()
    assert (first_row.status, first_row.cas_losses) == ("committed", 0)
    assert (second_row.status, second_row.cas_losses) == ("committed", 1)
    assert dict(revisions) == {commit_ids[0]: 1, commit_ids[1]: 2}
    assert len(adapter.calls) == calls


async def test_deleting_a_batch_while_committing_waits_and_removes_the_new_rows(committed_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    novel_id, chapters = await _committed_novel(factory, [BODY])
    batch_id, chapter_id, revision_id = chapters[0]
    gate = _Gate()
    facts = facts_slot()
    facts.before_apply = gate.pause
    registry, adapter = fake_registry(events_slot(), facts, knowledge_slot()), FakeAdapter()
    async with factory() as session:
        commit_id = await _confirm(session, registry, novel_id, chapter_id, revision_id)
        await session.commit()
    await _run_jobs(factory, registry, adapter)
    async with factory() as session:
        assert await start_linking(session, commit_id) == "linking"
        await session.commit()

    async def delete_the_batch() -> None:
        async with factory() as session:
            await delete_batch(session, novel_id=novel_id, batch_id=batch_id, freed_storage_keys=[])
            await session.commit()

    commit_task = asyncio.create_task(link_check_commit(factory, registry, [], commit_id))
    await gate.entered.wait()
    delete_task = asyncio.create_task(delete_the_batch())
    # 삭제는 커밋이 쥔 화 행 잠금을 기다린다(커밋이 확정 행보다 화 행을 먼저 잡아 두 쪽 순서가 같다 — 교착이 없다).
    await _wait_until_a_lock_is_awaited(committed_engine)
    gate.release.set()
    await commit_task
    await delete_task

    async with factory() as check:
        for model in (NovelBibleCommit, NovelBibleRevision, NovelBibleEvent, NovelBibleFact, NovelBibleEvidence):
            assert await _count(check, model, novel_id) == 0
