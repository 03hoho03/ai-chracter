"""원작 정본 슬롯 — 소설이 기대는 원작의 작품 설정과 키워드북 노트를 읽기만 한다.

버전은 소설 생성과 같은 규칙으로 고른다(방이 고정한 버전, 방이 없으면 원작의 지금 발행본). 확정 행에는 버전 id 와 입력 해시가
함께 남고, 작업 때는 확정 행의 버전으로 같은 글을 다시 만든다. 키워드북은 작품 버전 단위 노트만 읽는다 — 소설에는 시작설정
칸이 없어 방이 지워지면 어느 시작설정의 노트인지 정할 근거가 없다."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    CharacterVersionDetail,
    ChatRoom,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    KeywordNote,
    ModerationStatus,
    Novel,
    NovelBibleCommit,
    NovelBibleJob,
    StartingSetup,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.session import engine
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.jobs import commit_ref
from api.novel_bible.core.views import CommitView, source_ref_of
from api.novel_bible.registry import REGISTRY
from api.novel_bible.slots.source.slot import SourceCanonSlot
from api.novelize.inputs import _version_id, load_work_setting
from novel_bible_fakes import add_chapter, make_novel

BODY = "합성 문단 하나\n\n합성 문단 둘"
SYSTEM = Actor(kind="system")
_SLOT_LOGGER = "api.novel_bible.slots.source.slot"


@dataclass(frozen=True)
class Work:
    novel: Novel
    content: Content
    pinned: uuid.UUID  # 방이 고정한 버전
    published: uuid.UUID  # 원작의 지금 발행본 — 방이 고정한 버전보다 새것


async def _version(db: AsyncSession, content: Content, number: int, prompt: str) -> uuid.UUID:
    version = ContentVersion(
        content_id=content.id, version_number=number, published_at=datetime.now(UTC), detail_description="설명"
    )
    db.add(version)
    await db.flush()
    db.add(
        CharacterVersionDetail(
            content_version_id=version.id, name="인물", one_liner="한줄", intro="인트로", example_dialogues=[],
            character_prompt=prompt,
        )
    )
    await db.flush()
    return version.id


async def _make_work(db: AsyncSession) -> Work:
    """캐릭터 원작 하나(버전 둘)와, 옛 버전을 고정한 방에서 만든 소설. 작가 글의 `{{user}}` 는 소설 주인공 이름으로 바뀐다."""
    novel = await make_novel(db)
    content = Content(
        creator_user_id=novel.user_id, type=ContentType.CHARACTER, hashtags=[], visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    pinned = await _version(db, content, 1, "{{user}}와 오래 알고 지낸 고정본 합성 인물")
    published = await _version(db, content, 2, "{{user}}와 처음 만난 발행본 합성 인물")
    content.current_published_version_id = published
    room = ChatRoom(user_id=novel.user_id, content_id=content.id, content_version_id=pinned)
    db.add(room)
    await db.flush()
    novel.content_id, novel.chat_room_id, novel.protagonist_name = content.id, room.id, "주인공"
    await db.flush()
    return Work(novel=novel, content=content, pinned=pinned, published=published)


async def _make_story_work(db: AsyncSession, setting: str, *, protagonist: str | None) -> tuple[Novel, uuid.UUID]:
    """스토리 원작 하나(발행본 하나)와, 방 없이 남은 그 원작의 소설 — 원작 버전은 지금 발행본이다. 운영에서 키워드북 노트를
    싣는 원작은 스토리뿐이라 이름 치환은 이 원작으로 본다. 스토리 소설은 캐릭터 이름이 없어 `{{char}}` 가 글자 그대로 남는다."""
    novel = await make_novel(db)
    content = Content(
        creator_user_id=novel.user_id, type=ContentType.STORY, hashtags=[], visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db.add(version)
    await db.flush()
    db.add(
        StoryVersionDetail(
            content_version_id=version.id, name="스토리", one_liner="한줄", prompt_template=StoryPromptTemplate.BASIC,
            setting_text=setting,
        )
    )
    content.current_published_version_id = version.id
    novel.content_id, novel.content_type, novel.character_name = content.id, "story", None
    novel.protagonist_name = protagonist
    await db.flush()
    return novel, version.id


async def _note(
    db: AsyncSession, version_id: uuid.UUID, text: str, *, order: int = 0, setup_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
) -> KeywordNote:
    note = KeywordNote(
        entity_id=entity_id or uuid.uuid4(), content_version_id=version_id, starting_setup_id=setup_id,
        info_text=text, trigger_keywords=["합성"], order=order,
    )
    db.add(note)
    await db.flush()
    return note


async def _setup(db: AsyncSession, version_id: uuid.UUID) -> StartingSetup:
    setup = StartingSetup(
        entity_id=uuid.uuid4(), content_version_id=version_id, name="첫 만남", prologue="프롤로그", order=1
    )
    db.add(setup)
    await db.flush()
    return setup


async def _confirm(db: AsyncSession, novel_id: uuid.UUID) -> NovelBibleCommit:
    chapter, revision = await add_chapter(db, novel_id, 1, BODY)
    result = await confirm(
        db, REGISTRY, novel_id=novel_id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )
    commit = await db.get(NovelBibleCommit, result.commit_id)
    assert commit is not None
    return commit


# ── 버전 ──────────────────────────────────────────────────────────────────


async def test_the_version_is_the_one_the_room_pinned(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)

    ref = await SourceCanonSlot().resolve(db_session, work.novel.id)

    assert ref is not None
    assert ref.content_version_id == work.pinned
    assert ref.content_version_id == await _version_id(db_session, work.novel)


async def test_without_a_room_the_version_is_the_current_published_one(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    work.novel.chat_room_id = None
    await db_session.flush()

    ref = await SourceCanonSlot().resolve(db_session, work.novel.id)

    assert ref is not None
    assert ref.content_version_id == work.published
    assert ref.content_version_id == await _version_id(db_session, work.novel)


async def test_without_a_published_work_there_is_no_source(db_session: AsyncSession) -> None:
    unpublished = await _make_work(db_session)
    unpublished.novel.chat_room_id = None
    unpublished.content.current_published_version_id = None
    gone = await make_novel(db_session)  # 원작 행이 없는 소설(방도 없다)
    await db_session.flush()

    assert await SourceCanonSlot().resolve(db_session, unpublished.novel.id) is None
    assert await SourceCanonSlot().resolve(db_session, gone.id) is None


# ── 읽는 글 ───────────────────────────────────────────────────────────────


async def test_the_work_setting_is_the_text_novel_generation_reads(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    slot = SourceCanonSlot()
    ref = await slot.resolve(db_session, work.novel.id)
    assert ref is not None

    canon = await slot.load(db_session, work.novel.id, ref)

    assert canon.work_setting == await load_work_setting(db_session, work.novel, work.pinned)
    assert "주인공과 오래 알고 지낸 고정본" in canon.work_setting


async def test_only_version_wide_notes_with_text_are_read_in_note_order(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    setup = await _setup(db_session, work.pinned)
    later = await _note(db_session, work.pinned, "합성 노트 셋", order=2)
    tie_b = await _note(db_session, work.pinned, "합성 노트 둘", order=1, entity_id=uuid.UUID(int=2))
    tie_a = await _note(db_session, work.pinned, "합성 노트 하나", order=1, entity_id=uuid.UUID(int=1))
    await _note(db_session, work.pinned, "시작설정 합성 노트", setup_id=setup.id)
    await _note(db_session, work.pinned, "  \n ")
    await _note(db_session, work.published, "다른 버전 합성 노트")
    slot = SourceCanonSlot()
    ref = await slot.resolve(db_session, work.novel.id)
    assert ref is not None

    canon = await slot.load(db_session, work.novel.id, ref)

    assert list(canon.keyword_notes.items()) == [
        (tie_a.id, "합성 노트 하나"),
        (tie_b.id, "합성 노트 둘"),
        (later.id, "합성 노트 셋"),
    ]


# 작품 설정과 노트에 같은 문장을 넣고 두 결과를 견준다. 이름 규칙이 두 곳(소설 생성의 작품 설정과 이 슬롯의 노트)에 있어, 생성 쪽만
# 바뀌면 노트가 옛 규칙으로 남는 것을 이 비교가 잡는다.
_NAMED_SENTENCE = "합성 길목에서 {{user}}가 {{char}}와 걷는다"


@pytest.mark.parametrize(
    ("protagonist", "expected"),
    [
        # 조사는 이름 끝 받침에 맞춘다.
        pytest.param("지훈", "합성 길목에서 지훈이 {{char}}와 걷는다", id="named"),
        # 이름이 비면 대체어가 들어간다 — 이름 없는 소설에서도 예외 없이 읽는다.
        pytest.param(None, "합성 길목에서 당신이 {{char}}와 걷는다", id="unnamed"),
        pytest.param("", "합성 길목에서 당신이 {{char}}와 걷는다", id="blank-name"),
    ],
)
async def test_note_names_follow_the_work_setting_rule(
    db_session: AsyncSession, protagonist: str | None, expected: str
) -> None:
    novel, version_id = await _make_story_work(db_session, _NAMED_SENTENCE, protagonist=protagonist)
    note = await _note(db_session, version_id, _NAMED_SENTENCE)
    slot = SourceCanonSlot()
    ref = await slot.resolve(db_session, novel.id)
    assert ref is not None

    canon = await slot.load(db_session, novel.id, ref)

    assert canon.work_setting == expected
    assert canon.keyword_notes == {note.id: expected}


# ── 확정 행 ───────────────────────────────────────────────────────────────


async def test_confirm_records_the_version_id_and_the_input_hash(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    await _note(db_session, work.pinned, "합성 노트")

    commit = await _confirm(db_session, work.novel.id)

    ref = await SourceCanonSlot().resolve(db_session, work.novel.id)
    assert ref is not None
    assert (commit.source_content_version_id, commit.source_input_hash) == (work.pinned, ref.input_hash)
    source_jobs = select(func.count()).where(NovelBibleJob.commit_id == commit.id, NovelBibleJob.slot == "source")
    assert await db_session.scalar(source_jobs) == 0


async def test_confirm_leaves_the_source_empty_when_the_work_is_gone(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)

    commit = await _confirm(db_session, novel.id)

    assert (commit.source_content_version_id, commit.source_input_hash) == (None, None)


# ── 입력 해시 ─────────────────────────────────────────────────────────────


async def test_the_same_inputs_give_the_same_hash(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    await _note(db_session, work.pinned, "합성 노트")
    slot = SourceCanonSlot()

    first = await slot.resolve(db_session, work.novel.id)
    second = await slot.resolve(db_session, work.novel.id)

    assert first is not None and first == second
    assert (await slot.load(db_session, work.novel.id, first)).ref == first


Change = Callable[[AsyncSession, Work], Awaitable[None]]


async def _edit_work_setting(db: AsyncSession, work: Work) -> None:
    detail = await db.get(CharacterVersionDetail, work.pinned)
    assert detail is not None
    detail.character_prompt = "바뀐 합성 설정"


async def _edit_note(db: AsyncSession, work: Work) -> None:
    note = await db.scalar(select(KeywordNote).where(KeywordNote.content_version_id == work.pinned))
    assert note is not None
    note.info_text = "바뀐 합성 노트"


async def _add_note(db: AsyncSession, work: Work) -> None:
    await _note(db, work.pinned, "새 합성 노트", order=5)


async def _replace_note_with_the_same_text(db: AsyncSession, work: Work) -> None:
    # 근거는 노트 id 로 남으므로, 글이 같아도 다른 노트 행이면 다른 입력이다.
    note = await db.scalar(select(KeywordNote).where(KeywordNote.content_version_id == work.pinned))
    assert note is not None
    await db.delete(note)
    await _note(db, work.pinned, note.info_text, order=note.order, entity_id=note.entity_id)


async def _add_setup_note(db: AsyncSession, work: Work) -> None:
    setup = await _setup(db, work.pinned)
    await _note(db, work.pinned, "시작설정 합성 노트", setup_id=setup.id)


async def _add_blank_note(db: AsyncSession, work: Work) -> None:
    await _note(db, work.pinned, " \n\t")


async def _add_other_version_note(db: AsyncSession, work: Work) -> None:
    await _note(db, work.published, "다른 버전 합성 노트")


async def _hash_before_and_after(db: AsyncSession, work: Work, change: Change) -> tuple[str, str]:
    await _note(db, work.pinned, "원래 합성 노트")
    slot = SourceCanonSlot()
    before = await slot.resolve(db, work.novel.id)
    await change(db, work)
    await db.flush()
    after = await slot.resolve(db, work.novel.id)
    assert before is not None and after is not None
    return before.input_hash, after.input_hash


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_edit_work_setting, id="work-setting"),
        pytest.param(_edit_note, id="note-text"),
        pytest.param(_add_note, id="note-added"),
        pytest.param(_replace_note_with_the_same_text, id="note-replaced"),
    ],
)
async def test_the_hash_changes_with_each_input(db_session: AsyncSession, change: Change) -> None:
    work = await _make_work(db_session)

    before, after = await _hash_before_and_after(db_session, work, change)

    assert before != after


async def test_a_rename_reaches_the_hash_through_a_note_alone(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """작품 설정에는 이름 자리가 없고 노트에만 있다. 확정 때 해시를 낸 뒤(`resolve`) 이름을 바꾸면 노트 글과 해시가 함께
    바뀌고, 다시 읽기는 새 이름의 글로 진행하며 경고를 남긴다 — 이름은 확정 행에 남지 않는다."""
    novel, version_id = await _make_story_work(db_session, "이름 자리 없는 합성 세계관", protagonist="지훈")
    note = await _note(db_session, version_id, "{{user}}가 합성 열쇠를 쥔다")
    slot = SourceCanonSlot()
    ref = await slot.resolve(db_session, novel.id)
    assert ref is not None
    novel.protagonist_name = "민수"
    await db_session.flush()

    with caplog.at_level(logging.WARNING, logger=_SLOT_LOGGER):
        canon = await slot.load(db_session, novel.id, ref)

    assert canon.work_setting == "이름 자리 없는 합성 세계관"
    assert canon.keyword_notes == {note.id: "민수가 합성 열쇠를 쥔다"}
    assert canon.ref.input_hash != ref.input_hash
    assert [record.levelno for record in caplog.records if record.name == _SLOT_LOGGER] == [logging.WARNING]


async def test_the_hash_tells_versions_apart_even_when_their_text_is_the_same(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    pinned = await db_session.get(CharacterVersionDetail, work.pinned)
    published = await db_session.get(CharacterVersionDetail, work.published)
    assert pinned is not None and published is not None
    published.character_prompt = pinned.character_prompt
    await db_session.flush()
    slot = SourceCanonSlot()
    before = await slot.resolve(db_session, work.novel.id)
    work.novel.chat_room_id = None
    await db_session.flush()

    after = await slot.resolve(db_session, work.novel.id)

    assert before is not None and after is not None
    assert (await slot.load(db_session, work.novel.id, before)).work_setting == (
        await slot.load(db_session, work.novel.id, after)
    ).work_setting
    assert before.input_hash != after.input_hash


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_add_setup_note, id="setup-note"),
        pytest.param(_add_blank_note, id="blank-note"),
        pytest.param(_add_other_version_note, id="other-version-note"),
    ],
)
async def test_notes_the_slot_does_not_read_leave_the_hash_alone(db_session: AsyncSession, change: Change) -> None:
    work = await _make_work(db_session)

    before, after = await _hash_before_and_after(db_session, work, change)

    assert before == after


# ── 작업 때 다시 읽기 ─────────────────────────────────────────────────────


async def test_the_commit_view_rereads_the_confirmed_version_after_the_room_is_gone(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    work = await _make_work(db_session)
    note = await _note(db_session, work.pinned, "합성 노트")
    commit = await _confirm(db_session, work.novel.id)
    work.novel.chat_room_id = None
    await db_session.flush()
    view = CommitView(db_session, REGISTRY, await commit_ref(db_session, commit), source_ref_of(commit))

    with caplog.at_level(logging.WARNING, logger=_SLOT_LOGGER):
        canon = await view.source_canon()

    assert canon is not None
    assert canon.ref == source_ref_of(commit)
    assert canon.work_setting == await load_work_setting(db_session, work.novel, work.pinned)
    assert list(canon.keyword_notes) == [note.id]
    assert [record for record in caplog.records if record.name == _SLOT_LOGGER] == []
    now = await SourceCanonSlot().resolve(db_session, work.novel.id)
    assert now is not None and now.content_version_id == work.published


async def test_rereading_a_version_whose_rows_changed_warns(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    work = await _make_work(db_session)
    note = await _note(db_session, work.pinned, "합성 노트")
    commit = await _confirm(db_session, work.novel.id)
    ref = source_ref_of(commit)
    assert ref is not None
    note.info_text = "바뀐 합성 노트"
    await db_session.flush()

    with caplog.at_level(logging.WARNING, logger=_SLOT_LOGGER):
        canon = await SourceCanonSlot().load(db_session, work.novel.id, ref)

    assert canon.keyword_notes == {note.id: "바뀐 합성 노트"}
    assert canon.ref.content_version_id == ref.content_version_id
    assert canon.ref.input_hash != ref.input_hash
    assert [record.levelno for record in caplog.records if record.name == _SLOT_LOGGER] == [logging.WARNING]


# ── 읽기 전용 ─────────────────────────────────────────────────────────────


async def test_resolving_and_loading_only_read(db_session: AsyncSession) -> None:
    work = await _make_work(db_session)
    setup = await _setup(db_session, work.pinned)
    await _note(db_session, work.pinned, "합성 노트")
    await _note(db_session, work.pinned, "시작설정 합성 노트", setup_id=setup.id)
    statements: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        statements.append(statement)

    slot = SourceCanonSlot()
    sa.event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        ref = await slot.resolve(db_session, work.novel.id)
        assert ref is not None
        await slot.load(db_session, work.novel.id, ref)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", record)

    assert statements
    assert [statement for statement in statements if not statement.lstrip().upper().startswith("SELECT")] == []
