"""정본 기억 측정 하네스의 심기 — 명세 한 권을 격리 DB 에 심으면, 확정 때 코어가 읽는 길 그대로 사건·사실 슬롯의 입력에 원작
설정·노트, 그 화까지 보이는 플레이(채팅 기억) 사실, 장면 구성안의 장면 제목·회상 표시가 실린다.

심은 행이 앱이 읽는 사슬에서 하나라도 빠지면 오류 없이 빈 입력으로 확정된다(원작 버전을 못 찾으면 원작 없이, 방이 없으면 플레이
없이, 장면 행이 없으면 화 전체 한 장면). 그래서 입력에 실제로 실렸는지를 본다. 픽스처는 합성 문장이다."""

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import NovelBibleCommit
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.jobs import commit_ref
from api.novel_bible.core.views import CommitView, source_ref_of
from api.novel_bible.registry import REGISTRY
from api.novel_bible.slots.events.slot import EventsInput, EventsSlot
from api.novel_bible.slots.facts.slot import FactsInput, FactsSlot
from novel_bible_eval.seed import SeededChapter, add_chapter, seed_novel
from novel_bible_eval.spec import load_set

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "small_set.json"
SYSTEM = Actor(kind="system")


async def _view(db: AsyncSession, novel_id: uuid.UUID, chapter: SeededChapter) -> CommitView:
    """화 하나를 코어 확정 입구로 확정하고, 작업이 입력을 만들 때와 같은 읽기 뷰를 그 확정 행에서 세운다."""
    result = await confirm(
        db, REGISTRY, novel_id=novel_id, chapter_id=chapter.chapter_id, revision_id=chapter.revision_id,
        actor=SYSTEM,
    )
    commit = await db.get(NovelBibleCommit, result.commit_id)
    assert commit is not None
    return CommitView(db, REGISTRY, await commit_ref(db, commit), source_ref_of(commit), commit.chat_room_id)


async def _facts_input(db: AsyncSession, novel_id: uuid.UUID, chapter: SeededChapter) -> FactsInput:
    slot_input = await FactsSlot().build_input(db, await _view(db, novel_id, chapter))
    assert isinstance(slot_input, FactsInput)
    return slot_input


async def _events_input(db: AsyncSession, novel_id: uuid.UUID, chapter: SeededChapter) -> EventsInput:
    slot_input = await EventsSlot().build_input(db, await _view(db, novel_id, chapter))
    assert isinstance(slot_input, EventsInput)
    return slot_input


async def test_the_facts_input_reads_the_seeded_source_setting_and_notes(db_session: AsyncSession) -> None:
    (spec,) = load_set(FIXTURE).novels
    assert spec.source is not None
    seeded = await seed_novel(db_session, spec)
    slot_input = await _facts_input(db_session, seeded.novel_id, seeded.chapters[0])
    assert slot_input.source is not None
    # 스토리 원작의 작품 설정은 세계관 설정 글이고, 노트는 작품 버전 단위 노트를 심은 차례대로 읽는다.
    assert slot_input.source.work_setting == spec.source.setting
    assert list(slot_input.source.keyword_notes.values()) == spec.source.notes


async def test_without_play_rows_the_source_is_the_works_current_published_version(db_session: AsyncSession) -> None:
    # 플레이가 없는 명세는 방 없이 심는다 — 원작 정본 슬롯은 방이 고정한 버전이 없으니 소설의 원작 칸이 가리키는 작품의 지금
    # 발행본을 읽는다.
    (spec,) = load_set(FIXTURE).novels
    assert spec.source is not None
    chapters = [chapter.model_copy(update={"facts": []}) for chapter in spec.chapters]  # 플레이 차이 정답을 뗀다
    seeded = await seed_novel(db_session, spec.model_copy(update={"play": [], "chapters": chapters}))
    slot_input = await _facts_input(db_session, seeded.novel_id, seeded.chapters[0])
    assert slot_input.play is None
    assert slot_input.source is not None and slot_input.source.work_setting == spec.source.setting


async def test_a_play_row_reaches_the_facts_input_from_the_chapter_it_is_visible_from(db_session: AsyncSession) -> None:
    # 채팅 기억 행은 2화부터 보인다 — 그 스냅숏은 2화 구간 안에서 접혔다. 1화 끝까지 접힌 행은 없고, 2화·3화 끝까지는 그 행이다.
    (spec,) = load_set(FIXTURE).novels
    (row,) = spec.play
    seeded = await seed_novel(db_session, spec)
    seen = []
    for chapter in seeded.chapters:
        play = (await _facts_input(db_session, seeded.novel_id, chapter)).play
        seen.append(None if play is None else [(fact.subject, fact.attribute, fact.value) for fact in play])
    assert seen == [None, [(row.subject, row.attribute, row.value)], [(row.subject, row.attribute, row.value)]]


async def test_the_events_input_reads_the_seeded_scene_titles_and_flashback_marks(db_session: AsyncSession) -> None:
    (spec,) = load_set(FIXTURE).novels
    seeded = await seed_novel(db_session, spec)
    without = await _events_input(db_session, seeded.novel_id, seeded.chapters[0])
    assert without.scenes == []  # 구성안이 없는 화는 화 전체가 장면 하나라 힌트가 없다
    scened = await _events_input(db_session, seeded.novel_id, seeded.chapters[2])
    planned = spec.chapters[2].scenes
    assert planned is not None
    assert [(scene.title, scene.flashback) for scene in scened.scenes] == [
        (scene.title, scene.flashback) for scene in planned
    ]
    # 장면마다 그 장면 첫 문단부터 다음 장면 앞 문단까지의 블록이다.
    blocks = seeded.chapters[2].block_ids
    assert [scene.block_ids for scene in scened.scenes] == [(blocks[0],), (blocks[1],), blocks[2:]]


async def test_a_probe_chapter_carries_its_scene_outline_too(db_session: AsyncSession) -> None:
    (spec,) = load_set(FIXTURE).novels
    probe = next(probe for probe in spec.probes if probe.chapter.scenes is not None)
    seeded = await seed_novel(db_session, spec)
    attached = await add_chapter(db_session, seeded.novel_id, len(spec.chapters) + 1, probe.chapter)
    slot_input = await _events_input(db_session, seeded.novel_id, attached)
    assert probe.chapter.scenes is not None
    assert [(scene.title, scene.flashback) for scene in slot_input.scenes] == [
        (scene.title, scene.flashback) for scene in probe.chapter.scenes
    ]
