"""시간 세 축의 질의 넷 — 리비전 시점의 정본(편집 확정 시간), 사건 시점에 참인 사실과 인물이 아는 것(이야기 시간), 독자에게
드러난 사실(독자 공개 시간, 저장하지 않고 공개본·판에서 파생).

행은 확정 흐름을 거치지 않고 표에 직접 심는다 — 질의가 어떤 행을 고르는지만 본다. 슬롯은 가짜이고, 가짜 슬롯의 읽기는 코어의
리비전 시점 조회를 그대로 쓴다."""

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    NovelChapter,
    NovelChapterEdition,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelPublication,
)
from api.db.models.novel_bible import NovelBibleEntity, NovelBibleEvidence, NovelBibleExpiration, NovelBibleRevision
from api.db.models.novel_bible_events import NovelBibleEvent, NovelBibleEventRelation
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.novel_bible.core.queries import bible_at, facts_true_at, knowledge_at, revealed_facts
from api.novel_bible.core.types import FactRow
from api.novel_bible.ids import EventActuality, FactKind, FactScope, ItemStatus
from api.novelize.deletion import delete_batch
from api.novelize.text import split_paragraphs
from novel_bible_fakes import (
    add_chapter,
    add_revision,
    events_slot,
    facts_slot,
    fake_registry,
    full_registry,
    knowledge_slot,
    make_novel,
    plant_revision,
    publish,
)


async def _entity(db: AsyncSession, novel_id: uuid.UUID, name: str, kind: str = "character") -> uuid.UUID:
    entity = NovelBibleEntity(novel_id=novel_id, kind=kind, name=name, name_norm=name)
    db.add(entity)
    await db.flush()
    return entity.id


async def _event(
    db: AsyncSession, revision: NovelBibleRevision, chapter: NovelChapter, block: uuid.UUID, *, ordinal: int = 1,
    actuality: EventActuality = "present",
) -> NovelBibleEvent:
    event = NovelBibleEvent(
        novel_id=revision.novel_id, created_revision_id=revision.id, chapter_id=chapter.id, ordinal=ordinal,
        actuality=actuality, summary="합성 사건", anchor_block_ids=[block],
    )
    db.add(event)
    await db.flush()
    return event


async def _fact(
    db: AsyncSession, revision: NovelBibleRevision, chapter_id: uuid.UUID, *, key: uuid.UUID, subject: uuid.UUID,
    kind: FactKind = "life", value: str = "alive", holds: bool = True, scope: FactScope = "from_here",
    valid_from: uuid.UUID | None = None, value_entity: uuid.UUID | None = None, status: ItemStatus = "confirmed",
) -> NovelBibleFact:
    fact = NovelBibleFact(
        novel_id=revision.novel_id, created_revision_id=revision.id, chapter_id=chapter_id, status=status,
        fact_key=key, subject_entity_id=subject, kind=kind, predicate_norm=kind, value=value, value_norm=value,
        value_entity_id=value_entity, holds=holds, immutable=False, onset=False, scope=scope,
        valid_from_event_id=valid_from,
    )
    db.add(fact)
    await db.flush()
    return fact


async def _expire(db: AsyncSession, revision: NovelBibleRevision, table: str, item_id: uuid.UUID) -> None:
    db.add(
        NovelBibleExpiration(
            revision_id=revision.id, novel_id=revision.novel_id, item_table=table, item_id=item_id,
            reason="chapter_replaced",
        )
    )
    await db.flush()


async def test_bible_at_reads_each_revision_as_it_was(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, "1화")
    second, second_revision = await add_chapter(db_session, novel.id, 2, "2화")
    subject, registry = await _entity(db_session, novel.id, "하나"), fake_registry(facts_slot())
    r1 = await plant_revision(db_session, novel.id, first.id, first_revision.id)
    old = await _fact(db_session, r1, first.id, key=uuid.uuid4(), subject=subject)
    r2 = await plant_revision(db_session, novel.id, second.id, second_revision.id)
    other = await _fact(db_session, r2, second.id, key=uuid.uuid4(), subject=subject)
    await _fact(db_session, r2, second.id, key=uuid.uuid4(), subject=subject, status="proposed")
    r3 = await plant_revision(db_session, novel.id, first.id, first_revision.id)
    await _expire(db_session, r3, "fact", old.id)
    new = await _fact(db_session, r3, first.id, key=old.fact_key, subject=subject)

    async def fact_ids(revision_no: int | None) -> set[uuid.UUID]:
        snapshot = await bible_at(db_session, novel.id, registry, revision_no=revision_no)
        assert snapshot.facts is not None and snapshot.events is None and snapshot.knowledge is None
        return {fact.id for fact in snapshot.facts}

    assert await fact_ids(1) == {old.id}
    assert await fact_ids(2) == {old.id, other.id}
    assert await fact_ids(3) == await fact_ids(None) == {other.id, new.id}

    # 2화 묶음을 지우면 2번 리비전과 그 항목이 이력째 사라지고, 3번 시점은 2화 항목 없이 계산된다.
    assert second.batch_id is not None
    await delete_batch(db_session, novel_id=novel.id, batch_id=second.batch_id, freed_storage_keys=[])
    assert await fact_ids(3) == {new.id}


@dataclass
class _Story:
    novel_id: uuid.UUID
    chapters: list[NovelChapter]
    chapter_revisions: list[NovelChapterRevision]
    revisions: list[NovelBibleRevision]
    main: list[NovelBibleEvent]
    flashback_before_second: NovelBibleEvent
    loose_flashback: NovelBibleEvent
    life: uuid.UUID
    sword: uuid.UUID
    shield: uuid.UUID
    death: NovelBibleFact
    hana: uuid.UUID
    dul: uuid.UUID


async def _story(db: AsyncSession) -> _Story:
    """1~5화. 화마다 주선 사건 하나. 하나는 처음부터 살아 있고(작품 범위) 3화에서 죽는다. 셋은 2화에 검을 얻고 4화에 잃는다.
    4화의 꿈 속에서 셋이 방패를 얻는다. 5화에는 2화 사건 앞의 회상 하나와 관계 없는 회상 하나가 있다."""
    novel = await make_novel(db)
    chapters, chapter_revisions, revisions, main = [], [], [], []
    for ordinal in range(1, 6):
        chapter, revision = await add_chapter(db, novel.id, ordinal, f"{ordinal}화 첫 문단\n\n{ordinal}화 둘째 문단")
        bible_revision = await plant_revision(db, novel.id, chapter.id, revision.id)
        chapters.append(chapter)
        chapter_revisions.append(revision)
        revisions.append(bible_revision)
        main.append(await _event(db, bible_revision, chapter, revision.block_ids[0]))
    fifth_blocks = [uuid.uuid4(), uuid.uuid4()]
    before_second = await _event(db, revisions[4], chapters[4], fifth_blocks[0], ordinal=2, actuality="flashback")
    loose = await _event(db, revisions[4], chapters[4], fifth_blocks[1], ordinal=3, actuality="flashback")
    db.add(
        NovelBibleEventRelation(
            novel_id=novel.id, created_revision_id=revisions[4].id, chapter_id=chapters[4].id,
            from_event_id=before_second.id, relation="before", to_anchor_block_id=main[1].anchor_block_ids[0],
            to_chapter_id=chapters[1].id,
        )
    )
    dream = await _event(db, revisions[3], chapters[3], uuid.uuid4(), ordinal=2, actuality="dream_or_imagined")
    hana, set_, dul = [await _entity(db, novel.id, name) for name in ("하나", "셋", "둘")]
    sword_item, shield_item = await _entity(db, novel.id, "검", "object"), await _entity(db, novel.id, "방패", "object")
    life, sword, shield = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _fact(db, revisions[0], chapters[0].id, key=life, subject=hana, scope="work")
    death = await _fact(db, revisions[2], chapters[2].id, key=life, subject=hana, value="dead", valid_from=main[2].id)
    for index, holds in [(1, True), (3, False)]:
        await _fact(db, revisions[index], chapters[index].id, key=sword, subject=set_, kind="possession", value="검",
                    holds=holds, valid_from=main[index].id, value_entity=sword_item)
    await _fact(db, revisions[3], chapters[3].id, key=shield, subject=set_, kind="possession", value="방패",
                valid_from=dream.id, value_entity=shield_item)
    return _Story(
        novel.id, chapters, chapter_revisions, revisions, main, before_second, loose, life, sword, shield, death, hana,
        dul,
    )


async def test_facts_true_at_follow_story_order(db_session: AsyncSession) -> None:
    story = await _story(db_session)
    registry = full_registry()

    async def at(event: NovelBibleEvent) -> tuple[dict[uuid.UUID, FactRow], set[uuid.UUID]]:
        result = await facts_true_at(db_session, story.novel_id, registry, event_id=event.id)
        return dict(result.states), {row.fact_key for row in result.undetermined}

    states, _ = await at(story.main[4])
    assert states[story.life].value_norm == "dead"
    assert states[story.sword].holds is False
    # 꿈 속에서 얻은 방패는 상태가 아니다 — 참도 미정도 아니다.
    assert story.shield not in states
    states, _ = await at(story.main[2])
    assert states[story.sword].holds is True
    states, _ = await at(story.flashback_before_second)
    assert states[story.life].value_norm == "alive"
    states, undetermined = await at(story.loose_flashback)
    assert story.life not in states and story.life in undetermined


async def test_knowledge_at_resolves_through_the_current_fact_of_its_key(db_session: AsyncSession) -> None:
    story = await _story(db_session)
    knows = NovelBibleKnowledge(
        novel_id=story.novel_id, created_revision_id=story.revisions[4].id, chapter_id=story.chapters[4].id,
        knower_entity_id=story.dul, kind="knows", fact_key=story.life, proposition={"value": "dead"},
        known_since_event_id=story.main[4].id,
    )
    believes = NovelBibleKnowledge(
        novel_id=story.novel_id, created_revision_id=story.revisions[4].id, chapter_id=story.chapters[4].id,
        knower_entity_id=story.dul, kind="believes", fact_key=story.life, proposition={"value": "alive"},
        known_since_event_id=story.main[4].id,
    )
    db_session.add_all([knows, believes])
    await db_session.flush()
    # 3화를 다시 확정해 사건과 사망 사실이 새 행이 된다 — 5화 지식은 행을 고치지 않아도 같은 키의 새 사실로 풀린다.
    revision = await plant_revision(db_session, story.novel_id, story.chapters[2].id, story.chapter_revisions[2].id)
    await _expire(db_session, revision, "event", story.main[2].id)
    await _expire(db_session, revision, "fact", story.death.id)
    third_event = await _event(db_session, revision, story.chapters[2], story.main[2].anchor_block_ids[0])
    new_death = await _fact(
        db_session, revision, story.chapters[2].id, key=story.life, subject=story.hana, value="dead",
        valid_from=third_event.id,
    )

    result = await knowledge_at(
        db_session, story.novel_id, full_registry(), knower_entity_id=story.dul, event_id=story.main[4].id
    )
    assert [(row.id, fact.id if fact else None) for row, fact in result.knows] == [(knows.id, new_death.id)]
    assert [row.id for row in result.believes] == [believes.id]

    without_facts = await knowledge_at(
        db_session, story.novel_id, fake_registry(events_slot(), knowledge_slot()), knower_entity_id=story.dul,
        event_id=story.main[4].id,
    )
    assert [(row.id, fact) for row, fact in without_facts.knows] == [(knows.id, None)]


def _quote(revision: NovelChapterRevision, block: int) -> tuple[uuid.UUID, int, int, str]:
    text = split_paragraphs(revision.body)[block]
    return revision.block_ids[block], 0, len(text), hashlib.sha256(text.encode("utf-8")).hexdigest()


async def test_revealed_facts_follow_what_readers_were_shown(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    shown, confirmed = await add_chapter(db_session, novel.id, 1, "첫 문단\n\n하나는 살아 있다")
    hidden, hidden_revision = await add_chapter(db_session, novel.id, 2, "첫 문단\n\n둘은 떠났다")
    subject, registry = await _entity(db_session, novel.id, "하나"), fake_registry(facts_slot())
    facts = {}
    for chapter, revision in [(shown, confirmed), (hidden, hidden_revision)]:
        bible_revision = await plant_revision(db_session, novel.id, chapter.id, revision.id)
        fact = await _fact(db_session, bible_revision, chapter.id, key=uuid.uuid4(), subject=subject)
        block_id, start, end, digest = _quote(revision, 1)
        db_session.add(
            NovelBibleEvidence(
                novel_id=novel.id, created_revision_id=bible_revision.id, item_table="fact", item_id=fact.id,
                origin="manuscript_block", chapter_id=chapter.id, chapter_revision_id=revision.id, block_id=block_id,
                char_start=start, char_end=end, quote_sha256=digest,
            )
        )
        facts[chapter.id] = fact.id
    await db_session.flush()

    async def revealed(editions: dict[uuid.UUID, int] | None = None) -> set[uuid.UUID]:
        return {row.id for row in await revealed_facts(db_session, novel.id, registry, editions=editions)}

    assert await revealed() == set()
    await publish(db_session, novel.id, review_status="pending")
    db_session.add(NovelChapterPublication(chapter_id=shown.id, novel_id=novel.id, ordinal=1, revision_id=confirmed.id))
    await db_session.flush()
    assert await revealed() == set()

    await db_session.execute(
        update(NovelPublication).where(NovelPublication.novel_id == novel.id).values(
            visibility="public", review_status="approved"
        )
    )
    assert await revealed() == {facts[shown.id]}

    # 공개 개정이 확정 개정과 달라도 인용 구절이 그 블록에 그대로 있으면 드러난 것이다.
    same_quote = await add_revision(db_session, shown.id, "바뀐 첫 문단\n\n하나는 살아 있다", block_ids=confirmed.block_ids)
    await _show(db_session, shown.id, same_quote.id)
    assert await revealed() == {facts[shown.id]}
    changed = await add_revision(db_session, shown.id, "첫 문단\n\n하나는 이미 없다", block_ids=confirmed.block_ids)
    await _show(db_session, shown.id, changed.id)
    assert await revealed() == set()

    # 지정한 판(옛 판)을 기준으로 하면 그 판의 글로 판정한다.
    db_session.add(NovelChapterEdition(chapter_id=shown.id, edition=1, novel_id=novel.id, revision_id=confirmed.id))
    await db_session.flush()
    assert await revealed({shown.id: 1}) == {facts[shown.id]}


async def _show(db: AsyncSession, chapter_id: uuid.UUID, revision_id: uuid.UUID) -> None:
    await db.execute(
        update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter_id)
        .values(revision_id=revision_id)
    )
